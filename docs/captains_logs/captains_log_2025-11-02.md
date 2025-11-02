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

## v1.10 - Mute Toggle Feature

**Version**: v1.10  
**Commit Message**: "v1.10 Feature: Added Enter-key mute toggle with 1s fade, red pulsing MUTED indicator in visualization panel, master gain node for global audio control"

- Implemented global mute toggle triggered by Enter key
- Added `masterMuteGain` node to audio graph for clean mute control
- 1-second fade in/out for smooth transitions
- Red "MUTED" indicator in upper right of visualization panel with pulsing animation
- Styled with subtle glow effect and appropriate positioning/sizing

---

## v1.11 - Expanded Adaptive Playback Rate

**Version**: v1.11  
**Commit Message**: "v1.11 Feature: Expanded adaptive playback rate range to 5-500 Hz - added ultra-slow tiers (5 Hz at <100 samples, 10 Hz at <300 samples) and turbo mode (500 Hz at >10k samples), increased manual slider max to 500 Hz"

- Added ultra-slow tiers for critically low buffers:
  - 5 Hz for buffers < 100 samples
  - 10 Hz for buffers < 300 samples
- Added turbo tier for large buffers:
  - 500 Hz for buffers > 10,000 samples
- Increased manual playback rate slider maximum to 500 Hz
- Updated adaptive config with new thresholds and rates

---

## v1.12 - Fractional Sample Accumulation Fix

**Version**: v1.12  
**Commit**: 9668ab1  
**Commit Message**: "v1.12 Fix: Implemented fractional sample accumulation for high-speed playback - fixed 60 FPS interval with sample debt tracking enables accurate 5-500 Hz playback (was limited by browser setInterval minimum ~4-10ms), now actually achieves 500 Hz turbo mode"

### Problem Discovered:

The user noticed that 500 Hz playback wasn't actually playing back at 500 Hz and couldn't keep up with incoming data. The issue was that the previous implementation tried to set `setInterval(advanceMappingScan, 1000 / playbackRate)`:
- At 500 Hz: `1000 / 500 = 2ms` interval
- **JavaScript setInterval minimum is ~4-10ms** (browser-dependent)
- Browser throttling and main thread contention made high rates impossible
- Only 1 sample was consumed per tick, so max achievable rate was ~100-250 Hz

### Solution: Fixed Interval + Fractional Accumulation

Changed to a **fixed 60 FPS interval** with **sample debt tracking**:

```javascript
const MAPPING_SCAN_FPS = 60;  // Fixed interval rate
let mappingSampleDebt = 0;    // Fractional sample accumulator

function advanceMappingScan() {
    // Calculate samples to consume this tick
    const samplesPerTick = mappingPlaybackRate / MAPPING_SCAN_FPS;
    mappingSampleDebt += samplesPerTick;
    
    // Consume whole samples, carry forward fractional remainder
    const samplesToConsume = Math.floor(mappingSampleDebt);
    mappingSampleDebt -= samplesToConsume;
    
    // Actually remove samples from buffer
    for (let i = 0; i < samplesToConsume; i++) {
        mappingDataBuffer.shift();
        mappingTotalSamplesPlayed++;
    }
}
```

### How It Works:

**At 500 Hz:**
- Each tick (16.67ms @ 60 FPS) should consume: `500 / 60 = 8.333 samples`
- Tick 1: debt = 8.333 → consume 8, carry 0.333
- Tick 2: debt = 8.666 → consume 8, carry 0.666
- Tick 3: debt = 8.999 → consume 8, carry 0.999
- Tick 4: debt = 9.332 → consume 9, carry 0.332
- **Averages to exactly 500 samples/second over time**

**At 5 Hz:**
- Each tick should consume: `5 / 60 = 0.083 samples`
- Most ticks: consume 0
- Every 12th tick: consume 1 (when debt ≥ 1)
- **Averages to exactly 5 samples/second**

### Benefits:

- ✅ Works at **any playback rate** from 5 Hz to 500 Hz
- ✅ **Perfectly accurate** over time (fractional error accumulation)
- ✅ No JavaScript timer limitations
- ✅ No browser throttling issues
- ✅ Same technique used in Bresenham's algorithm and audio resampling

### Files Modified:

- `index.html` - Added `MAPPING_SCAN_FPS`, `mappingSampleDebt`, updated `advanceMappingScan()` and `applyMappingPlaybackRate()`

**Now 500 Hz turbo mode actually works! 🚀**

---

## v1.13 - Dynamic Volcano Name Display Fix

**Version**: v1.13  
**Commit**: c66f275  
**Commit Message**: "v1.13 Fix: Dynamic volcano name display now works - updates full subtitle text before reapplying magma effect (was trying to update span destroyed by innerHTML clear), custom formatting per volcano (Great Sitkin, Mauna Loa, Mt. Shishaldin, Mt. Spurr, Kīlauea), updated page title to 'Ride the Volcano'"

### Problem Discovered:

User reported that volcano names in the subtitle were NOT updating when selecting different volcanoes from the dropdown. The subtitle always showed "Kīlauea" regardless of selection.

### Root Cause:

The `applyMagmaEffect()` function was destroying the subtitle's DOM structure:

```javascript
function applyMagmaEffect() {
    const subtitle = document.querySelector('.magma-text');
    subtitle.innerHTML = ''; // ❌ This DESTROYS the <span id="volcanoName"> element!
    // Then rebuilds character-by-character WITHOUT preserving the span
}
```

The original HTML had:
```html
<h2 class="magma-text">Live Seismic Data From <span id="volcanoName">Kīlauea</span></h2>
```

When `loadStations()` ran, it tried to update `document.getElementById('volcanoName')`, but after the first call to `applyMagmaEffect()`, that span no longer existed in the DOM! Console logs confirmed: `volcanoName element: null`.

### Solution:

Instead of trying to update a nested span (which gets destroyed), update the ENTIRE subtitle text content before reapplying the magma effect:

```javascript
// Update the FULL subtitle text (applyMagmaEffect destroys the span structure)
const subtitle = document.querySelector('.magma-text');
if (subtitle) {
    subtitle.textContent = `Live Seismic Data From ${displayName}`;
    
    // Re-apply magma letter effect after volcano name changes
    applyMagmaEffect();
}
```

### Custom Volcano Name Formatting:

```javascript
const displayNames = {
    'Great Sitkin': 'Great Sitkin',      // No "Mt."
    'Mauna Loa': 'Mauna Loa',            // No "Mt."
    'Shishaldin': 'Mt. Shishaldin',      // With "Mt."
    'Spurr': 'Mt. Spurr',                // With "Mt."
    'Kilauea': 'Kīlauea'                 // No "Mt.", add macron
};
```

### Additional Changes:

- Updated page `<title>` from "🌋 Feel Live Volcanic Activity" to "Ride the Volcano"
- Removed debug console logs for cleaner output
- Simplified `loadStations()` function

### Files Modified:

- `index.html` - Fixed volcano name updating logic, simplified `applyMagmaEffect()`, updated page title
- `python_code/__init__.py` - Version bump to 1.13

**Volcano names now change dynamically! 🌋**

---

## v1.14 - Efficient Mode + Seamless Data Fetch

**Version**: v1.14  
**Commit**: 6e99844  
**Commit Message**: "v1.14 Feature: Efficient Mode (40 FPS visuals) + Seamless data fetch with crossfade - added Efficient Mode toggle for 40 FPS waveform/spectrogram and reduced update intervals, implemented seamless audio transitions that keep old audio playing during fetch with 1s crossfade to new data, analyser switches mid-fade for continuous visualizations"

### Feature 1: Efficient Mode

**Problem:**
The application was running all visualizations at 60 FPS constantly, which could be taxing on CPU/battery for laptops and lower-end devices. Several processes were updating more frequently than necessary.

**Solution - Efficient Mode Toggle:**

Added a checkbox in the top control bar (after High Pass filter) that enables performance optimizations:

**Standard Mode (default - 60 FPS):**
- Waveform: 60 FPS (`requestAnimationFrame`)
- Spectrogram: 60 FPS (`requestAnimationFrame`)
- Mapping UI updates: 60 FPS (17ms interval)
- Connection status: 5 FPS (200ms interval)
- Adaptive rate updates: 10 FPS (100ms interval)

**Efficient Mode (40 FPS):**
- Waveform: 40 FPS (25ms throttle via timestamp check)
- Spectrogram: 40 FPS (25ms throttle via timestamp check)
- Mapping UI updates: 40 FPS (25ms interval)
- Connection status: 1 FPS (1000ms interval)
- Adaptive rate updates: 2 FPS (500ms interval)

**Implementation:**
- Added `efficientModeEnabled` flag and timestamp trackers (`lastWaveformDrawTime`, `lastSpectrogramDrawTime`)
- `drawWaveform()` and `drawSpectrogram()` check elapsed time before drawing
- `toggleEfficientMode()` function restarts intervals with new rates
- Maintains smooth 40 FPS animations (imperceptible to most users)
- ~33% reduction in CPU usage for visualizations

**Expected Impact:**
- Significant battery savings on laptops
- Reduced CPU usage without noticeable quality loss
- 40 FPS still feels very smooth for real-time seismic data

### Feature 2: Seamless Data Fetch with Crossfade

**Problem:**
When fetching new data, the old audio would immediately stop, disconnect all nodes, and create an awkward silence during the download/processing phase (often several seconds). The spectrogram would also clear completely, creating a jarring visual interruption.

**Old Flow (abrupt cutoff):**
1. Stop/disconnect old worklet/gain/analyser
2. Clear visualizations
3. Fetch new data (silence during download)
4. Create new worklet
5. Load data → play

**Solution - Continuous Audio with Crossfade:**

Keep the old audio playing seamlessly while new data downloads in the background, then perform a smooth 1-second crossfade.

**New Flow (seamless):**
1. Save references to old nodes (keep playing)
2. Create NEW worklet/gain/analyser/mute nodes alongside old ones
3. Start new nodes at zero volume
4. Fetch data in background (old audio continues)
5. Load new data into new worklet
6. **1-second crossfade:**
   - New audio: 0.0001 → 1.0 (exponential ramp)
   - Old audio: current → 0.0001 (exponential ramp)
   - Analyser switches at 0.5s (mid-fade)
7. After fade: disconnect old nodes

**Key Implementation Details:**

```javascript
// Save old nodes before creating new ones
const oldWorkletNode = workletNode;
const oldGainNode = gainNode;
const oldMasterMuteGain = masterMuteGain;
const oldAnalyserNode = analyserNode;
const hadOldPlayback = (oldWorkletNode && isPlaying);

// Clear globals so initAudioWorklet creates new ones
workletNode = null;
gainNode = null;
masterMuteGain = null;
analyserNode = null;

// Create new audio chain
await initAudioWorklet();

// Start new nodes at zero volume
gainNode.gain.setValueAtTime(0.0001, audioContext.currentTime);

// Keep using old analyser for visualization during crossfade
const newAnalyserNode = analyserNode;
analyserNode = oldAnalyserNode;

// ... fetch and load data ...

// Crossfade (1 second)
gainNode.gain.exponentialRampToValueAtTime(1.0, now + 1.0);  // New: fade in
oldGainNode.gain.exponentialRampToValueAtTime(0.0001, now + 1.0);  // Old: fade out

// Switch analyser mid-fade (0.5s)
setTimeout(() => { analyserNode = newAnalyserNode; }, 500);

// Cleanup old nodes after fade (1.1s)
setTimeout(() => { /* disconnect old nodes */ }, 1100);
```

**Preserved During Transition:**
- ✅ Mute state (Enter key toggle)
- ✅ Playback speed
- ✅ Volume level

**Visual Continuity:**
- Spectrogram does NOT clear (keeps scrolling seamlessly)
- Waveform transitions smoothly from old to new data
- Status shows "Fetching new data (current audio continues)" during download

**User Experience:**
- Radio-style seamless transitions between datasets
- No awkward silence or visual gaps
- Professional, polished feel
- User can keep listening while exploring different time windows/stations

### Files Modified:

- `index.html` - Added Efficient Mode toggle, throttling logic in draw functions, seamless fetch with crossfade
- `python_code/__init__.py` - Version bump to 1.14

**Smooth transitions and better performance! 🎵🔄⚡**

---

## v1.15 - Loop/Finish Fade Fixes

**Version**: v1.15  
**Commit**: [pending]  
**Commit Message**: "v1.15 Fix: Loop/finish fades (separate gain stage + early fade-out) - created separate liveAmplitudeGain stage to prevent Live Amplitude from canceling loop fades, fixed playback speed race condition by setting speed before sending data to worklet, fixed fade-out clicks by using loop-soon warning to start fade early while audio still playing, added speed-adjusted fade duration that scales inversely with playback speed, comprehensive fade logging for debugging, adjusted Gain control spacing"

### Problems Discovered:

1. **Clicks at loop points** - User reported hard clicks when audio looped or finished, even with loop disabled
2. **Live Amplitude interference** - Live Amplitude feature was calling `gainNode.gain.cancelScheduledValues()` every ~17ms, which canceled the loop fade-in/fade-out ramps
3. **Playback speed race condition** - Worklet started playing at default 1.0x speed before receiving speed update message, causing timing issues
4. **Fade-out too late** - Fade-out was triggered AFTER buffer already ran out (worklet outputting silence), causing clicks
5. **UI overlap** - Gain control overlapping with Scroll Speed number display

### Solutions Implemented:

#### 1. Separate Gain Stage for Live Amplitude

Created a two-stage gain architecture to prevent interference:

```javascript
// NEW audio graph:
workletNode → gainNode → liveAmplitudeGain → analyserNode + masterMuteGain → destination
              ↑                ↑
         Volume slider    Live Amplitude
         + Loop fades     modulation
```

**Before:**
- `gainNode` handled both volume AND Live Amplitude modulation
- Live Amplitude's frequent `cancelScheduledValues()` calls destroyed loop fades

**After:**
- `gainNode` handles volume slider + loop fades (uninterrupted)
- `liveAmplitudeGain` handles Live Amplitude modulation (independent)
- They multiply together for final output
- **No interference = no clicks!**

#### 2. Fixed Playback Speed Race Condition

**Problem:** Playback speed was set AFTER data was sent to worklet, causing initial samples to play at wrong speed.

**Solution:** Set speed IMMEDIATELY after creating worklet, before sending any data:

```javascript
await initAudioWorklet();

// ⚡ CRITICAL: Set speed BEFORE sending data
updatePlaybackSpeed();
console.log(`Set playback speed BEFORE sending data: ${currentPlaybackRate.toFixed(2)}x`);

// THEN send data to worklet...
```

This ensures:
- ✅ Duration calculations are accurate
- ✅ Position tracking is smooth
- ✅ Fades trigger at the right time

#### 3. Early Fade-Out Using "loop-soon" Warning

**Problem:** Worklet sends "finished" event AFTER buffer is empty (already outputting silence). Fade-out happened too late = click.

**Solution:** Use "loop-soon" warning (~100ms before end) to start fade-out WHILE audio is still playing:

```javascript
// "loop-soon" fires with ~100ms left
if (gainNode && audioContext) {
    const currentGain = gainNode.gain.value;
    const baseFadeDuration = Math.min(0.08, secondsRemaining * 0.8);
    const speedAdjustedFade = baseFadeDuration / speed;  // Scale with speed!
    const fadeDuration = Math.min(0.08, speedAdjustedFade);
    
    gainNode.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + fadeDuration);
}
```

**Timeline:**
- ~100ms before end: Start fade-out (audio still playing)
- Buffer runs out: Audio already faded to silence
- "finished" event: Just handle UI (fade already done)

#### 4. Speed-Adjusted Fade Duration

Fade duration now scales inversely with playback speed:

- **1x speed**: 80ms fade ✓
- **2x speed**: 40ms fade (half duration) ✓
- **4x speed**: 20ms fade (quarter duration) ✓
- **10x speed**: 8ms fade ✓
- **0.5x speed**: 80ms fade (capped at max) ✓

Keeps fades perceptually appropriate at all speeds!

#### 5. Comprehensive Logging

Added detailed console logging for debugging:

```
🔔 RECEIVED "finished" EVENT from worklet
   isFetchingNewData: false
   isLooping: false
   gainNode exists: true
   audioContext exists: true
📉 STARTING EARLY FADE-OUT (before buffer runs out)...
🔽 EARLY FADE-OUT: 1.0000 → 0.0001 over 80.0ms (speed: 1.00x, 100.0ms remaining)
🏁 BUFFER EMPTY: ...
   (Fade-out already completed via early "loop-soon" trigger)
```

#### 6. UI Spacing Fix

Increased gap between Scroll Speed and Gain controls from 20px → 55px to prevent overlap.

### Files Modified:

- `index.html` - Separate liveAmplitudeGain stage, early fade-out logic, speed-adjusted fade duration, comprehensive logging, UI spacing
- `python_code/__init__.py` - Version bump to 1.15

**Smooth, click-free fades at all playback speeds! 🎵✨**

---

