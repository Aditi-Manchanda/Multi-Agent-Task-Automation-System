# Multi-Agent Task Automation System

This is a comprehensive **AI-powered task automation platform** that transforms complex, multi-step digital workflows into simple natural language commands.

The system acts as an intelligent orchestrator that understands human intent and automatically coordinates actions across multiple applications and services. Instead of manually switching between different apps to complete complex tasks, users can simply describe their goal in plain English and watch as specialized AI agents work together to execute the entire workflow.

## ✨ Key Features

- **Natural Language Interface** - Describe complex tasks in plain English
- **AI-Powered Planning** - Gemini AI breaks down goals into executable step-by-step plans  
- **Specialized Agent Network** - Dedicated agents for different services (Slack, Google Calendar, SMS, Web Search, File System)
- **Real-time Execution Monitoring** - Live dashboard showing plan progress and agent activities
- **Cross-Platform Integration** - Seamlessly connects and automates tasks across disconnected systems
- **Context-Aware Processing** - Agents share information and build upon previous results

## 🛠 Tech Stack

| Component | Technology |
|-----------|------------|
| Backend API | Python, FastAPI |
| AI Planning | Google Gemini API |
| Real-time Communication | WebSockets |
| Frontend | HTML5, JavaScript, CSS |
| External Integrations | Slack SDK, Google Calendar API, Twilio API, DuckDuckGo Search |
| Authentication | OAuth2 (Google), API Keys |

## 🤖 Agent Capabilities

The system includes specialized agents for different domains:

- **KnowledgeAgent** - Reads and processes local files and internal data
- **SearchAgent** - Performs live web searches using DuckDuckGo
- **CalendarAgent** - Creates and manages Google Calendar events
- **CommunicationAgent** - Sends SMS messages and initiates phone calls via Twilio
- **SlackAgent** - Posts messages and manages Slack workspace communications

## 💡 Example Use Cases

**Simple Task**: *"Find out who the CEO of Microsoft is and post it to the #announcements channel on Slack"*

**Complex Workflow**: *"Check yesterday's sales figures for our top product, verify current stock levels, and if inventory is low, send an alert to the inventory team and schedule a restocking meeting for tomorrow morning"*

**Multi-Platform Automation**: *"Send a welcome SMS to our new employee, schedule their onboarding meeting in Google Calendar, and post a welcome announcement in our team Slack channel"*

## 🎯 Project Background

Originally developed for the **Walmart Sparkathon**, this system demonstrates how AI-powered automation can streamline operations across any organization. The modular architecture allows for easy scaling and adaptation to different business contexts and integration requirements.

---

*Transform your digital workflows from manual, multi-app processes into intelligent, single-command automation.*
