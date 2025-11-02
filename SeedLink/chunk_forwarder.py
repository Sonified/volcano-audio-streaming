"""
Minimal SeedLink chunk forwarder with ON-DEMAND operation using SUBPROCESS
- Starts DORMANT (no SeedLink connection)
- Auto-STARTS on first request (spawns subprocess)
- Auto-SHUTS DOWN after 10 seconds of no requests (KILLS subprocess)
- Zero cost when not in use!
- ACTUALLY KILLABLE (subprocess, not thread)
"""

from flask import Flask, jsonify
from flask_cors import CORS
import subprocess
import json
import time
import os
import signal
import threading

CHUNK_FILE = '/tmp/seedlink_chunk.json'
STATUS_FILE = '/tmp/seedlink_status.json'
SUBPROCESS_SCRIPT = os.path.join(os.path.dirname(__file__), 'seedlink_subprocess.py')

# Create Flask app
app = Flask(__name__)
CORS(app)

# Global state - ON-DEMAND OPERATION
seedlink_process = None
seedlink_active = False
last_request_time = None
last_chunk_id = None

def start_seedlink():
    """Start SeedLink subprocess"""
    global seedlink_process, seedlink_active
    
    if seedlink_active:
        print("[SEEDLINK] Already active, skipping start")
        return
    
    print("[SEEDLINK] 🚀 STARTING subprocess...")
    
    try:
        # Start the subprocess with UNBUFFERED output (-u flag)
        seedlink_process = subprocess.Popen(
            ['python', '-u', SUBPROCESS_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1  # Line buffered
        )
        
        seedlink_active = True
        
        # Start thread to monitor subprocess output
        def monitor_output():
            for line in seedlink_process.stdout:
                print(f"[SUBPROCESS OUTPUT] {line.strip()}")
        
        output_thread = threading.Thread(target=monitor_output, daemon=True)
        output_thread.start()
        
        print(f"[SEEDLINK] ✅ Started successfully (PID: {seedlink_process.pid})")
        
    except Exception as e:
        print(f"[SEEDLINK] ❌ Failed to start: {e}")
        seedlink_active = False

def stop_seedlink():
    """Stop SeedLink subprocess - KILL IT!"""
    global seedlink_process, seedlink_active
    
    if not seedlink_active:
        print("[SEEDLINK] Already stopped, skipping shutdown")
        return
    
    print("[SEEDLINK] 🛑 SHUTTING DOWN (idle timeout)...")
    seedlink_active = False
    
    if seedlink_process:
        print(f"[SEEDLINK] Terminating process (PID: {seedlink_process.pid})...")
        
        try:
            # Try graceful SIGTERM first
            seedlink_process.terminate()
            
            # Wait up to 2 seconds for graceful shutdown
            try:
                seedlink_process.wait(timeout=2.0)
                print("[SEEDLINK] ✓ Process terminated gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if still alive
                print("[SEEDLINK] Process didn't die - FORCE KILLING...")
                seedlink_process.kill()
                seedlink_process.wait()
                print("[SEEDLINK] ✓ Process KILLED")
                
        except Exception as e:
            print(f"[SEEDLINK] Error during shutdown: {e}")
        
        seedlink_process = None
    
    print("[SEEDLINK] ✅ Shut down successfully")

def auto_shutdown_monitor():
    """Background thread that monitors inactivity and triggers shutdown"""
    global last_request_time, seedlink_active
    
    while True:
        time.sleep(1)  # Check every second
        
        if seedlink_active and last_request_time:
            idle_seconds = time.time() - last_request_time
            
            if idle_seconds > 10:  # 10 second timeout for testing
                print(f"[MONITOR] ⏱️ No requests for {idle_seconds:.0f}s - triggering shutdown")
                stop_seedlink()
                last_request_time = None

# Start auto-shutdown monitor
monitor_thread = threading.Thread(target=auto_shutdown_monitor, daemon=True)
monitor_thread.start()

@app.route('/api/get_chunk_id')
def get_chunk_id():
    """Lightweight endpoint - just return the chunk ID"""
    global last_request_time, last_chunk_id
    
    last_request_time = time.time()
    
    # Start SeedLink if dormant
    if not seedlink_active:
        start_seedlink()
    
    # Read current chunk ID from file
    try:
        if os.path.exists(CHUNK_FILE):
            with open(CHUNK_FILE, 'r') as f:
                data = json.load(f)
                return jsonify({'chunk_id': data.get('chunk_id')})
    except:
        pass
    
    return jsonify({'chunk_id': None})

@app.route('/api/get_chunk')
def get_chunk():
    """Full chunk endpoint - return all data"""
    global last_request_time, last_chunk_id
    
    last_request_time = time.time()
    
    # Start SeedLink if dormant
    if not seedlink_active:
        start_seedlink()
    
    # Read chunk from file
    try:
        if os.path.exists(CHUNK_FILE):
            with open(CHUNK_FILE, 'r') as f:
                data = json.load(f)
                last_chunk_id = data.get('chunk_id')
                return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'No chunk available'}), 404

@app.route('/api/seedlink_status')
def get_seedlink_status():
    """Return current SeedLink status"""
    global last_request_time
    
    status_data = {
        'active': seedlink_active,
        'process_pid': seedlink_process.pid if seedlink_process else None,
        'idle_seconds': time.time() - last_request_time if last_request_time else None
    }
    
    # Try to read subprocess status
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r') as f:
                subprocess_status = json.load(f)
                status_data.update(subprocess_status)
    except:
        pass
    
    return jsonify(status_data)

if __name__ == '__main__':
    print("=" * 60)
    print("🌋 VOLCANO SEEDLINK CHUNK FORWARDER (SUBPROCESS MODE)")
    print("=" * 60)
    print("Flask server: http://localhost:8889")
    print("Endpoints:")
    print("  - GET /api/get_chunk_id    (lightweight ID check)")
    print("  - GET /api/get_chunk       (full chunk data)")
    print("  - GET /api/seedlink_status (connection info)")
    print("")
    print("SeedLink: ON-DEMAND (auto-start/stop)")
    print("  - Starts on first request")
    print("  - Shuts down after 10s idle")
    print("  - KILLABLE subprocess (no zombie threads!)")
    print("  - Detailed trace logging enabled")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=8889, debug=False)
