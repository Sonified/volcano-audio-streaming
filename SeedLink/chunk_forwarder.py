"""
Minimal SeedLink chunk forwarder
ONLY receives chunks from IRIS and forwards them via API
NO audio processing, NO filtering, NO normalization
"""

import numpy as np
from obspy.clients.seedlink import EasySeedLinkClient
from flask import Flask, jsonify
from flask_cors import CORS
import threading

class ChunkForwarder(EasySeedLinkClient):
    def __init__(self):
        super().__init__('rtserve.iris.washington.edu:18000')
        
        # Accumulate chunks until we have a full packet (SeedLink may send multiple small chunks)
        self.accumulated_chunk = []  # Accumulate samples across multiple on_data calls
        self.current_chunk_id = 0
        self.latest_chunk = []  # Final chunk to send to frontend (when accumulation is complete)
        self.chunk_id = 0
        self.sample_rate = 100
        self.last_chunk_time = None  # Track when we last received data
        self.chunk_timeout = 2.0  # If >2 second gap, consider chunk complete (wait for burst to finish)
        
        # Connection info
        self.network = ''
        self.station = ''
        self.channel = ''
        self.connected = False
        self.connection_established = False
        
        print("[CHUNK FORWARDER] Initialized")
    
    def on_connect(self):
        """Called when connection to SeedLink server is established"""
        self.connection_established = True
        print("[CHUNK FORWARDER] ✓ Connected to SeedLink server")
    
    def on_error(self, error):
        """Called when an error occurs"""
        print(f"[CHUNK FORWARDER ERROR] {error}")
    
    def on_data(self, trace):
        """Called when new data arrives from IRIS - ACCUMULATE all traces!
        SeedLink may send multiple small traces that need to be combined into one chunk"""
        import time
        current_time = time.time()
        
        # Extract raw samples as-is (convert from int32 to float for JSON compatibility)
        # trace.data is the COMPLETE trace from SeedLink - we accumulate ALL of them
        samples = trace.data.astype(np.float32).tolist()
        
        # Update connection info
        self.network = trace.stats.network
        self.station = trace.stats.station
        self.channel = trace.stats.channel
        self.sample_rate = int(trace.stats.sampling_rate)
        self.connected = True
        
        # Check if this is a continuation of the current chunk or a new one
        if self.last_chunk_time is not None and (current_time - self.last_chunk_time) > self.chunk_timeout:
            # Gap > 1 second means new chunk - finalize previous accumulation
            if len(self.accumulated_chunk) > 0:
                self.latest_chunk = self.accumulated_chunk.copy()
                self.chunk_id += 1
                self.current_chunk_id += 1  # Increment ONLY when finalizing
                print(f"[CHUNK COMPLETE {self.chunk_id:04d}] Finalized accumulated chunk: {len(self.latest_chunk)} total samples")
                self.accumulated_chunk = []
        
        # Add samples to accumulation buffer
        self.accumulated_chunk.extend(samples)
        self.last_chunk_time = current_time
        
        # Debug: Log each trace received
        print(f"[TRACE] Received {len(samples)} samples | Accumulated: {len(self.accumulated_chunk)} total | "
              f"Trace time: {trace.stats.starttime} to {trace.stats.endtime} | "
              f"Duration: {len(samples) / trace.stats.sampling_rate:.2f}s")
    

# Create Flask app
app = Flask(__name__)
CORS(app)

# Global forwarder instance (will be set in __main__)
forwarder = None

@app.route('/api/get_chunk')
def get_chunk():
    """Get the latest chunk from IRIS (raw, unprocessed)"""
    if forwarder:
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
    if forwarder:
        return jsonify({
            'connected': forwarder.connected,
            'network': forwarder.network,
            'station': forwarder.station,
            'channel': forwarder.channel,
            'chunks_received': forwarder.chunk_id,
            'sample_rate': forwarder.sample_rate
        })
    return jsonify({
        'connected': False,
        'network': '',
        'station': '',
        'channel': '',
        'chunks_received': 0,
        'sample_rate': 100
    })

def run_flask():
    """Run Flask server"""
    app.run(host='0.0.0.0', port=8889, debug=False, use_reloader=False)

if __name__ == '__main__':
    print("=" * 50)
    print("🌋 SeedLink Chunk Forwarder")
    print("=" * 50)
    
    # Create forwarder (autoconnect=True by default, so connection starts immediately)
    # Note: forwarder is already declared as global at module level
    forwarder = ChunkForwarder()
    
    # Wait a moment for connection to establish
    print("[SEEDLINK] Waiting for connection to establish...")
    import time
    time.sleep(2)  # Give SeedLink time to connect
    
    # Check if connection was established
    if forwarder.connection_established:
        print("[SEEDLINK] ✓ Connection established")
    else:
        print("[SEEDLINK] ⚠ Connection not yet established, proceeding anyway...")
    
    # Start Flask in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"[FLASK] Started on http://localhost:8889")
    
    # Connect to station (try same as live_audifier.py first to test)
    print("[SEEDLINK] Selecting stream HV.NPOC.HHZ (same as live_audifier.py)...")
    try:
        forwarder.select_stream('HV', 'NPOC', 'HHZ')
        print("[SEEDLINK] ✓ Stream selected successfully")
    except Exception as e:
        print(f"[SEEDLINK ERROR] Failed to select stream: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
    
    print("[SEEDLINK] Starting data stream...")
    print("=" * 50)
    
    # Run SeedLink client (blocking)
    try:
        forwarder.run()
    except KeyboardInterrupt:
        print("\n[SEEDLINK] Stopped by user")
    except Exception as e:
        print(f"[SEEDLINK ERROR] Fatal error: {e}")
        import traceback
        traceback.print_exc()

