import os
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from twilio.rest import Client
from duckduckgo_search import DDGS
import requests
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

TWILIO_ACCOUNT_SID = "" 
TWILIO_AUTH_TOKEN = ""  
TWILIO_PHONE_NUMBER = ""
SLACK_BOT_TOKEN = "" 

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY_HOLDER', '')

# --- Slack Agent ---
class SlackAgent:
    """An agent that can post messages to Slack."""
    def __init__(self):
        if not SLACK_BOT_TOKEN:
            print("WARNING: SLACK_BOT_TOKEN not set. SlackAgent will not work.")
            self.client = None
        else:
            self.client = AsyncWebClient(token=SLACK_BOT_TOKEN)

    async def run(self, channel: str, message: str):
        if not self.client:
            raise Exception("Slack client not initialized. Check credentials.")
        
        try:
            response = await self.client.chat_postMessage(channel=channel, text=message)
            assert response["ok"]
            print(f"Message posted to {channel}")
        except SlackApiError as e:
            raise Exception(f"Error posting to Slack: {e.response['error']}")


# --- Knowledge Base Agent ---
class KnowledgeAgent:
    """Answers questions based on files in the 'knowledge_base' directory."""
    def __init__(self, directory="knowledge_base"):
        self.directory = directory
        self.knowledge = self._load_knowledge()

    def _load_knowledge(self):
        """Loads all .txt files from the specified directory."""
        if not os.path.exists(self.directory):
            print(f"Warning: Knowledge base directory '{self.directory}' not found. Creating it.")
            os.makedirs(self.directory)
            return ""
        
        full_text = ""
        for filename in os.listdir(self.directory):
            if filename.endswith(".txt"):
                with open(os.path.join(self.directory, filename), 'r', encoding='utf-8') as f:
                    full_text += f.read() + "\n\n"
        return full_text

    async def run(self, query: str) -> str:
        """Answers a query using the loaded knowledge and Gemini."""
        if not self.knowledge:
            return "The knowledge base is empty. Please add .txt files to the 'knowledge_base' directory."
        
        prompt_template = """
        You are a helpful assistant. Answer the following 'Question' based ONLY on the provided 'Context'.
        If the answer is not found in the context, say "I don't have that information in my knowledge base."

        Context:
        ---
        {context}
        ---
        Question: {question}
        Answer:
        """
        
        final_prompt = prompt_template.format(context=self.knowledge, question=query)
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": final_prompt}]}]}
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

        try:
            response = requests.post(gemini_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            response_json = response.json()
            return response_json['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            return f"An error occurred while consulting the knowledge base: {e}"

# --- Search Agent ---
class SearchAgent:
    """An agent that can search the web using DuckDuckGo."""
    async def run(self, query: str) -> str:
        """Performs a web search and returns a summary of the top results."""
        print(f"Searching the web for: '{query}'")
        try:
            with DDGS() as ddgs:
                results = [r for r in ddgs.text(query, max_results=3)]
                if not results:
                    return "No results found."
                
                summary = "Found articles:\n"
                for i, result in enumerate(results):
                    summary += f"{i+1}. {result['title']}\n"
                return summary
        except Exception as e:
            print(f"An error occurred during web search: {e}")
            return f"Error during search: {e}"

# --- Google Calendar Agent ---
SCOPES = ["https://www.googleapis.com/auth/calendar"]

class CalendarAgent:
    """An agent that can interact with Google Calendar."""
    def __init__(self):
        self.creds = self._get_credentials()

    def _get_credentials(self):
        """Gets valid user credentials from storage or initiates login."""
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        return creds

    async def run(self, event_details: dict):
        """Creates an event on the user's primary calendar."""
        try:
            service = build("calendar", "v3", credentials=self.creds)
            event = {
                "summary": event_details.get("title", "No Title Provided"),
                "start": {"dateTime": event_details["start_time"], "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": event_details["end_time"], "timeZone": "Asia/Kolkata"},
            }
            event = service.events().insert(calendarId="primary", body=event).execute()
            return event.get('htmlLink')
        except HttpError as error:
            raise Exception(f"Google Calendar API Error: {error}")

# --- Communication Agent ---
class CommunicationAgent:
    """An agent for making calls and sending SMS via Twilio."""
    def __init__(self):
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
            print("WARNING: Twilio credentials are not set in agents.py. CommunicationAgent will not work.")
            self.client = None
        else:
            self.client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    def send_sms(self, recipient: str, message: str) -> str:
        if not self.client:
            raise Exception("Twilio client not initialized. Check credentials.")
        message = self.client.messages.create(body=message, from_=TWILIO_PHONE_NUMBER, to=recipient)
        return message.sid

    def make_call(self, recipient: str, message: str) -> str:
        if not self.client:
            raise Exception("Twilio client not initialized. Check credentials.")
        twiml_message = f'<Response><Say>{message}</Say></Response>'
        call = self.client.calls.create(twiml=twiml_message, to=recipient, from_=TWILIO_PHONE_NUMBER)
        return call.sid
