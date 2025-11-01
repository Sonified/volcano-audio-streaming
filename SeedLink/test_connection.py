"""Test connection to see what's happening"""
from obspy.clients.seedlink import EasySeedLinkClient
import time

class TestClient(EasySeedLinkClient):
    def __init__(self):
        super().__init__('rtserve.iris.washington.edu:18000')
        print("[TEST] Client initialized")
    
    def on_data(self, trace):
        print(f"[TEST] Received data: {trace.stats.network}.{trace.stats.station}.{trace.stats.channel}")
    
    def on_error(self, error):
        print(f"[TEST ERROR] {error}")
    
    def on_connect(self):
        print("[TEST] Connected to server!")

print("=" * 50)
print("Testing AV.SPBG.HHZ connection...")
print("=" * 50)

client = TestClient()
time.sleep(2)  # Give it time to connect

print("[TEST] Selecting stream AV.SPBG.HHZ...")
try:
    client.select_stream('AV', 'SPBG', 'HHZ')
    print("[TEST] Stream selected, starting run()...")
    print("[TEST] If you see 'Received data' messages, connection works!")
    print("[TEST] Press Ctrl+C to stop")
    client.run()
except KeyboardInterrupt:
    print("\n[TEST] Stopped")
except Exception as e:
    print(f"[TEST ERROR] Exception: {e}")
    import traceback
    traceback.print_exc()


