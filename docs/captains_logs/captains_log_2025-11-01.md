# Captain's Log - November 1, 2025

## Project Duplication for New GitHub Repository

### Major Decision: Repository Duplication

The original volcano audio streaming project has been duplicated to create a new GitHub repository. This allows us to:

1. **Separate Event Focus**: Create a dedicated GitHub page for this specific event
2. **Optimized Development**: Continue building an optimized page specifically for this event (`index.html`)
3. **Clean Slate**: Start fresh with version tracking for this new repository

### Current State

- **Repository**: `https://github.com/Sonified/volcano-audio-streaming` (NEW - separate from `volcano-audio`)
- **Version**: v1.00 (fresh start for new repository)
- **First Push**: ✅ **COMPLETED** - Initial commit pushed
- **Focus**: Optimizing `index.html` for the specific event needs

### First Push Details

**Version**: v1.00  
**Commit**: `e13e9b6`  
**Commit Message**: "v1.00 Initial: Duplicated project for new GitHub repository - optimized event page"  
**Repository**: `https://github.com/Sonified/volcano-audio-streaming`  
**Files**: 564 files, 510,250 insertions  
**Status**: Successfully pushed to main branch

### Next Steps

- Continue optimizing `index.html` for event-specific requirements
- Document version increments going forward
- Build out event-specific features and optimizations

---

## SeedLink Real-Time Smoothing Filter

### Changes Made:

1. **Low-Pass Smoothing Filter at Audio Rate**
   - Added exponential moving average (EMA) filter running at 44.1 kHz
   - Default smoothing time: 50ms (0.05s)
   - Adjustable range: 20ms to 500ms (0.02s to 0.5s)
   - Applied in real-time during audio callback to remove sharp spikes
   - Audio output now uses smoothed version exclusively

2. **Dual Waveform Tracking**
   - Raw interpolated samples (stored for visualization)
   - Smoothed samples (used for audio output and visualization)
   - Both tracked at audio rate and downsampled to 10Hz for display

3. **4-Box Dashboard Layout**
   - Reorganized dashboard into 4 equal-width boxes in a row:
     1. **Original Live Amplitude** (left) - Real-time raw interpolated amplitude indicator
     2. **Smoothed Live Amplitude** - Real-time smoothed amplitude indicator
     3. **Original Waveform** - Raw interpolated waveform drawing
     4. **Smoothed Waveform** - Smoothed waveform drawing with smoothing control slider
   - Side-by-side comparison allows visual verification of smoothing effect

4. **Interactive Smoothing Control**
   - Slider in smoothed waveform box
   - Range: 20ms to 500ms
   - Default: 50ms
   - Updates in real-time via API endpoint `/api/smoothing_time` (POST)

5. **Backend API Enhancements**
   - `/api/waveform_raw_interpolated` - Get raw interpolated waveform data
   - `/api/waveform_smoothed` - Get smoothed waveform data
   - `/api/live_amplitude` - Now returns both `amplitude` (raw) and `amplitude_smoothed`
   - `/api/smoothing_time` (POST) - Set smoothing time constant

### Key Learnings:

- **Exponential Moving Average**: Simple and efficient for real-time smoothing at audio rates
- **Alpha Calculation**: `alpha = dt / tau` where dt = 1/sample_rate, tau = smoothing_time
- **Visual Comparison**: Side-by-side displays make it easy to see smoothing effect
- **Real-Time Updates**: Both live amplitude indicators update at 20 fps for smooth motion

### Technical Details:

- Smoothing filter uses exponential moving average: `y[n] = alpha * x[n] + (1 - alpha) * y[n-1]`
- Filter state persists across audio callbacks for continuous smoothing
- Both raw and smoothed samples stored in separate deques for visualization
- Live amplitude API returns both values simultaneously for efficient dashboard updates

### Version
**v1.01** - Commit: `d55abeb`  
**Commit Message**: "v1.01 Feature: Added real-time smoothing filter to SeedLink dashboard - 4-box layout with raw/smoothed live amplitude and waveform displays, adjustable smoothing (20-500ms)"  
**Status**: Successfully pushed to main branch  
**Changes**: 4 files changed, 319 insertions(+), 69 deletions(-)

---

## SeedLink Chunk Forwarder & Waveform Viewer

### Changes Made:

1. **New Chunk Forwarder Backend** (`chunk_forwarder.py`)
   - Minimal SeedLink client focused solely on receiving and forwarding raw chunks
   - No audio processing, filtering, or normalization on backend
   - Accumulates multiple small traces into complete chunks (waits 2s for burst to complete)
   - Runs on port 8889 (separate from live_audifier on 8888)
   - Launch script: `launch_chunk_forwarder.sh`

2. **Live Waveform Viewer Dashboard** (`dashboard_chunk_viewer.html`)
   - Fixed 8k-sample visualization window showing scrolling waveform
   - 50k-sample internal buffer (bounded sliding window)
   - Red scan line stays at left edge (read position)
   - Data scrolls left as consumed, new chunks fill from right
   - Visual chunk boundaries (orange dashed lines) show where chunks splice

3. **Adaptive Visualization Scaling**
   - Analyzes leftmost 3k samples for min/max
   - Exponential moving average smoothing (~5s time constant)
   - Immediately initializes to actual data range (no slow ramp-up)
   - Auto-centers waveform using 80% of canvas height
   - Shows current range: `[min, max]` raw counts

4. **Playback Rate Control**
   - Interactive slider: 1-200 Hz (default 100 Hz)
   - Dynamically adjusts consumption rate
   - Helps match data arrival rate to prevent buffer overflow
   - Real-time interval restart on rate change

5. **Live Output Meter**
   - Vertical bar showing current value at red line
   - Color gradient: red (low) → yellow (mid) → green (high)
   - Displays normalized value (0.000-1.000)
   - Updates at playback rate (100 Hz default)

6. **Visual Grid System**
   - Gray vertical lines every 500 samples with labels
   - Orange dashed lines at chunk boundaries (dynamic, scroll with data)
   - Empty buffer space shown as grayed area
   - Yellow line at fill boundary

7. **Statistics Dashboard**
   - Chunks Received: Count of complete chunks from server
   - Total Received: Cumulative samples received
   - Samples Remaining: Current buffer fill level
   - Playback Rate: Adjustable slider
   - Time Since Chunk: Seconds since last chunk arrival

8. **Chunk Log Display**
   - Scrollable log showing last 50 chunks
   - Each row shows: chunk ID, sample count, timestamp
   - First 10 and last 10 values for each chunk
   - Newest chunk highlighted
   - Helps verify chunk alignment and continuity

### Major Bug Fixed: Chunk Accumulation

**Problem**: Initial implementation was only receiving ~400 samples per chunk instead of expected ~4000
**Root Cause**: SeedLink sends data in bursts of multiple small traces that must be accumulated
**Solution**: 
- Wait 2 seconds after last trace before finalizing chunk
- Only increment chunk_id when chunk is complete
- Frontend sees complete, aligned chunks instead of fragments

**Result**: Now receiving 3300-4500 samples per chunk with proper alignment at boundaries

### Key Learnings:

1. **SeedLink Data Delivery**: Sends multiple small traces in quick succession that need accumulation
2. **Fixed vs Scrolling Windows**: Fixed visualization window (8k) with unlimited internal buffer caused issues
3. **Bounded Buffers**: 50k sample limit prevents unbounded memory growth while providing headroom
4. **Adaptive Normalization**: Immediate initialization prevents off-scale startup artifacts
5. **Visual Debugging**: Chunk boundary markers essential for verifying proper data alignment

### Technical Architecture:

**Backend** (`chunk_forwarder.py`):
```
SeedLink → on_data() → Accumulate traces → 2s timeout → Finalize chunk → API endpoint
```

**Frontend** (`dashboard_chunk_viewer.html`):
```
Poll API (100ms) → Add to buffer → Trim if >50k → Consume at playback rate → Visualize first 8k
```

**Buffer Management**:
- Internal: Unlimited growth during accumulation, trim to 50k on chunk arrival
- Visualization: Always show first 8k samples (what's being "played")
- Playback: shift() from front at adjustable rate (1-200 Hz)

### Version
**v1.02**  
**Commit Message**: "v1.02 Feature: Created SeedLink chunk forwarder with live waveform viewer - fixed-size scrolling buffer visualization, adaptive normalization, playback rate control (1-200Hz), live output meter"

---

## Adaptive Speed Control for Chunk Viewer

### Changes Made:

1. **Adaptive Speed Control System**
   - Toggle button to enable/disable adaptive mode (defaults ON)
   - Three configurable zones: Low Buffer (slow down), Normal Range, High Buffer (speed up)
   - Low buffer thresholds: ≤500, ≤1000, ≤1500 samples → rates: 40, 60, 80 Hz
   - High buffer thresholds: ≥4000, ≥6000, ≥8000 samples → rates: 120, 150, 200 Hz
   - Normal range (1500-4000 samples) → 100 Hz
   - All thresholds and rates editable in real-time

2. **Linear Ramping Transitions**
   - Fixed issue with exponential smoothing causing rate drift
   - Implemented proper linear ramp function over configurable smooth time (default 3s)
   - Ramps at 10 steps/second for smooth transitions
   - Guarantees exact target rate at end of ramp
   - Cancels previous ramp when new target detected (no overlapping ramps)

3. **Display Rate Optimization**
   - Increased drawing rate from 20fps (50ms) to 60fps (17ms) for buttery smooth display
   - Adjusted adaptive scaling alpha from 0.01 to 0.0033 to maintain 5s time constant at 60fps
   - Separated meter/stats updates (60fps) from data consumption (variable adaptive rate)
   - Fixed meter jitter by decoupling meter updates from playback rate

4. **UI Improvements**
   - Fixed current output meter width (60px) to prevent shrinking on small screens
   - Removed header text from Statistics and Adaptive Speed Control sections for cleaner look
   - Moved smooth transition time control to same row as enable button
   - Color-coded zones: Blue (slow down), Green (normal), Red (speed up)

5. **Code Cleanup**
   - Removed debug console logs for scan calls
   - Separated visualization logic from core data processing for future modularity
   - All meter and stats updates now run at fixed 60fps regardless of playback speed

### Major Bug Fixed: Rate Drift and Jitter

**Problem**: Playback rate would drift to values like 106Hz instead of 100Hz, and meter updates were jerky
**Root Causes**: 
1. Exponential smoothing recalculated every 100ms, causing cumulative rounding errors
2. Meter updates tied to variable playback rate interval
**Solutions**:
1. Linear ramp function that draws straight line from start to end rate
2. Fixed 60fps update loop for all visualization (meter, stats, waveform)
3. Data consumption separated to run at variable adaptive playback rate

**Result**: Exact target rates reached, smooth 60fps display regardless of playback speed changes

### Key Learnings:

1. **Linear vs Exponential Ramping**: True linear ramp (constant velocity) better than exponential smoothing (slowing approach) for rate changes
2. **Decoupling Update Rates**: Visual updates should run at fixed frame rate, independent of data processing rate
3. **Ramp Interruption**: Must cancel active ramps when new target detected to avoid jitter
4. **Time Constants at Different Frame Rates**: Alpha values must scale with frame rate to maintain same smoothing behavior

### Technical Architecture:

**Adaptive Rate Logic**:
```
Check buffer size → Calculate target rate → Start linear ramp if changed
Ramp: newRate = startRate + (delta * step/totalSteps) for each 100ms
```

**Update Loops**:
- **60fps (17ms)**: drawWaveform() → updateStats() → updateScanLine() → draw canvas
- **100ms**: fetchChunk() (get new data from backend)
- **100ms**: updateAdaptiveRate() (check if target rate changed)
- **Variable**: advanceScan() (consume data at adaptive playback rate)

### Version
**v1.03**  
**Commit**: `Pending`  
**Commit Message**: "v1.03 Enhancement: Added adaptive speed control to chunk viewer - configurable buffer thresholds, linear ramping transitions, 60fps display, fixed meter width"

---

## Data-First Architecture & Parameter Mapping Sonification

### Major Refactoring: Data-First Architecture (5 Phases Completed)

**Goal**: Separate data calculations from visualization to enable modular, reusable code where rendering is optional.

#### Phase 1: Data State Object
- Created centralized `dataState` object holding all calculated values
- Added `updateDataState()` function running at 60fps independently
- Stores: currentOutput (raw + normalized), smoothedOutput, adaptive scaling, visual data window, statistics
- Runs continuously even when visualization is paused

#### Phase 2: Extracted Adaptive Scaling Logic
- Removed min/max calculations from `drawWaveform()`
- All scaling calculations moved to `updateDataState()`
- Rendering functions now pure - only read from `dataState` and update DOM

#### Phase 3 & 4: Current Value & Stats Separation (Combined)
- Extracted current output calculation (raw + normalized) to data loop
- Split `updateStats()` into calculate (data loop) + render (display loop)
- Meter updates now read pre-calculated values from `dataState`

#### Phase 5: Visualization Toggle
- Added checkbox to pause waveform rendering
- Meter bar and stats continue updating when visualization paused
- Shows "WAVEFORM PAUSED" overlay when disabled

### IRIS Duplicate Detection & Auto-Deduplication

**Problem**: IRIS sometimes sends overlapping data chunks causing duplicate waveform patterns.

**Solution Implemented**:
1. **Exact Overlap Detection**: Checks up to 500 samples for matches between buffer end and chunk start
2. **Internal Pattern Detection**: Finds repeating patterns within chunks (95% similarity threshold)
3. **Fingerprint Comparison**: Compares first/last 10 values between chunks
4. **Automatic De-duplication**: When exact overlap detected (≥10 samples):
   - Trims duplicate samples from START of new chunk
   - Only adds clean data to buffer
   - Logs removal with before/after sizes
   - Shows orange badge in chunk log

**Result**: Successfully catches and removes IRIS overlaps (example: removed 390 duplicate samples from chunk 2392)

### Adaptive Rate Conservative Tuning

**Change**: Updated low-buffer rates to be more conservative:
- ≤500 samples: 40 Hz → **20 Hz** (50% slower for max cushion)
- ≤1000 samples: 60 Hz → **50 Hz** (17% slower)  
- ≤1500 samples: 80 Hz → **70 Hz** (13% slower)

**Reason**: Provide more time for chunks to arrive when buffer is critically low, preventing starvation.

### Parameter Mapping Sonification Section

#### Left Side: Instantaneous Output Meters
- **RAW Meter**: Shows `dataState.currentOutputNormalized` (green gradient)
- **SMOOTHED Meter**: Shows lowpass filtered version (orange gradient)
- Both update at 60fps, displays as vertical bars with normalized values (0-1)
- **Smoothing Controls**:
  - Enable/disable checkbox
  - Smooth Time slider: 20-500ms (default 100ms)
  - Exponential smoothing: `y[n] = α·x[n] + (1-α)·y[n-1]`
  - Alpha calculated from smooth time: `α = 1 - exp(-Δt/τ)`

#### Right Side: Audio Synthesis
- **Sine Wave Generator**: Using Web Audio API OscillatorNode
- **Start/Stop Audio** button
- **Parameter Mapping** (data-driven):
  - **Map to Amplitude** (default ON): Gain = smoothedValue * 0.5
  - **Map to Frequency** (default OFF): 100-300 Hz range
  - Redundant mapping: Both can be active simultaneously
- **Audio Parameter Updates**:
  - Updates at 60fps from `dataState.smoothedOutputNormalized`
  - Uses `exponentialRampToValueAtTime()` with 20ms ramp to prevent clicks
  - Displays real-time amplitude and frequency values

### Major Bug Fixed: Audio Clicking

**Problem**: Crazy clicking sounds when audio enabled
**Root Causes**:
1. Using `setValueAtTime()` caused instantaneous jumps at 60fps
2. 60 discontinuities/second = audible clicks
**Solution**:
- Changed to `exponentialRampToValueAtTime()` with 20ms ramp time
- Added `cancelScheduledValues()` to prevent automation conflicts
- Clamped gain to minimum 0.001 (exponential ramps can't go to zero)
**Result**: Smooth, click-free parameter updates

### Key Learnings:

1. **Data-First Architecture**: Separating calculations from rendering enables:
   - True modularity (can extract and reuse modules)
   - Optional visualization
   - Multiple visualizations from same data source
   - Easier testing and verification

2. **IRIS Data Quality**: Overlapping chunks are a known issue, frontend de-duplication is essential

3. **Web Audio API**: Parameter changes must use ramps, not instant sets, to avoid clicks

4. **Exponential Smoothing at Audio Rates**: Proper alpha calculation critical: `α = 1 - exp(-1/(τ·fs))`

### Technical Architecture:

**Data Loop (ALWAYS RUNS @ 60fps)**:
```
updateDataState()
  ├─ Calculate currentOutput (raw + normalized)
  ├─ Calculate smoothedOutput (exponential filter)
  ├─ Extract visualData window
  ├─ Calculate adaptive scaling (min/max)
  └─ Calculate statistics
```

**Render Loop (CONDITIONAL @ 60fps)**:
```
drawWaveform()
  ├─ updateStats() → read dataState
  ├─ updateScanLine() → read dataState
  ├─ updateParameterMappingMeters() → read dataState (RAW + SMOOTHED)
  ├─ updateAudioParameters() → read dataState (map to audio)
  └─ if (visualizationEnabled) { draw canvas }
```

### Version
**v1.04**  
**Commit**: `Pending`  
**Commit Message**: "v1.04 Major Update: Data-first architecture refactor, IRIS duplicate detection/auto-deduplication, parameter mapping sonification with RAW/SMOOTHED meters, audio synthesis with amplitude/frequency mapping (100-300Hz), exponential smoothing, visualization toggle"

---

