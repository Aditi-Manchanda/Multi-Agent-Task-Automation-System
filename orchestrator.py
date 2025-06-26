import asyncio
import json
import requests
import os
from agents import CalendarAgent, CommunicationAgent, SearchAgent, KnowledgeAgent, SlackAgent
from datetime import datetime

# IMPORTANT: Paste your Gemini API Key here.
GEMINI_API_KEY = "AIzaSyCM-E0l0TMZZnrYw7sB_ci9atR-2o3Pbio"
# This line is important for the KnowledgeAgent to access the key
os.environ['GEMINI_API_KEY_HOLDER'] = GEMINI_API_KEY
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"


# --- PROMPTS ---
PLANNER_PROMPT_TEMPLATE = """
You are an expert planning agent. Your job is to create a plan to fulfill a user's request.

Here are the available agents:
- "KnowledgeAgent": Use this agent FIRST for any questions about internal data (e.g., "who is our CEO?").
- "SearchAgent": A general web search agent for public information (e.g., "what is the weather?").
- "SlackAgent": Can post messages to a specific Slack channel.
- "CommunicationAgent": Can make phone calls or send text messages.
- "CalendarAgent": Can interact with a user's calendar.
- "FilterAgent", "BookingAgent", "MonitoringAgent", "UserInteractionAgent": Other specialized agents.

Based on the user's request, create a JSON array of steps.

Example Request: "Announce on the #engineering Slack channel that the new server is deployed."

Example Output:
[
    { "agent": "SlackAgent", "action": "Post to #engineering: The new server is deployed." }
]

User Request: "{user_prompt}"
"""

SLACK_PARSER_PROMPT_TEMPLATE = """
You are a data extraction tool. Extract the 'channel' and 'message' from the text.
The channel usually starts with a '#'.

Text: "{action_text}"

JSON Output:
"""

EVENT_PARSER_PROMPT_TEMPLATE = """
You are a data extraction tool. Your job is to extract event details from a given text and provide them in a JSON format.
The text describes a calendar event. Extract the 'title', 'start_time', and 'end_time'.
The current date is {current_date}. All relative times like "tomorrow" or "next week" should be resolved based on this date.
The output must be a single JSON object with keys "title", "start_time", and "end_time" in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
If an end time is not specified, assume the event is one hour long.

Text: "{action_text}"

JSON Output:
"""

COMMUNICATION_PARSER_PROMPT_TEMPLATE = """
You are a data extraction tool. Your job is to extract communication task details from a given text and provide them in a JSON format.
From the text, extract the 'type' (must be "call" or "sms"), the 'recipient' (the phone number in E.164 format), and the 'message' (the content to be said or sent).

Text: "{action_text}"

JSON Output:
"""

SEARCH_QUERY_PARSER_PROMPT_TEMPLATE = """
You are a data extraction tool. Your job is to extract a concise web search query from a given text.
The query should be what a user would type into Google.

Text: "{action_text}"

Search Query:
"""

class TaskOrchestrator:
    def __init__(self, task_id: str, prompt: str, ws_manager):
        self.task_id = task_id
        self.prompt = prompt
        self.ws_manager = ws_manager
        self.plan = []
        self.context = {} 
        # Initialize agents
        self.calendar_agent = CalendarAgent()
        self.communication_agent = CommunicationAgent()
        self.search_agent = SearchAgent()
        self.knowledge_agent = KnowledgeAgent()
        self.slack_agent = SlackAgent()

    async def _gemini_request(self, prompt, parser_template, is_json_output=True):
        """Generic function to make a request to the Gemini API."""
        if not GEMINI_API_KEY:
             raise ValueError("GEMINI_API_KEY is not set in orchestrator.py")
        
        headers = {"Content-Type": "application/json"}
        final_prompt = parser_template.format(**prompt)
        payload = {"contents": [{"parts": [{"text": final_prompt}]}]}
        
        response = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        response_json = response.json()
        content_part = response_json['candidates'][0]['content']['parts'][0]['text']
        
        if is_json_output:
            return json.loads(content_part.strip().lstrip("```json").rstrip("```").strip())
        return content_part.strip()

    async def execute_plan(self):
        try:
            await self.ws_manager.broadcast(json.dumps({"type": "log", "agent": "PlannerAgent", "message": "Contacting Gemini API to create an execution plan...", "log_type": "info"}))
            self.plan = await self._gemini_request({"user_prompt": self.prompt}, PLANNER_PROMPT_TEMPLATE)
            for step in self.plan:
                step['status'] = 'pending'
            await self.ws_manager.broadcast(json.dumps({"type": "plan", "steps": self.plan}))
        except Exception as e:
            await self.ws_manager.broadcast(json.dumps({"type": "log", "agent": "System", "message": f"Failed to create a task plan: {e}", "log_type": "error"}))
            return

        for step in self.plan:
            await asyncio.sleep(1)
            # Inject context from previous steps into the current action
            try:
                step['action'] = step['action'].format(**self.context)
            except KeyError as e:
                print(f"Skipping format for action '{step['action']}' due to missing key: {e}")

            await self._execute_step(step)

        await self.ws_manager.broadcast(json.dumps({"type": "log", "agent": "System", "message": "Task automation completed.", "log_type": "success"}))

    async def _execute_step(self, step: dict):
        agent_name = step.get('agent', 'UnknownAgent')
        action = step.get('action', 'No action defined')

        await self.ws_manager.broadcast(json.dumps({"type": "status_update", "step_action": action, "status": "in-progress"}))
        await self.ws_manager.broadcast(json.dumps({"type": "log", "agent": agent_name, "message": f"Starting: {action}...", "log_type": "info"}))

        execution_result = f"Action Completed: {action}"
        try:
            if agent_name == "SlackAgent":
                slack_details = await self._gemini_request({"action_text": action}, SLACK_PARSER_PROMPT_TEMPLATE)
                message_to_send = slack_details["message"].format(**self.context)
                await self.slack_agent.run(slack_details["channel"], message_to_send)
                execution_result = f"Message successfully posted to Slack channel {slack_details['channel']}."

            elif agent_name == "KnowledgeAgent":
                answer = await self.knowledge_agent.run(action)
                self.context['knowledge_answer'] = answer
                execution_result = f"Knowledge Base Answer: {answer}"

            elif agent_name == "SearchAgent":
                query = await self._gemini_request({"action_text": action}, SEARCH_QUERY_PARSER_PROMPT_TEMPLATE, is_json_output=False)
                search_results = await self.search_agent.run(query)
                self.context['search_result'] = search_results 
                execution_result = f"Search for '{query}' found: {search_results}"

            elif agent_name == "CalendarAgent":
                event_details = await self._gemini_request({"action_text": action, "current_date": datetime.now().strftime("%A, %Y-%m-%d")}, EVENT_PARSER_PROMPT_TEMPLATE)
                event_link = await self.calendar_agent.run(event_details)
                execution_result = f"Successfully created event. View: {event_link}"
            
            elif agent_name == "CommunicationAgent":
                comm_details = await self._gemini_request({"action_text": action}, COMMUNICATION_PARSER_PROMPT_TEMPLATE)
                message_to_send = comm_details["message"].format(**self.context)
                
                if comm_details.get("type") == "sms":
                    sms_sid = self.communication_agent.send_sms(comm_details["recipient"], message_to_send)
                    execution_result = f"SMS to {comm_details['recipient']} sent successfully. SID: {sms_sid}"
                elif comm_details.get("type") == "call":
                    call_sid = self.communication_agent.make_call(comm_details["recipient"], message_to_send)
                    execution_result = f"Call to {comm_details['recipient']} initiated. SID: {call_sid}"
            
            else: # Fallback for simulated agents
                print(f"Executing (Simulated): {agent_name} -> {action}")
                await asyncio.sleep(2)
        
        except Exception as e:
            execution_result = f"Action failed. Error: {e}"
            print(f"Error during execution: {e}")

        await self.ws_manager.broadcast(json.dumps({"type": "status_update", "step_action": action, "status": "completed"}))
        await self.ws_manager.broadcast(json.dumps({"type": "log", "agent": agent_name, "message": execution_result, "log_type": "info"}))

