#!/usr/bin/env python3
"""
Minimal OpenHands SDK test
"""
import os
from dotenv import load_dotenv
from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.terminal import TerminalTool

load_dotenv()

# Configure LLM (uses env vars: LLM_BASE_URL, LLM_API_KEY, etc.)
llm_kwargs = {"base_url": os.getenv("LLM_BASE_URL")}
api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY")
if api_key:
    llm_kwargs["api_key"] = api_key
llm = LLM(
    model=os.getenv("SCOUT_MODEL"),
    **llm_kwargs,
)

# Create agent
agent = Agent(
    llm=llm,
    tools=[Tool(name=TerminalTool.name)],
)

# Create conversation
conversation = Conversation(
    agent=agent,
    workspace="/repos"
)

# Simple task
print("🤖 Sending task to agent...")
conversation.send_message("List all directories in the current workspace and tell me what you see.")

print("🚀 Running agent...")
conversation.run()

print("✅ Test complete!")
