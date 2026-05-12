#!/usr/bin/env python3
"""
Test 5: Python script that polls a Stata log file for "done" markers.
Simulates the agent-side polling loop for background tasks.
"""

import subprocess
import sys
import os
import time
import re
import signal

def poll_log(log_path: str, pid: int, poll_interval: float = 1.0, timeout: float = 120.0):
    """
    Poll a Stata batch log file for progress markers.
    
    Args:
        log_path: Path to the Stata log file (*.log from -b mode)
        pid: Process ID of the Stata process
        poll_interval: How often to check (seconds)
        timeout: Maximum time to wait (seconds)
    
    Returns:
        dict with status, exit_code, lines_output, elapsed
    """
    start_time = time.time()
    last_size = 0
    progress_line_count = 0
    output_lines = []
    
    print(f"[poll_log] Watching log: {log_path}")
    print(f"[poll_log] PID: {pid}")
    print(f"[poll_log] Poll interval: {poll_interval}s, Timeout: {timeout}s")
    print("-" * 60)
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            print(f"[poll_log] TIMEOUT after {elapsed:.1f}s")
            return {
                "status": "timeout",
                "exit_code": None,
                "elapsed": elapsed,
                "lines_output": progress_line_count,
                "last_lines": output_lines[-5:] if output_lines else []
            }
        
        # 1. Check if process is still alive
        alive = True
        try:
            os.kill(pid, 0)
        except OSError:
            alive = False
        
        # 2. Read log file (incrementally)
        if os.path.exists(log_path):
            current_size = os.path.getsize(log_path)
            if current_size > last_size:
                with open(log_path, 'r') as f:
                    f.seek(last_size)
                    new_data = f.read()
                    last_size = current_size
                
                # Extract progress markers
                for line in new_data.split('\n'):
                    line_stripped = line.strip()
                    if line_stripped:
                        output_lines.append(line_stripped)
                    
                    # Count progress lines
                    if 'PROGRESS:' in line_stripped:
                        progress_line_count += 1
                        # Extract the actual progress value
                        match = re.search(r'PROGRESS:\s*(\d+)/(\d+)', line_stripped)
                        if match:
                            current = int(match.group(1))
                            total = int(match.group(2))
                            pct = (current / total) * 100
                            print(f"[{elapsed:6.1f}s] Progress: {current}/{total} ({pct:5.1f}%) | "
                                  f"Log size: {current_size/1024:.1f} KB")
                    
                    # Check for "DONE:" marker
                    if line_stripped.startswith('DONE:'):
                        done_time = line_stripped.replace('DONE:', '').strip()
                        print(f"[{elapsed:6.1f}s] DONE marker found! Execution time: {done_time}")
        
        # 3. Exit condition: process finished
        if not alive:
            # Get return code
            try:
                # Wait with WNOHANG equivalent
                ret = subprocess.run(
                    ['wait', str(pid)],
                    shell=True,
                    capture_output=True,
                    timeout=2
                )
                exit_code = ret.returncode
            except Exception:
                # Try to get exit code from process
                proc = subprocess.run(
                    f'ps -p {pid} -o state 2>/dev/null | tail -1',
                    shell=True, capture_output=True, text=True
                )
                exit_code = -1  # unknown
            
            print(f"[{elapsed:6.1f}s] Process exited (PID {pid})")
            
            # Read remaining log content
            if os.path.exists(log_path):
                with open(log_path, 'r') as f:
                    remaining = f.read()
                for line in remaining.split('\n'):
                    ls = line.strip()
                    if ls:
                        output_lines.append(ls)
                        if 'DONE:' in ls:
                            print(f"[poll_log] Final log confirms completion: {ls}")
            
            return {
                "status": "completed",
                "exit_code": 0 if 'DONE:' in '\n'.join(output_lines[-10:]) else exit_code,
                "elapsed": elapsed,
                "lines_output": len(output_lines),
                "total_progress_markers": progress_line_count,
                "last_lines": output_lines[-5:] if output_lines else []
            }
        
        time.sleep(poll_interval)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Poll a Stata batch log file for progress and done markers.'
    )
    parser.add_argument('--log', '-l', default='/tmp/stata-bg-test/longjob.log',
                        help='Path to Stata log file')
    parser.add_argument('--pid', '-p', type=int, required=True,
                        help='Stata process PID')
    parser.add_argument('--interval', '-i', type=float, default=1.0,
                        help='Poll interval in seconds')
    parser.add_argument('--timeout', '-t', type=float, default=120.0,
                        help='Timeout in seconds')
    
    args = parser.parse_args()
    
    result = poll_log(args.log, args.pid, args.interval, args.timeout)
    
    print("\n" + "=" * 60)
    print("RESULT:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    
    sys.exit(0 if result['status'] == 'completed' and result.get('exit_code') == 0 else 1)
