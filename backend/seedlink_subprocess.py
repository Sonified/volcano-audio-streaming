"""
Standalone SeedLink subprocess for Render backend - runs independently, can be KILLED
Writes chunks to a JSON file that the Flask server reads
"""

import numpy as np
from obspy.clients.seedlink import EasySeedLinkClient
import json
import time
import signal
import sys

CHUNK_FILE = '/tmp/seedlink_chunk.json'
STATUS_FILE = '/tmp/seedlink_status.json'

class ChunkForwarder(EasySeedLinkClient):
    def __init__(self):
        super().__init__('rtserve.iris.washington.edu:18000')
        self.accumulated_chunk = []
        self.chunk_id = 0
        self.last_trace_time = None
        self.chunk_timeout = 1.0
        self.network = ''
        self.station = ''
        self.channel = ''
        self.sample_rate = 100
        
        # Write initial status
        self._write_status('starting')
        
        print("[SUBPROCESS] SeedLink client initialized")
    
    def _write_status(self, status):
        """Write status to file"""
        try:
            with open(STATUS_FILE, 'w') as f:
                json.dump({
                    'status': status,
                    'network': self.network,
                    'station': self.station,
                    'channel': self.channel,
                    'timestamp': time.time()
                }, f)
        except Exception as e:
            print(f"[SUBPROCESS] Error writing status: {e}")
    
    def _write_chunk(self, gap_time=None):
        """Write chunk to file"""
        if len(self.accumulated_chunk) == 0:
            return
        
        self.chunk_id += 1
        chunk_data = {
            'chunk_id': f"{self.chunk_id:04d}",
            'samples': self.accumulated_chunk,
            'sample_rate': self.sample_rate,
            'network': self.network,
            'station': self.station,
            'channel': self.channel,
            'timestamp': time.time()
        }
        
        try:
            with open(CHUNK_FILE, 'w') as f:
                json.dump(chunk_data, f)
            
            # Detailed completion message like old version
            gap_msg = f" (gap detected: {gap_time:.1f}s)" if gap_time else ""
            print(f"[CHUNK COMPLETE {self.chunk_id:04d}] Finalized accumulated chunk: {len(self.accumulated_chunk)} total samples{gap_msg}")
        except Exception as e:
            print(f"[SUBPROCESS] Error writing chunk: {e}")
        
        self.accumulated_chunk = []
        self.last_trace_time = None
    
    def _monitor_gaps(self):
        """Background thread to check for gaps and finalize chunks"""
        import threading
        def monitor():
            while True:
                time.sleep(0.1)  # Check every 100ms
                if self.last_trace_time and len(self.accumulated_chunk) > 0:
                    gap = time.time() - self.last_trace_time
                    if gap > self.chunk_timeout:
                        self._write_chunk(gap_time=gap)
        
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def on_connect(self):
        self._write_status('connected')
        print("[SUBPROCESS] ✓ Connected to SeedLink server")
    
    def on_data(self, trace):
        samples = trace.data.astype(np.float32).tolist()
        
        self.network = trace.stats.network
        self.station = trace.stats.station
        self.channel = trace.stats.channel
        self.sample_rate = int(trace.stats.sampling_rate)
        
        self.accumulated_chunk.extend(samples)
        self.last_trace_time = time.time()
        
        # Detailed logging like the old version
        print(f"[TRACE] Received {len(samples)} samples | Accumulated: {len(self.accumulated_chunk)} total | "
              f"Trace time: {trace.stats.starttime} to {trace.stats.endtime} | "
              f"Duration: {len(samples) / trace.stats.sampling_rate:.2f}s")

def signal_handler(sig, frame):
    """Handle SIGTERM/SIGINT - clean exit"""
    print("[SUBPROCESS] 🛑 Received kill signal - exiting immediately")
    sys.exit(0)

if __name__ == '__main__':
    # Register signal handlers for clean kill
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    print("[SUBPROCESS] 🚀 Starting SeedLink subprocess...")
    
    forwarder = ChunkForwarder()
    forwarder._monitor_gaps()
    
    try:
        forwarder.select_stream('HV', 'NPOC', 'HHZ')
        print("[SUBPROCESS] ✓ Stream selected: HV.NPOC.HHZ")
    except Exception as e:
        print(f"[SUBPROCESS] Error selecting stream: {e}")
        sys.exit(1)
    
    print("[SUBPROCESS] ✓ Starting data collection...")
    
    try:
        forwarder.run()  # Blocking call
    except Exception as e:
        print(f"[SUBPROCESS] Error: {e}")
    finally:
        print("[SUBPROCESS] Process exiting")

