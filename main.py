from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime
import asyncio
import json
import os
import aiofiles
import scheduler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WAS_CONFIG_PATH = os.path.join(BASE_DIR, "was_config.json")
# Support both plural and singular names for the script to prevent user mistakes
LIST_SCRIPT = "list_servers.sh" if os.path.exists(os.path.join(BASE_DIR, "list_servers.sh")) else "list_server.sh"
MANAGE_SCRIPT = "manage_container.sh"

app = FastAPI(title="Container Manager API")

was_config = {}

async def load_was_config(force=False):
    global was_config
    if was_config and not force:
        return
    if os.path.exists(WAS_CONFIG_PATH):
        try:
            async with aiofiles.open(WAS_CONFIG_PATH, mode='r') as f:
                was_config = json.loads(await f.read())
                print(f"Config loaded: {list(was_config.keys())}")
        except Exception as e:
            print(f"Error loading was_config: {e}")

@app.on_event("startup")
async def startup_event():
    scheduler.start_scheduler()
    await load_was_config()
    print(f"Loaded {len(was_config)} WAS configurations.")

@app.get("/api/config/reload")
async def reload_config():
    await load_was_config()
    return {"success": True, "count": len(was_config)}

class ContainerRequest(BaseModel):
    action: Literal["start", "stop", "restart", "status"]
    servers: List[str] = Field(..., min_items=1, description="List of server names")
    was: str = "container"

@app.post("/api/container")
async def manage_container(request: ContainerRequest):
    """
    Executes the manage_container.sh script with the specified action and servers.
    """
    await load_was_config() # Uses cache unless empty
    was_key = request.was
    if was_key not in was_config:
        raise HTTPException(status_code=400, detail=f"WAS configuration for '{was_key}' not found.")
        
    cfg = was_config[was_key]
    server_args = ",".join(request.servers)
    cmd = [
        "bash", f"./{MANAGE_SCRIPT}", 
        request.action, 
        server_args,
        cfg["ip"], cfg["port"], cfg["user"], cfg["password"]
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        return {
            "success": process.returncode == 0,
            "action": request.action,
            "servers": request.servers,
            "stdout": stdout.decode().strip(),
            "stderr": stderr.decode().strip(),
            "returncode": process.returncode
        }
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="manage_container.sh script not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/container/list")
async def list_containers(was: str = "container"):
    """
    Executes list_servers.sh and returns a list of servers with their status for a specific WAS.
    """
    await load_was_config() # Uses cache unless empty
    if was not in was_config:
        raise HTTPException(status_code=400, detail=f"WAS configuration for '{was}' not found.")
        
    cfg = was_config[was]
    cmd = [
        "bash", f"./{LIST_SCRIPT}", 
        cfg["ip"], cfg["port"], cfg["user"], cfg["password"]
    ]
    
    try:
        print(f"Executing: {' '.join(cmd)}") # Debug log
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Script failed: {stderr.decode().strip()}")
            
        output = stdout.decode().strip()
        servers = []
        for line in output.split('\n'):
            parts = line.strip().split()
            if len(parts) >= 2:
                servers.append({
                    "name": parts[0],
                    "status": parts[1]
                })
        return {"servers": servers}

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="list_servers.sh script not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/time")
async def get_system_time():
    return {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

@app.get("/api/clusters")
async def get_clusters():
    return scheduler.load_clusters()

@app.get("/api/jobs/history")
async def get_job_history():
    return {"history": scheduler.get_history()}

class JobRequest(BaseModel):
    action: Literal["start", "stop", "restart"]
    servers: List[str]
    cron: str # "min hour day month dow"
    cluster_aware: bool = False
    was: str = "container"

@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": scheduler.get_jobs()}

@app.post("/api/jobs")
async def create_job(request: JobRequest):
    try:
        job_id = scheduler.add_job(
            request.action, 
            request.servers, 
            request.cron, 
            request.cluster_aware,
            request.was
        )
        return {"success": True, "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    success = scheduler.remove_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True}

# Serve Static Files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
