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

