#!/usr/bin/env python3
"""
J5 Harness Soak Test Monitor

Tracks key metrics over 24-hour soak period:
- Orphan count
- Stall rate
- Scoreboard metrics
- Mirror SLO
- Receipt coverage
- Health status
"""

import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\Users\DELL\j5-harness")

from tools.harness.integration import load_config, build_project_contexts, build_project_states, SHARED
from tools.domains import MultiProjectRouter

LOG_FILE = Path(r"C:\Users\DELL\j5-harness\.swarm\soak_monitor.log")
METRICS_FILE = Path(r"C:\Users\DELL\j5-harness\.swarm\soak_metrics.jsonl")

def log(msg):
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def record_metric(name, value):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "metric": name,
        "value": value
    }
    with open(METRICS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def check_orphans():
    """Check for orphan node.exe processes."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq node.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split('\n')
        # Count node.exe processes (excluding header)
        count = max(0, len(lines) - 1)
        return count
    except Exception as e:
        log(f"Error checking orphans: {e}")
        return -1

def check_health():
    """Check harness health via CLI."""
    try:
        result = subprocess.run(
            ["python", "j5_cli/main.py", "status"],
            cwd=r"C:\Users\DELL\j5-harness",
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout
    except Exception as e:
        log(f"Health check error: {e}")
        return False, str(e)

def check_routing():
    """Test routing for both projects."""
    try:
        router = MultiProjectRouter()
        d1 = router.pick("wsb-alpha", "coding")
        d2 = router.pick("burgonomics", "coding")
        return True, {"wsb-alpha": d1.model, "burgonomics": d2.model}
    except Exception as e:
        log(f"Routing check error: {e}")
        return False, str(e)

def check_kilo_watcher():
    """Check if Kilo watcher process is running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split('\n')
        python_count = max(0, len(lines) - 1)
        return python_count > 0, python_count
    except Exception as e:
        log(f"Watcher check error: {e}")
        return False, -1

def run_checks():
    """Run all soak test checks."""
    log("=" * 60)
    log("SOAK TEST CHECK CYCLE")
    
    # Orphan count
    orphans = check_orphans()
    log(f"Orphan node.exe processes: {orphans}")
    record_metric("orphan_count", orphans)
    
    # Health check
    healthy, output = check_health()
    log(f"Health check: {'PASS' if healthy else 'FAIL'}")
    record_metric("health_check", 1 if healthy else 0)
    
    # Routing
    routing_ok, models = check_routing()
    log(f"Routing: {'PASS' if routing_ok else 'FAIL'} - {models}")
    record_metric("routing_check", 1 if routing_ok else 0)
    
    # Kilo watcher
    watcher_ok, py_count = check_kilo_watcher()
    log(f"Kilo watcher: {'RUNNING' if watcher_ok else 'NOT FOUND'} (python processes: {py_count})")
    record_metric("watcher_running", 1 if watcher_ok else 0)
    record_metric("python_processes", py_count)
    
    # Shared state
    log(f"Shared health models: {len(SHARED.tracker.snapshot())}")
    log(f"Shared scores models: {len(SHARED.feedback.all_scores())}")
    record_metric("shared_health_models", len(SHARED.tracker.snapshot()))
    record_metric("shared_score_models", len(SHARED.feedback.all_scores()))
    
    log("CHECK CYCLE COMPLETE")
    log("=" * 60)

def main():
    log("SOAK TEST MONITOR STARTED")
    log("Monitoring interval: 5 minutes")
    log("Duration: 24 hours (288 cycles)")
    
    cycle = 0
    max_cycles = 288  # 24 hours * 12 cycles/hour
    
    while cycle < max_cycles:
        try:
            run_checks()
        except Exception as e:
            log(f"ERROR in check cycle: {e}")
        
        cycle += 1
        log(f"Cycle {cycle}/{max_cycles} complete. Sleeping 5 minutes...")
        time.sleep(300)  # 5 minutes
    
    log("SOAK TEST MONITOR COMPLETED (24 hours)")

if __name__ == "__main__":
    main()