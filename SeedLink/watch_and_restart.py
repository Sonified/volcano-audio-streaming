#!/usr/bin/env python3
"""
Auto-restart script for live_audifier.py
Watches for file changes and automatically restarts the service
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class RestartHandler(FileSystemEventHandler):
    def __init__(self, script_path, restart_callback):
        self.script_path = Path(script_path)
        self.restart_callback = restart_callback
        self.last_modified = self.script_path.stat().st_mtime if self.script_path.exists() else 0
        
    def on_modified(self, event):
        if event.src_path == str(self.script_path):
            # Debounce: ignore rapid successive modifications
            current_time = time.time()
            if current_time - self.last_modified > 0.5:  # 500ms debounce
                self.last_modified = current_time
                print(f"\n🔄 Detected change in {self.script_path.name} - restarting...")
                self.restart_callback()

def kill_audifier_process():
    """Kill any running live_audifier.py processes"""
    try:
        subprocess.run(['pkill', '-9', '-f', 'live_audifier.py'], 
                      check=False, capture_output=True)
        time.sleep(0.5)  # Give it time to die
    except Exception as e:
        print(f"Warning: Could not kill existing process: {e}")

def start_audifier_process():
    """Start live_audifier.py using conda"""
    script_dir = Path(__file__).parent
    script_path = script_dir / "live_audifier.py"
    
    # Use conda run if available, otherwise use system python
    try:
        # Check if conda is available
        result = subprocess.run(['conda', '--version'], 
                              capture_output=True, timeout=2)
        if result.returncode == 0:
            # Use conda run
            cmd = ['conda', 'run', '-n', 'plotbot_anaconda', 
                   'python', str(script_path)]
        else:
            # Fall back to system python
            cmd = ['python3', str(script_path)]
    except:
        # Fall back to system python
        cmd = ['python3', str(script_path)]
    
    # Filter out conda libmamba warnings
    log_file = '/tmp/seedlink_audifier.log'
    with open(log_file, 'w') as log:
        process = subprocess.Popen(
            cmd,
            cwd=str(script_dir),
            stdout=log,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid if hasattr(os, 'setsid') else None
        )
    
    return process

class AudifierManager:
    def __init__(self):
        self.script_path = Path(__file__).parent / "live_audifier.py"
        self.process = None
        self.running = True
        
    def restart(self, is_initial=False):
        """Restart the audifier process - matches launch.sh output format"""
        if not is_initial:
            print("\n" + "="*32)
        
        print("🌋 Starting SeedLink Live Audifier...")
        print("================================")
        
        # Kill any existing processes
        print("🧹 Cleaning up existing processes...")
        if self.process:
            try:
                # Try graceful shutdown first
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                time.sleep(0.5)
            except:
                pass
            
            # Force kill if still running
            if self.process.poll() is None:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except:
                    pass
        
        # Kill any stray processes
        kill_audifier_process()
        time.sleep(1)
        
        # Get script directory
        script_dir = Path(__file__).parent
        
        # Clear old log
        log_file = '/tmp/seedlink_audifier.log'
        open(log_file, 'w').close()
        
        # Start SeedLink Audifier
        print("🔊 Starting SeedLink Audifier on localhost:8888...")
        
        # Start process with same command as launch.sh
        script_path = script_dir / "live_audifier.py"
        cmd = ['conda', 'run', '-n', 'plotbot_anaconda', 'python', str(script_path)]
        
        # Use grep to filter conda libmamba warnings (like launch.sh does)
        # Note: subprocess can't easily replicate grep filtering, so we'll do it differently
        # We'll use the log file directly
        with open(log_file, 'w') as log:
            process = subprocess.Popen(
                cmd,
                cwd=str(script_dir),
                stdout=log,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
        
        self.process = process
        
        # Wait for audifier to load (ObsPy takes time)
        print("   Waiting for backend to load dependencies...")
        max_wait = 15
        wait_count = 0
        
        while wait_count < max_wait:
            try:
                result = subprocess.run(
                    ['lsof', '-i', ':8888'],
                    capture_output=True,
                    timeout=1
                )
                if result.returncode == 0 and 'LISTEN' in result.stdout.decode():
                    break
            except:
                pass
            time.sleep(1)
            wait_count += 1
        
        print("")
        print("================================")
        print("🔍 Checking Service Status...")
        print("================================")
        
        # Check SeedLink Audifier
        audifier_running = False
        try:
            result = subprocess.run(
                ['lsof', '-i', ':8888'],
                capture_output=True,
                timeout=1
            )
            if result.returncode == 0 and 'LISTEN' in result.stdout.decode():
                print("✅ SeedLink Audifier:  http://localhost:8888 (RUNNING)")
                audifier_running = True
        except:
            pass
        
        if not audifier_running:
            print("❌ SeedLink Audifier:  FAILED TO START")
            print("")
            print("📋 Audifier Logs (last 30 lines):")
            print("-----------------------------------")
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    for line in lines[-30:]:
                        print(line.rstrip())
            except:
                print("(No log file found)")
            print("-----------------------------------")
            print("")
        
        print("")
        print("================================")
        
        if audifier_running:
            print("✅ Service Running Successfully!")
            print("")
            print("📡 Dashboard: http://localhost:8888")
            print("")
            print("View Live Logs:")
            print("   tail -f /tmp/seedlink_audifier.log")
            print("")
            print("To stop:")
            print("   • Click 'Stop Backend' button on dashboard")
            print("   • Or run: pkill -f 'live_audifier.py'")
            print("")
            print("✅ Ready to monitor seismic data!")
        else:
            print("⚠️  Service failed to start. Check logs above.")
            print("")
            print("📋 Troubleshooting:")
            print("   • Check conda environment: conda env list")
            print("   • Install dependencies: pip install -r requirements.txt")
            print("   • Full logs: tail -f /tmp/seedlink_audifier.log")
        
        if not is_initial:
            print("")
            print("👀 Continuing to watch for file changes...")
            print("")
    
    def run(self):
        """Start watching and managing the service"""
        if not self.script_path.exists():
            print(f"❌ Error: {self.script_path} not found!")
            sys.exit(1)
        
        # Initial start (with full launch.sh output)
        self.restart(is_initial=True)
        
        # Add note about auto-restart
        print("")
        print("🔄 Auto-restart mode: Editing live_audifier.py will automatically restart the service")
        print("   Press Ctrl+C to stop")
        print("")
        
        # Setup file watcher
        event_handler = RestartHandler(self.script_path, lambda: self.restart(is_initial=False))
        observer = Observer()
        observer.schedule(event_handler, path=str(self.script_path.parent), recursive=False)
        observer.start()
        
        try:
            # Monitor process health
            while self.running:
                time.sleep(1)
                if self.process and self.process.poll() is not None:
                    print("\n⚠️  Process died unexpectedly!")
                    print("   Restarting...")
                    self.restart(is_initial=False)
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping watcher...")
            observer.stop()
            
            # Kill process
            if self.process:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    print("   Waiting for process to exit...")
                    time.sleep(2)
                    if self.process.poll() is None:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except:
                    pass
            
            kill_audifier_process()
            print("✅ Stopped")
        
        observer.join()

if __name__ == "__main__":
    # Check if watchdog is installed
    try:
        import watchdog
    except ImportError:
        print("❌ Error: 'watchdog' package not installed")
        print("   Install with: pip install watchdog")
        sys.exit(1)
    
    manager = AudifierManager()
    manager.run()

