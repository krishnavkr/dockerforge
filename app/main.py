import os
import asyncio
import json
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Dict, Optional
from dotenv import load_dotenv

# I load my local configuration environment
load_dotenv()

from app.agent import DockerForgeAgent

app = FastAPI(
    title="DockerForge Developer Console",
    description="I built this AI-powered Dockerfile generator and self-healing agent system.",
    version="1.0.0"
)

# Store running agents in-memory
# session_id -> DockerForgeAgent
active_agents: Dict[str, DockerForgeAgent] = {}

# Ensure standard templates and static folders exist
os.makedirs("app/templates", exist_ok=True)
os.makedirs("app/static/css", exist_ok=True)
os.makedirs("app/static/js", exist_ok=True)

# Mount my static asset folders
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

class GenerateRequest(BaseModel):
    repo_url: str
    api_key: Optional[str] = None
    force_simulation: bool = False

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """
    I serve my main gorgeous developer dashboard interface.
    """
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/health")
async def get_health():
    """
    I check if my system environment has Docker running and if the Gemini API Key is configured.
    """
    # Instantiate a quick agent to check docker presence
    test_agent = DockerForgeAgent(repo_url="", api_key="")
    return {
        "status": "online",
        "docker_available": test_agent.docker_available,
        "api_key_configured": bool(os.getenv("GEMINI_API_KEY")),
        "default_simulation_mode": os.getenv("ENABLE_SIMULATION_MODE", "false").lower() == "true"
    }

@app.post("/api/generate")
async def start_generation(payload: GenerateRequest, background_tasks: BackgroundTasks):
    """
    I initiate a new containerization agent thread for the provided repository.
    """
    repo = payload.repo_url.strip()
    if not repo:
        raise HTTPException(status_code=400, detail="I need a valid GitHub repository URL.")
    
    # Initialize the agent
    agent = DockerForgeAgent(
        repo_url=repo,
        api_key=payload.api_key.strip() if payload.api_key else None,
        force_simulation=payload.force_simulation
    )
    
    active_agents[agent.session_id] = agent
    
    # Start the agent processing in the background
    background_tasks.add_task(agent.run)
    
    agent.log(f"I registered background worker for session {agent.session_id}.", "INFO")
    return {
        "session_id": agent.session_id,
        "is_simulated": agent.is_simulated
    }

@app.get("/api/stream/{session_id}")
async def stream_logs(session_id: str):
    """
    I stream my agent's progress, state changes, thoughts, and compiler logs in real-time
    directly to the frontend terminal using Server-Sent Events (SSE).
    """
    if session_id not in active_agents:
        raise HTTPException(status_code=404, detail="I could not find a running session for that ID.")
        
    agent = active_agents[session_id]
    
    async def log_generator():
        last_yielded_idx = 0
        
        while True:
            # Yield any new logs that have accrued
            current_logs_len = len(agent.logs)
            if current_logs_len > last_yielded_idx:
                for i in range(last_yielded_idx, current_logs_len):
                    log_line = agent.logs[i]
                    yield f"event: log\ndata: {json.dumps({'line': log_line})}\n\n"
                last_yielded_idx = current_logs_len
            
            # Yield the current execution state
            state_payload = {
                "state": agent.current_state,
                "detected_language": agent.detected_language,
                "dockerfile": agent.dockerfile_content,
                "compose": agent.compose_content
            }
            yield f"event: state\ndata: {json.dumps(state_payload)}\n\n"
            
            # Break if agent finished processing
            if agent.current_state in ("ready", "failed"):
                # Make sure we flush any final logs
                if len(agent.logs) > last_yielded_idx:
                    for i in range(last_yielded_idx, len(agent.logs)):
                        log_line = agent.logs[i]
                        yield f"event: log\ndata: {json.dumps({'line': log_line})}\n\n"
                break
                
            await asyncio.sleep(0.3)
            
    return StreamingResponse(log_generator(), media_type="text/event-stream")
