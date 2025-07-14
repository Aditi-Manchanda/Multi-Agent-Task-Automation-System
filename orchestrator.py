import os
import re
import json
import asyncio
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from agents import SlackAgent, KnowledgeAgent, SearchAgent, CalendarAgent, CommunicationAgent

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
)

PLANNER_PROMPT_TEMPLATE = """
You are an expert planning agent. Your job is to create a plan to fulfill a user's request.
Here are the available agents and their EXACT action formats:

- "KnowledgeAgent":
  * To add knowledge: "Add knowledge: 'content here' in filename"
  * To query: "What is [question]?"
- "SearchAgent": "Search for [query]"
- "SlackAgent": "Post \"message text\" to #channel"
- "CalendarAgent": "Schedule [event name] for [time]"
- "CommunicationAgent": "Send SMS to [number]: [message]"

CRITICAL: Use the exact formats shown above. For SlackAgent, always use: Post "message"
to #channel

Respond with ONLY a JSON array of steps (no backticks or extra text).
Each step must have "agent" and "action" fields.

User Request: "{user_prompt}"
"""

class TaskOrchestrator:
    def __init__(self, task_id: str, prompt: str, ws_manager):
        self.task_id = task_id
        self.prompt = prompt
        self.ws_manager = ws_manager

        self.knowledge_agent = KnowledgeAgent()
        self.search_agent = SearchAgent()
        self.calendar_agent = CalendarAgent()
        self.communication_agent = CommunicationAgent()

        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            raise RuntimeError("Missing SLACK_BOT_TOKEN")
        self.slack_agent = SlackAgent(token=slack_token)

        self.plan = []
        self.context = {}

    async def _gemini_request(self, data: dict, template: str, is_json=True):
        if not GEMINI_API_KEY:
            raise RuntimeError("Missing GEMINI_API_KEY")
        payload = {"contents": [{"parts": [{"text": template.format(**data)}]}]}
        r = requests.post(GEMINI_API_URL, json=payload, timeout=60)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if is_json:
            clean = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            clean = re.sub(r"\s*```$", "", clean).strip()
            return json.loads(clean)
        return text

    async def execute_plan(self):
        m = re.search(
            r"Post a message on\s+(#[^\s]+)\s+channel in Slack saying ['\"](.+?)['\"]",
            self.prompt,
            flags=re.IGNORECASE
        )
        if m:
            channel, msg = m.group(1), m.group(2)
            action = f'Post "{msg}" to {channel}'
            self.plan = [{"agent": "SlackAgent", "action": action}]
        else:
            await self.ws_manager.broadcast(json.dumps({
                "type": "log",
                "agent": "PlannerAgent",
                "message": "Generating plan...",
                "log_type": "info"
            }))
            try:
                plan = await self._gemini_request({"user_prompt": self.prompt}, PLANNER_PROMPT_TEMPLATE)
                self.plan = plan if isinstance(plan, list) else [plan]
            except Exception as e:
                await self.ws_manager.broadcast(json.dumps({
                    "type": "log",
                    "agent": "System",
                    "message": f"Plan error: {e}",
                    "log_type": "error"
                }))
                return

        await self.ws_manager.broadcast(json.dumps({"type": "plan", "steps": self.plan}))
        for step in self.plan:
            await asyncio.sleep(1)
            await self._execute_step(step)

        await self.ws_manager.broadcast(json.dumps({
            "type": "log",
            "agent": "System",
            "message": "Task completed",
            "log_type": "success"
        }))

    async def _execute_step(self, step):
        agent, action = step["agent"], step["action"]
        await self.ws_manager.broadcast(json.dumps({
            "type": "status_update", "step_action": action, "status": "in-progress"
        }))
        await self.ws_manager.broadcast(json.dumps({
            "type": "log", "agent": agent, "message": f"Starting: {action}", "log_type": "info"
        }))

        try:
            if agent == "KnowledgeAgent":
                if action.lower().startswith("add knowledge"):
                    match = re.search(r"add knowledge:\s*['\"](.+?)['\"].*in\s+(\w+)", action, re.IGNORECASE)
                    if match:
                        content, filename = match.groups()
                        resp = await self.knowledge_agent.add_knowledge(filename, content)
                        msg = resp
                    else:
                        raise ValueError(f"Could not parse knowledge add action: {action}")
                else:
                    resp = await self.knowledge_agent.run(action)
                    msg = f"Knowledge query completed"

            elif agent == "SlackAgent":
                print(f"🔷 SlackAgent.execute got action: {action}")
                resp = await self.slack_agent.execute(action)
                msg = f"Slack message posted successfully"

            elif agent == "CalendarAgent":
                event_details = self._parse_calendar_action(action)
                resp = await self.calendar_agent.run(event_details)
                msg = f"Calendar event created: {resp}"

            elif agent == "SearchAgent":
                resp = await self.search_agent.run(action)
                msg = f"Search completed: {resp[:50]}..."

            elif agent == "CommunicationAgent":
                msg = "SMS feature called (add actual logic if needed)"
                resp = None  
            else:
                await asyncio.sleep(1)
                msg = f"Executed {agent}"
                resp = None

            status = "completed"
            lt = "success"

        except Exception as e:
            msg = f"Error: {e}"
            status = "failed"
            lt = "error"

        await self.ws_manager.broadcast(json.dumps({
            "type": "status_update", "step_action": action, "status": status
        }))
        await self.ws_manager.broadcast(json.dumps({
            "type": "log", "agent": agent, "message": msg, "log_type": lt
        }))

    def _parse_calendar_action(self, action: str) -> dict:
        """Parse calendar action to extract event title, start, and end times."""
        title_match = re.search(r'schedule\s+(?:a\s+)?(.+?)\s+for', action, re.IGNORECASE)
        title = title_match.group(1) if title_match else "Meeting"

        tomorrow = datetime.now() + timedelta(days=1)

        time_match = re.search(r'tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', action, re.IGNORECASE)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            period = time_match.group(3)
            if period:
                if period.lower() == 'pm' and hour != 12:
                    hour += 12
                elif period.lower() == 'am' and hour == 12:
                    hour = 0
            start_time = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            start_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

        end_time = start_time + timedelta(hours=1)
        return {
            "title": title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat()
        }

