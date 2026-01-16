import asyncio
import json
import logging
import subprocess
import os
import uuid
from datetime import datetime
from typing import List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler")

scheduler = BackgroundScheduler()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLUSTERS_FILE = os.path.join(BASE_DIR, "clusters.json")
HISTORY_FILE = os.path.join(BASE_DIR, "job_history.json")
JOBS_FILE = os.path.join(BASE_DIR, "scheduled_jobs.json")

def load_clusters():
    try:
        if os.path.exists(CLUSTERS_FILE):
            with open(CLUSTERS_FILE, "r") as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading clusters: {e}")
        return {}

def save_history(entry: dict):
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    history = json.load(f)
            except json.JSONDecodeError:
                pass
        
        # Prepend new entry
        history.insert(0, entry)
        # Keep last 100 entries
        if len(history) > 100:
            history = history[:100]
            
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save job history: {e}")

def get_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def _get_was_config(was_key: str):
    config_path = os.path.join(BASE_DIR, "was_config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cfg = json.load(f)
            return cfg.get(was_key, {})
    return {}

def get_server_status(server_name: str, was: str = "konetic") -> str:
    try:
        cfg = _get_was_config(was)
        if not cfg: return "UNKNOWN"
        
        script_path = os.path.join(BASE_DIR, "list_servers.sh")
        # Usage: $0 IP PORT USER PASS
        cmd = ["bash", script_path, cfg["ip"], cfg["port"], cfg["user"], cfg["password"]]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR)
        
        if result.returncode != 0:
            return "UNKNOWN"
            
        lines = result.stdout.strip().split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                status = parts[1]
                if name == server_name:
                    if '(' in status:
                        status = status.split('(')[0]
                    return status
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"

def execute_container_action(action: str, servers: List[str], was: str = "konetic"):
    cfg = _get_was_config(was)
    if not cfg: raise Exception(f"WAS config for {was} not found.")

    server_args = ",".join(servers)
    script_path = os.path.join(BASE_DIR, "manage_container.sh")
    # Usage: $0 ACTION SERVERS IP PORT USER PASS
    cmd = ["bash", script_path, action, server_args, cfg["ip"], cfg["port"], cfg["user"], cfg["password"]]
    logger.info(f"Executing action: {action} on {servers} via WAS {was}")
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR)
    if result.returncode != 0:
        raise Exception(f"Script error: {result.stderr.strip()}")
    return result.stdout.strip()

def scheduled_job_task(action: str, servers: List[str], cluster_aware: bool, job_id: str, was: str = "konetic"):
    logger.info(f"Executing scheduled task: {action} on {servers} (WAS: {was})")
    
    history_entry = {
        "id": str(uuid.uuid4())[:8],
        "job_id": job_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "targets": servers,
        "cluster_aware": cluster_aware,
        "was": was,
        "status": "PENDING",
        "detail": ""
    }

    try:
        final_targets = []
        skipped_targets = []

        if not cluster_aware:
            final_targets = servers
        else:
            clusters = load_clusters()
            for server in servers:
                my_peers = []
                # Find cluster membership
                for cluster_name, members in clusters.items():
                    if server in members:
                        my_peers = [m for m in members if m != server]
                        break
                
                if not my_peers:
                    final_targets.append(server)
                    continue
                
                # Verify safety: At least one peer must be RUNNING
                peer_statuses = []
                can_proceed = False
                for peer in my_peers:
                    status = get_server_status(peer, was)
                    peer_statuses.append(f"{peer}({status})")
                    if "RUNNING" in status:
                        can_proceed = True
                        break
                
                if can_proceed:
                    final_targets.append(server)
                else:
                    skipped_targets.append(f"{server} [Peers: {', '.join(peer_statuses)}]")

        if skipped_targets:
            history_entry["detail"] += f"Cluster Safety Skip: {', '.join(skipped_targets)}. At least one peer must be RUNNING. "

        if not final_targets:
            history_entry["status"] = "SKIPPED"
            history_entry["detail"] += "No eligible servers to run."
            save_history(history_entry)
            remove_job(job_id)
            return

        if not cluster_aware:
            # Parallel execution for non-cluster jobs
            execute_container_action(action, final_targets, was)
            history_entry["detail"] += f"Executed on: {', '.join(final_targets)}"
        else:
            # Rolling execution for cluster-aware jobs
            executed_successfully = []
            for target in final_targets:
                logger.info(f"Rolling Task: Executing {action} on {target}")
                execute_container_action(action, [target], was)
                
                # Wait for target to become RUNNING and stay stable (if action is start/restart)
                if action in ["start", "restart"]:
                    import time
                    reached_running = False
                    # Wait for initial RUNNING status (up to 1 minute)
                    for _ in range(30):
                        time.sleep(2)
                        if "RUNNING" in get_server_status(target, was):
                            reached_running = True
                            break
                    
                    if not reached_running:
                        raise Exception(f"Stability Failure: {target} failed to reach RUNNING status within 60s.")

                    # Stability Check Window: Must stay RUNNING for 10 seconds
                    logger.info(f"Rolling Task: {target} reached RUNNING. Starting 10s stability check...")
                    for i in range(5): # 5 checks * 2 seconds = 10s
                        time.sleep(2)
                        current_status = get_server_status(target, was)
                        if "RUNNING" not in current_status:
                            raise Exception(f"Stability Failure: {target} crashed (Status: {current_status}) during 10s stability window. ABORTING JOB.")
                    
                    logger.info(f"Rolling Task: {target} confirmed stable.")
                
                executed_successfully.append(target)
            
            history_entry["detail"] += f"Rolling execution completed on: {', '.join(executed_successfully)}"

        history_entry["status"] = "SUCCESS"
    
    except Exception as e:
        history_entry["status"] = "FAILED"
        history_entry["detail"] += str(e)
        logger.error(f"Job failed: {e}")
    
    save_history(history_entry)
    remove_job(job_id)

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started.")
        jobs = _load_persistent_jobs()
        for job in jobs:
            try:
                run_date = datetime.fromisoformat(job['run_date'])
                if run_date < datetime.now():
                    logger.info(f"Skipping expired job: {job['id']}")
                    _remove_persistent_job(job['id'])
                    continue

                trigger = DateTrigger(run_date=run_date)
                scheduler.add_job(
                    scheduled_job_task,
                    trigger,
                    args=[job['action'], job['servers'], job['cluster_aware'], job['id'], job.get('was', 'konetic')],
                    id=job['id'],
                    replace_existing=True
                )
                logger.info(f"Restored job: {job['id']} for {run_date}")
            except Exception as e:
                logger.error(f"Failed to restore job {job['id']}: {e}")

def _load_persistent_jobs():
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading persistent jobs: {e}")
    return []

def _save_persistent_job(job_data):
    jobs = _load_persistent_jobs()
    # Filter out if already exists
    jobs = [j for j in jobs if j['id'] != job_data['id']]
    jobs.append(job_data)
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2)

def _remove_persistent_job(job_id):
    jobs = _load_persistent_jobs()
    jobs = [j for j in jobs if j['id'] != job_id]
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2)

def add_job(action: str, servers: List[str], cron: str, cluster_aware: bool = False, was: str = "konetic"):
    # Parse simplified cron (min hour * * *) to calculate next run_date
    parts = cron.split()
    minute = int(parts[0])
    hour = int(parts[1])

    now = datetime.now()
    run_date = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # If time has already passed today, schedule for tomorrow
    if run_date < now:
        run_date += timedelta(days=1)

    job_id = str(uuid.uuid4())[:8]
    
    # Persist with run_date instead of cron
    _save_persistent_job({
        "id": job_id,
        "action": action,
        "servers": servers,
        "run_date": run_date.isoformat(),
        "cluster_aware": cluster_aware,
        "was": was
    })

    trigger = DateTrigger(run_date=run_date)
    scheduler.add_job(
        scheduled_job_task,
        trigger,
        args=[action, servers, cluster_aware, job_id, was],
        id=job_id,
        replace_existing=True
    )
    logger.info(f"Job {job_id} scheduled for {run_date}")
    return job_id

def get_jobs():
    jobs = []
    for job in scheduler.get_jobs():
        # APScheduler trigger to string is simplified cron expression
        trigger_str = str(job.trigger) 
        # CronTrigger str is like "cron[minute='*', hour='*', ...]"
        # We can try to extract parts or just return the str
        jobs.append({
            "id": job.id,
            "next_run_time": str(job.next_run_time),
            "args": job.args[:3],
            "trigger": trigger_str
        })
    return jobs

def remove_job(job_id: str):
    _remove_persistent_job(job_id)
    try:
        scheduler.remove_job(job_id)
        return True
    except JobLookupError:
        return False
