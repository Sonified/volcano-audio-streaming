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

