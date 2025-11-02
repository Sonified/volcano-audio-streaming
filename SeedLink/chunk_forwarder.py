"""
Minimal SeedLink chunk forwarder with ON-DEMAND operation
- Starts DORMANT (no SeedLink connection)
- Auto-STARTS on first request
- Auto-SHUTS DOWN after 60 seconds of no requests
- Zero cost when not in use!
"""

import numpy as np
from obspy.clients.seedlink import EasySeedLinkClient
from flask import Flask, jsonify
from flask_cors import CORS
import threading
import time

class ChunkForwarder(EasySeedLinkClient):
    def __init__(self):
        # Pass autoconnect=False to prevent immediate connection
        super().__init__('rtserve.iris.washington.edu:18000')
        self.should_stop = False  # Flag to stop the run loop
        
        # Accumulate chunks until we have a full packet (SeedLink may send multiple small chunks)
        self.accumulated_chunk = []  # Accumulate samples across multiple on_data calls
        self.current_chunk_id = 0
        self.latest_chunk = []  # Final chunk to send to frontend (when accumulation is complete)
        self.chunk_id = 0
        self.sample_rate = 100
        self.last_trace_time = None  # Track when we last received a trace (wall clock time)
        self.chunk_timeout = 1.0  # If >1 second gap, consider chunk complete (traces arrive in bursts < 100ms)
        
        # Start background thread to check for gaps
        import threading
        self.monitor_thread = threading.Thread(target=self._monitor_gaps, daemon=True)
        self.monitor_thread.start()
        
        # Connection info
        self.network = ''
        self.station = ''
        self.channel = ''
        self.connected = False
        self.connection_established = False
        
        print("[CHUNK FORWARDER] Initialized (dormant)")
    
    def on_connect(self):
        """Called when connection to SeedLink server is established"""
        self.connection_established = True
        print("[CHUNK FORWARDER] ✓ Connected to SeedLink server")
    
    def on_error(self, error):
        """Called when an error occurs"""
        print(f"[CHUNK FORWARDER ERROR] {error}")
    
    def _monitor_gaps(self):
        """Background thread that actively monitors for gaps and finalizes chunks"""
        while True:
            time.sleep(0.1)  # Check every 100ms
            
            if self.last_trace_time is not None and len(self.accumulated_chunk) > 0:
                gap = time.time() - self.last_trace_time
                
                if gap > self.chunk_timeout:
                    # Gap detected! Finalize chunk
                    self.latest_chunk = self.accumulated_chunk.copy()
                    self.chunk_id += 1
                    self.current_chunk_id += 1
                    print(f"[CHUNK COMPLETE {self.chunk_id:04d}] Finalized accumulated chunk: {len(self.latest_chunk)} total samples (gap detected: {gap:.1f}s)")
                    self.accumulated_chunk = []
                    self.last_trace_time = None  # Reset
    
    def on_terminate(self):
        """Override to prevent auto-reconnect on shutdown"""
        global shutdown_requested
        if self.should_stop or shutdown_requested:
            print("[SEEDLINK] on_terminate called - stopping (no reconnect)")
            return
        super().on_terminate()
    
    def on_data(self, trace):
        """Called when new data arrives from IRIS - ACCUMULATE all traces!
        SeedLink may send multiple small traces that need to be combined into one chunk"""
        global shutdown_requested
        
        # Check if we should stop
        if self.should_stop or shutdown_requested:
            print("[SEEDLINK] Stop requested during on_data - exiting")
            self.close()
            return
        
        # Extract raw samples as-is (convert from int32 to float for JSON compatibility)
        # trace.data is the COMPLETE trace from SeedLink - we accumulate ALL of them
        samples = trace.data.astype(np.float32).tolist()
        
        # Update connection info
        self.network = trace.stats.network
        self.station = trace.stats.station
        self.channel = trace.stats.channel
        self.sample_rate = int(trace.stats.sampling_rate)
        self.connected = True
        
        # Add samples to accumulation buffer
        self.accumulated_chunk.extend(samples)
        
        # Update timestamp (monitor thread will check for gaps)
        self.last_trace_time = time.time()
        
        # Debug: Log each trace received
        print(f"[TRACE] Received {len(samples)} samples | Accumulated: {len(self.accumulated_chunk)} total | "
              f"Trace time: {trace.stats.starttime} to {trace.stats.endtime} | "
              f"Duration: {len(samples) / trace.stats.sampling_rate:.2f}s")

# Create Flask app
app = Flask(__name__)
CORS(app)

# Global state - ON-DEMAND OPERATION
forwarder = None
seedlink_thread = None
seedlink_active = False
last_request_time = None
shutdown_requested = False

def start_seedlink():
    """Start SeedLink connection in background thread"""
    global forwarder, seedlink_thread, seedlink_active, shutdown_requested
    
    if seedlink_active:
        print("[SEEDLINK] Already active, skipping start")
        return
    
    print("[SEEDLINK] 🚀 STARTING on-demand...")
    
    # Create forwarder
    forwarder = ChunkForwarder()
    forwarder.should_stop = False
    shutdown_requested = False
    
    # Select stream
    try:
        forwarder.select_stream('HV', 'NPOC', 'HHZ')
        print("[SEEDLINK] ✓ Stream selected: HV.NPOC.HHZ")
    except Exception as e:
        print(f"[SEEDLINK ERROR] Failed to select stream: {e}")
        return
    
    # Start SeedLink in background thread
    def run_seedlink():
        global seedlink_active
        seedlink_active = True
        print("[SEEDLINK] ✓ Connection active - receiving data...")
        try:
            # run() blocks until close() is called - don't use a while loop!
            forwarder.run()
        except Exception as e:
            if not shutdown_requested:
                print(f"[SEEDLINK ERROR] Connection error: {e}")
        finally:
            seedlink_active = False
            print("[SEEDLINK] Thread exiting - connection closed")
    
    seedlink_thread = threading.Thread(target=run_seedlink, daemon=True)
    seedlink_thread.start()
    
    print("[SEEDLINK] ✅ Started successfully")

def stop_seedlink():
    """Stop SeedLink connection"""
    global forwarder, seedlink_active, shutdown_requested, seedlink_thread
    
    if not seedlink_active:
        print("[SEEDLINK] Already stopped, skipping shutdown")
        return
    
    print("[SEEDLINK] 🛑 SHUTTING DOWN (idle timeout)...")
    shutdown_requested = True
    seedlink_active = False  # Set this FIRST to stop the thread check
    
    if forwarder:
        # Set stop flag BEFORE calling close
        forwarder.should_stop = True
        
        try:
            # Call close() to stop the SeedLink connection
            forwarder.close()
            print("[SEEDLINK] ✓ Close() called on forwarder")
        except Exception as e:
            print(f"[SEEDLINK] Error during close: {e}")
        forwarder = None
    
    # Give thread a moment to finish
    if seedlink_thread and seedlink_thread.is_alive():
        seedlink_thread.join(timeout=2.0)
        if seedlink_thread.is_alive():
            print("[SEEDLINK] ⚠️ Thread still alive after timeout")
        else:
            print("[SEEDLINK] ✓ Thread terminated")
    
    print("[SEEDLINK] ✅ Shut down successfully")

def auto_shutdown_monitor():
    """Background monitor - shuts down SeedLink after 10s of no requests (for testing)"""
    global last_request_time, seedlink_active
    
    while True:
        time.sleep(2)  # Check every 2 seconds
        
        if seedlink_active:
            if last_request_time is None:
                # SeedLink is active but no requests ever made - this shouldn't happen
                # but if it does, start the timer now
                print("[MONITOR] ⚠️ SeedLink active but no request timestamp - starting idle timer")
                idle_time = 999  # Force shutdown
            else:
                idle_time = time.time() - last_request_time
            
            if idle_time > 10:
                print(f"[MONITOR] ⏱️ No requests for {idle_time:.0f}s - triggering shutdown")
                stop_seedlink()
                last_request_time = None  # Reset

@app.route('/api/get_chunk_id')
def get_chunk_id():
    """Lightweight endpoint - only returns chunk ID (tiny response!)
    Also triggers auto-start if dormant"""
    global last_request_time
    
    # Update last request time (heartbeat)
    last_request_time = time.time()
    
    # Auto-start if dormant
    if not seedlink_active:
        print("[API] First request received - starting SeedLink...")
        start_seedlink()
        # Give it a moment to start
        time.sleep(0.5)
    
    if forwarder:
        return jsonify({
            'chunk_id': forwarder.current_chunk_id if hasattr(forwarder, 'current_chunk_id') else forwarder.chunk_id
        })
    return jsonify({'chunk_id': 0})

@app.route('/api/get_chunk')
def get_chunk():
    """Get the latest chunk from IRIS (raw, unprocessed)
    Also triggers auto-start if dormant
    NOTE: Chunks are NOT cleared after fetching - frontend filters by ID"""
    global last_request_time
    
    # Update last request time (heartbeat)
    last_request_time = time.time()
    
    # Auto-start if dormant
    if not seedlink_active:
        print("[API] First request received - starting SeedLink...")
        start_seedlink()
        # Give it a moment to start
        time.sleep(0.5)
    
    if forwarder:
        # Return latest chunk (frontend will filter by chunk_id to avoid duplicates)
        return jsonify({
            'samples': forwarder.latest_chunk,
            'sample_count': len(forwarder.latest_chunk),
            'sample_rate': forwarder.sample_rate,
            'chunk_id': forwarder.current_chunk_id if hasattr(forwarder, 'current_chunk_id') else forwarder.chunk_id,
            'network': forwarder.network,
            'station': forwarder.station,
            'channel': forwarder.channel,
            'connected': forwarder.connected
        })
    return jsonify({
        'samples': [],
        'sample_count': 0,
        'sample_rate': 100,
        'chunk_id': 0,
        'network': '',
        'station': '',
        'channel': '',
        'connected': False
    })

@app.route('/api/status')
def get_status():
    """Get connection status"""
    global last_request_time
    
    idle_time = None
    if last_request_time:
        idle_time = time.time() - last_request_time
    
    if forwarder:
        return jsonify({
            'connected': forwarder.connected,
            'active': seedlink_active,
            'network': forwarder.network,
            'station': forwarder.station,
            'channel': forwarder.channel,
            'chunks_received': forwarder.chunk_id,
            'sample_rate': forwarder.sample_rate,
            'idle_seconds': idle_time
        })
    return jsonify({
        'connected': False,
        'active': seedlink_active,
        'network': '',
        'station': '',
        'channel': '',
        'chunks_received': 0,
        'sample_rate': 100,
        'idle_seconds': idle_time
    })

def run_flask():
    """Run Flask server"""
    app.run(host='0.0.0.0', port=8889, debug=False, use_reloader=False)

if __name__ == '__main__':
    print("=" * 60)
    print("🌋 SeedLink Chunk Forwarder (ON-DEMAND)")
    print("=" * 60)
    print("🔵 Starting in DORMANT mode")
    print("🔵 Will auto-START on first request")
    print("🔵 Will auto-SHUTDOWN after 10s of no requests (TESTING MODE)")
    print("=" * 60)
    
    # Start auto-shutdown monitor in background
    monitor_thread = threading.Thread(target=auto_shutdown_monitor, daemon=True)
    monitor_thread.start()
    print("[MONITOR] ✓ Auto-shutdown monitor started")
    
    # Start Flask (this will block)
    print(f"[FLASK] Starting on http://localhost:8889")
    print("=" * 60)
    run_flask()
