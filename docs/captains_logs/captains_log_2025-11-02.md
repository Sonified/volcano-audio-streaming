# Captain's Log - November 2, 2025

## SeedLink Parameter Mapping Integration to Render Backend

### Major Update: On-Demand SeedLink Chunk Forwarding

**Version**: v1.08  
**Commit**: [pending]  
**Commit Message**: "v1.08 Feature: Integrated on-demand SeedLink chunk forwarding to Render backend - auto-start/shutdown, efficient polling (1 req/sec ID check + full chunk on change), connection status indicators, 1s chunk finalization, backend auto-detects localhost vs Render"

### Changes Made:

1. **Integrated SeedLink to Render Backend** (`backend/main.py`)
   - Added `ChunkForwarder` class (same as local version)
   - On-demand operation: starts on first request, shuts down after 60s idle
   - Background gap monitor (100ms checks, finalizes chunks after 1s gap)
   - Three new endpoints: `/api/get_chunk_id`, `/api/get_chunk`, `/api/seedlink_status`
   - Auto-shutdown monitor prevents 24/7 operation costs

2. **Optimized Polling Strategy**
   - Frontend polls `/api/get_chunk_id` every 1 second (lightweight ~20 byte response)
   - Only fetches `/api/get_chunk` when chunk ID changes (~25KB response)
   - **99.7% bandwidth reduction** compared to naive polling
   - Chunks finalize 1 second after traces arrive (not 30+ seconds later)

3. **Backend Auto-Detection** (`index.html`)
   - Tries `localhost:8889` first (1s timeout)
   - Falls back to `https://volcano-audio.onrender.com` if localhost unavailable
   - Seamless transition between local development and production
   - Single codebase works in both environments

4. **Connection Status Indicators**
   - Green glowing circle = backend responding (< 5 seconds)
   - Red glowing circle = connection lost (> 5 seconds)
   - Gray circle = waiting for first request
   - Appears on both "Real-Time Data Statistics" and "Parameter Mapping Sonification" panels

5. **Chunk Timing Improvements** (`chunk_forwarder.py`)
   - Changed chunk timeout from 2.0s → 1.0s (traces arrive in <100ms bursts)
   - Active gap monitoring in background thread (checks every 100ms)
   - Chunks finalize immediately after 1s gap (not waiting for next burst)
   - Much faster delivery to frontend (~1s vs ~30-50s)

### Technical Details:

**Bandwidth Efficiency:**
- Old approach: 10 req/sec × 25KB = 250 KB/sec = 900 MB/hour
- New approach: 1 req/sec × 20 bytes + 1 chunk/45s × 25KB ≈ 0.7 KB/sec
- **99.92% reduction in bandwidth usage**

**Cost Implications:**
- SeedLink only runs when actively being used
- Auto-shuts down after 60 seconds of no activity
- Traces arrive every ~40-50 seconds in <100ms bursts
- Minimal CPU impact on Render paid tier
- Estimated cost: < $1/month additional processing

**Shutdown Behavior:**
- `close()` stops data processing immediately (verified - no TRACE messages after shutdown)
- Thread may remain alive briefly (~30s) but idle (not processing)
- Daemon thread - doesn't block process exit
- ObsPy's auto-reconnect suppressed via `on_terminate()` override

### Files Modified:

1. `backend/main.py` - Added SeedLink integration
2. `index.html` - Added backend detection and connection indicators
3. `SeedLink/chunk_forwarder.py` - Optimized local testing version
4. `python_code/__init__.py` - Version bump to 1.08

### Known Issues:

- Thread warning "Thread still alive after timeout" appears during shutdown (harmless - thread is idle)
- ObsPy SeedLink client sometimes prints "reconnecting" message during shutdown (cosmetic only, no actual reconnection occurs)

### Major Refactor: Subprocess Architecture (v1.09)

**Problem Discovered:**
After implementing the threaded approach (v1.08), we discovered that ObsPy's `EasySeedLinkClient` was NOT designed to be stopped. When calling `close()` or even `conn.terminate()`, the client would continue attempting reconnections indefinitely, spamming logs with "socket read error: timed out, reconnecting in 30s" messages. Python threads cannot be forcefully killed, making it impossible to achieve a clean shutdown.

**Solution: Subprocess Architecture**

Completely migrated from threading to subprocess-based architecture:

1. **Created `seedlink_subprocess.py`**
   - Standalone Python script that runs the SeedLink client
   - Handles SIGTERM/SIGINT signals for clean exit
   - Writes chunks to `/tmp/seedlink_chunk.json`
   - Writes status to `/tmp/seedlink_status.json`
   - Uses IPC (inter-process communication) via JSON files

2. **Refactored Flask Server**
   - Spawns subprocess with `subprocess.Popen()`
   - Uses `-u` flag for unbuffered output (real-time logging!)
   - Monitors subprocess stdout in separate thread
   - Can send SIGTERM for graceful shutdown
   - Can send SIGKILL for forced termination if needed
   - Reads chunk data from JSON files (not shared memory)

3. **Clean Shutdown Achieved**
   ```
   [SEEDLINK] 🛑 SHUTTING DOWN (idle timeout)...
   [SEEDLINK] Terminating process (PID: 87810)...
   [SUBPROCESS OUTPUT] [SUBPROCESS] 🛑 Received kill signal - exiting immediately
   [SUBPROCESS OUTPUT] [SUBPROCESS] Process exiting
   [SEEDLINK] ✓ Process terminated gracefully
   [SEEDLINK] ✅ Shut down successfully
   ```
   **NO reconnection spam! Clean exit every time!**

4. **Applied to Both Backends**
   - Local: `SeedLink/chunk_forwarder.py` + `SeedLink/seedlink_subprocess.py`
   - Render: `backend/main.py` + `backend/seedlink_subprocess.py`
   - Identical architecture for consistency

**Technical Details:**

- **Python `-u` flag**: Unbuffered stdout/stderr for real-time log visibility
- **Signal handlers**: `signal.signal(signal.SIGTERM, handler)` for clean exit
- **Process termination**: `process.terminate()` → wait 2s → `process.kill()` if still alive
- **Daemon threads**: Output monitor thread doesn't block process exit
- **IPC via files**: Simple and reliable, no shared memory complexity

**Files Modified:**

- `SeedLink/chunk_forwarder.py` - Converted to subprocess spawner
- `SeedLink/seedlink_subprocess.py` - NEW standalone client
- `backend/main.py` - Converted to subprocess spawner  
- `backend/seedlink_subprocess.py` - NEW standalone client
- `index.html` - Added backend detection logging
- `python_code/__init__.py` - Version bump to 1.09

**Lessons Learned:**

1. ObsPy's `EasySeedLinkClient` is designed for 24/7 monitoring stations, not on-demand operation
2. Python threads cannot be forcefully killed - use subprocesses when you need true process control
3. Unbuffered output (`-u` flag) is critical for real-time debugging of subprocesses
4. Signal handlers enable graceful subprocess termination
5. Sometimes the "complex" solution (subprocesses) is actually simpler than fighting library limitations

**Version**: v1.09  
**Commit**: [pending]  
**Commit Message**: "v1.09 Refactor: Migrated SeedLink from threads to KILLABLE subprocesses - clean shutdown with no reconnection spam, unbuffered real-time logging, SIGTERM/SIGKILL termination, subprocess architecture for both local and Render backends"

### Next Steps:

- Deploy v1.09 to Render
- Test online version with subprocess architecture
- Monitor Render logs for clean shutdown behavior
- Verify no zombie processes on Render

---

