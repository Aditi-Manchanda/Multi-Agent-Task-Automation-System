"""
agents.py – rewritten 07 Jul 2025
---------------------------------
Utility “agents” used by TaskOrchestrator.

If a service (Slack, Google Calendar, Twilio, etc.) is not configured in
`.env`, the related agent will degrade gracefully instead of crashing
FastAPI with a 500.
"""
from __future__ import annotations

import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from dotenv import load_dotenv
from duckduckgo_search import DDGS
import requests

# ---------- 3rd‑party SDKs ----------
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from twilio.rest import Client

# -----------------------------------------------------------------------
#               ENVIRONMENT & PATH SET‑UP
# -----------------------------------------------------------------------
load_dotenv()  # makes the .env values available immediately

BASE_DIR            = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH    = os.path.join(BASE_DIR, "credentials.json")
TOKEN_PATH          = os.path.join(BASE_DIR, "token.json")

SLACK_BOT_TOKEN     = os.getenv("SLACK_BOT_TOKEN", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")

TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

# -----------------------------------------------------------------------
#               SLACK AGENT
# -----------------------------------------------------------------------
class SlackAgent:
    """Send messages to Slack asynchronously."""
    def __init__(self, token: str = SLACK_BOT_TOKEN):
        if not token:
            raise RuntimeError("SLACK_BOT_TOKEN missing – SlackAgent cannot start.")
        self.client = AsyncWebClient(token=token)

    async def execute(self, action: str) -> Dict[str, Any]:
        """
        Expected formats:
          Post "hello world" to #general
          post_message(channel='#general', message='hello world')
        """
        print("🔷 SlackAgent.execute got action:", action)

        # pattern 1 – strict “Post … to” form
        m = re.match(r'^Post\s+"(.+)"\s+to\s+(#[^\s]+)$', action, flags=re.IGNORECASE)
        if m:
            msg, channel = m.groups()
        else:
            # pattern 2 – function‑call style
            m = re.match(r"post_message\(channel='(#[^']+)',\s*message='(.+)'\)", action,
                         flags=re.IGNORECASE)
            if not m:
                raise ValueError(f"Could not parse Slack action: {action!r}")
            channel, msg = m.groups()

        try:
            return await self.client.chat_postMessage(channel=channel, text=msg)
        except SlackApiError as e:
            # Don’t kill FastAPI – just surface the reason up‑stack
            raise RuntimeError(f"Slack API error: {e.response['error']}")

# -----------------------------------------------------------------------
#               KNOWLEDGE AGENT (local txt files + Gemini query)
# -----------------------------------------------------------------------
class KnowledgeAgent:
    def __init__(self, directory: str = "knowledge_base") -> None:
        self.directory = os.path.join(BASE_DIR, directory)
        os.makedirs(self.directory, exist_ok=True)
        self.knowledge = self._load_knowledge()

    # ---------- helpers ----------
    def _load_knowledge(self) -> str:
        corpus = []
        for fn in os.listdir(self.directory):
            if fn.endswith(".txt"):
                with open(os.path.join(self.directory, fn), encoding="utf‑8") as f:
                    corpus.append(f.read())
        return "\n\n".join(corpus)

    # ---------- public API ----------
    async def add_knowledge(self, filename: str, content: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", filename)
        fp   = os.path.join(self.directory, f"{safe}.txt")
        with open(fp, "w", encoding="utf‑8") as f:
            f.write(content.strip() + "\n")
        self.knowledge = self._load_knowledge()
        return f"Knowledge stored in {safe}.txt"

    async def run(self, query: str) -> str:
        if not self.knowledge:
            return "Knowledge base is empty."

        prompt = (
            f"Context:\n{self.knowledge}\n\n"
            f"Question: {query}\n\n"
            "Answer based only on the context:"
        )

        if not GEMINI_API_KEY:
            return "(Gemini not configured) " + prompt

        url  = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        body = {"contents": [{"parts": [{"text": prompt}]}]}

        try:
            r = requests.post(url, json=body, timeout=60)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            return f"Gemini request failed: {e}"

# -----------------------------------------------------------------------
#               SEARCH AGENT
# -----------------------------------------------------------------------
class SearchAgent:
    async def run(self, query: str) -> str:
        try:
            with DDGS() as ddgs:
                hits = [r for r in ddgs.text(query, max_results=3)]
            return "\n".join(f"{h['title']}: {h['body']}" for h in hits) or "No results."
        except Exception as e:
            return f"Search error: {e}"

# -----------------------------------------------------------------------
#               CALENDAR AGENT  (lazy‑auth)
# -----------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]
class CalendarAgent:
    """
    Lazily obtains credentials the first time `run()` is called.  If the
    Google Calendar flow cannot be completed (e.g., running headless on
    a server), we simply raise a controlled error instead of crashing
    during import.
    """
    def __init__(self) -> None:
        self.creds: Credentials | None = None

    # ---------- helpers ----------
    def _get_credentials(self) -> Credentials:
        if self.creds and self.creds.valid:
            return self.creds

        if os.path.exists(TOKEN_PATH):
            self.creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_PATH):
                    raise RuntimeError(
                        "Google Calendar is not configured – credentials.json missing."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                # WARNING: opens a local browser – only do this on a workstation
                self.creds = flow.run_local_server(port=0)

            with open(TOKEN_PATH, "w") as token:
                token.write(self.creds.to_json())

        return self.creds

    # ---------- public API ----------
    async def run(self, event: Dict[str, str]) -> str:
        """
        event = {"title": "...", "start_time": ISO8601, "end_time": ISO8601}
        """
        creds = self._get_credentials()
        try:
            service = build("calendar", "v3", credentials=creds)
            evt     = {
                "summary": event["title"],
                "start": {"dateTime": event["start_time"], "timeZone": "Asia/Kolkata"},
                "end":   {"dateTime": event["end_time"],   "timeZone": "Asia/Kolkata"},
            }
            created = service.events().insert(calendarId="primary", body=evt).execute()
            return created.get("htmlLink", "Created")
        except HttpError as e:
            raise RuntimeError(f"Google Calendar API error: {e}")

# -----------------------------------------------------------------------
#               COMMUNICATION AGENT (Twilio SMS / voice)
# -----------------------------------------------------------------------
class CommunicationAgent:
    def __init__(self) -> None:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
            self.client = None
            print("⚠️  Twilio not configured – CommunicationAgent disabled.")
        else:
            self.client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    # ---------- public API ----------
    def send_sms(self, recipient: str, message: str) -> str:
        if not self.client:
            raise RuntimeError("Twilio client not initialised.")
        msg = self.client.messages.create(
            body=message, from_=TWILIO_PHONE_NUMBER, to=recipient
        )
        return msg.sid

    def make_call(self, recipient: str, message: str) -> str:
        if not self.client:
            raise RuntimeError("Twilio client not initialised.")
        twiml = f"<Response><Say>{message}</Say></Response>"
        call  = self.client.calls.create(twiml=twiml, to=recipient, from_=TWILIO_PHONE_NUMBER)
        return call.sid
