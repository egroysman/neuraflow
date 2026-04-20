import os
import json
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=".env")

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize FastAPI
app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request model
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []

# Health check
@app.get("/")
def read_root():
    return {"message": "Clarifying AI is running"}

# Core AI logic
def run_clarification_logic(user_message, history=None):
    if history is None:
        history = []

    history_text = ""
    for item in history:
        role = item.get("role", "user")
        content = item.get("content", "")
        history_text += f"{role}: {content}\n"

    prompt = f"""
You are a finance decision AI designed to help professionals make judgment calls.

Your job:
1. Use the conversation history
2. Understand the business context
3. Determine if enough information exists to make a decision
4. If yes, give a clear recommendation
5. If not, ask one precise clarifying question

You think like:
- a finance manager
- a controller
- a senior analyst

Focus on:
- approval authority
- thresholds and limits
- policy compliance
- risk exposure
- missing financial context

Behavior rules:
- Do not ask the same question twice
- If the user already answered the key issue, move to a recommendation
- Ask only one question when a critical decision factor is missing
- Prefer a practical recommendation with assumptions over endless clarification
- Keep questions short and direct
- Keep answers practical and business-oriented

Conversation history:
{history_text}

Latest user message:
{user_message}

Return only valid JSON in this exact format:

{{
  "confidence": 0.0,
  "is_ambiguous": true,
  "interpretations": ["", ""],
  "restate": "",
  "clarifying_question": "",
  "answer": "",
  "assumptions": ""
}}

Rules:
- If enough information exists, confidence should usually be 0.7 or higher and provide an answer
- If key finance information is missing, confidence should be below 0.6 and ask one clarifying question
- If answering, leave clarifying_question as an empty string
- If asking a clarifying question, leave answer as an empty string
- Restate should reflect updated understanding after using history
"""

    response = client.responses.create(
        model="gpt-5.4",
        input=prompt
    )

    try:
        return json.loads(response.output_text)
    except Exception:
        return {
            "error": "Failed to parse response",
            "raw": response.output_text
        }

# Chat endpoint
@app.post("/chat")
def chat(req: ChatRequest):
    return run_clarification_logic(req.message, req.history)