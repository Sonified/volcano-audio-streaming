"""
Real-time SeedLink audification proof-of-concept
Streams live seismic data from IRIS and plays it as audio
"""

import numpy as np
import sounddevice as sd
from obspy.clients.seedlink import EasySeedLinkClient
from scipy import signal
from collections import deque
import json
import threading
import queue
from datetime import datetime
from flask import Flask, jsonify, render_template
from flask_cors import CORS

class LiveAudifier(EasySeedLinkClient):
    def __init__(self):
        super().__init__('rtserve.iris.washington.edu:18000')
        self.audio_sample_rate = 44100  # Standard audio rate
        self.seismic_sample_rate = 100  # HHZ channels are 100 Hz
        
        # THREAD-SAFE QUEUE ARCHITECTURE:
        # SeedLink thread -> raw_data_queue -> Processing thread -> seismic_buffer -> Audio thread
        self.raw_data_queue = queue.Queue(maxsize=100)  # Raw data from SeedLink (thread-safe)
        self.seismic_buffer = deque()  # Processed audio-ready samples (no maxlen - manual management)
        self.playback_position = 0  # Index into seismic_buffer (only accessed by audio thread)
        
        # High-pass filter (remove DC offset and low freq noise) - used by processing thread
        self.sos = signal.butter(4, 0.1, 'hp', fs=self.seismic_sample_rate, output='sos')
        self.zi = signal.sosfilt_zi(self.sos)
        
        # Normalization (adaptive)
        self.running_max = 1000  # Will adapt based on data
        
        # Diagnostics tracking
        self.stats = {
            'connected': False,
            'network': '',
            'station': '',
            'channel': '',
            'last_update': None,
            'sample_count': 0,
            'buffer_size': 0,
            'current_max': 0,
            'running_max': self.running_max,
            'audio_active': False,
            'packets_received': 0,
            'underruns': 0
        }
        self.recent_data = deque(maxlen=1000)  # Store last 1000 samples for visualization
        self.playback_started = False
        
        # Detailed diagnostics
        self.packet_times = []
        self.total_samples_received = 0
        self.total_samples_consumed = 0
        self.last_packet_time = None
        self.first_packet_time = None
        
        # Audio thread state (only accessed by audio callback)
        self.current_amplitude = 0.0  # Current amplitude being played (raw)
        self.current_amplitude_smoothed = 0.0  # Current smoothed amplitude
        
        # Low-pass smoothing filter (exponential moving average at audio rate)
        self.smoothing_time = 0.5  # Default 500ms smoothing
        self.smoothed_value = 0.0  # Current smoothed output value
        self.smoothing_alpha = self._calculate_smoothing_alpha()
        
        # Hold last sample value on underruns (prevents sudden jumps to zero)
        self.last_raw_sample = 0.0  # Hold this value when buffer runs out
        
        # Speed ramp-up smoothing (for gradual return to normal speed)
        self.current_speed_multiplier = 1.0  # Current effective speed multiplier
        self.speed_ramp_time = 2.0  # Ramp up over 2 seconds (200 seismic samples at 100 Hz)
        # Calculate increment per audio sample to reach 1.0 in speed_ramp_time seconds
        self.speed_ramp_increment_per_sample = 1.0 / (self.speed_ramp_time * self.audio_sample_rate)
        
        # Store both raw and smoothed samples for visualization
        self.recent_data_raw_interpolated = deque(maxlen=1000)  # Raw interpolated at audio rate
        self.recent_data_smoothed = deque(maxlen=1000)  # Smoothed at audio rate
        
        # Latest chunk from IRIS (just forward, no buffering)
        self.latest_raw_chunk = []  # Most recent packet from IRIS
        self.latest_chunk_id = 0  # Increment each time we get new data from IRIS
        self.raw_chunk_buffer = deque(maxlen=5000)  # Store last 5000 processed samples for browser (for compatibility)
        
        # Pause state
        self.paused = False
        
        # Fade-out state (for clean reset - only modified by audio callback)
        self.fade_out_requested = False
        self.fading_out = False
        self.fade_samples_remaining = 0  # Samples remaining in fade
        self.fade_total_samples = 0  # Total fade duration (for calculating progress)
        self.fade_factor = 1.0  # Current fade multiplier (1.0 = full volume, 0.0 = silent)
        
        # Processing thread control
        self.processing_active = True
        
        # Start processing thread (lower priority - does heavy filtering/normalization)
        self.processing_thread = threading.Thread(target=self._processing_worker, daemon=True, name="ProcessingThread")
        self.processing_thread.start()
        
        # Start audio stream at 44.1 kHz (real-time priority handled by sounddevice)
        self.audio_stream = sd.OutputStream(
            samplerate=44100,
            channels=1,
            callback=self.audio_callback,
            blocksize=8820  # 0.2 second blocks (doubled for safety)
        )
        self.audio_stream.start()
        self.stats['audio_active'] = True
        print("=" * 80)
        print("🔊 Audio stream: 44.1 kHz with smooth interpolation")
        print("⏱️  THREADED ARCHITECTURE:")
        print("   • SeedLink thread: Receives raw data, dumps to queue (no processing)")
        print("   • Processing thread: Filters + normalizes in background (lower priority)")
        print("   • Audio thread: Real-time playback from pre-processed buffer (high priority)")
        print(f"📦 Buffer: Thread-safe deque, 10 second capacity")
        print(f"🎵 Frequency range: 0.1 Hz - 50 Hz (infrasound/low freq)")
        print(f"🎚️  Playback rate: {self.seismic_sample_rate / self.audio_sample_rate:.6f} seismic/audio sample")
        print(f"🎛️  Smoothing filter: {self.smoothing_time*1000:.0f}ms time constant (exponential low-pass, default 500ms)")
        print("⏳ Waiting for seismic data from IRIS SeedLink...")
        print("=" * 80)
    
    def _calculate_smoothing_alpha(self):
        """Calculate smoothing alpha from time constant"""
        # alpha = dt / tau, where dt = 1/44100, tau = smoothing_time
        dt = 1.0 / self.audio_sample_rate
        return dt / self.smoothing_time
    
    def on_data(self, trace):
        """Called when new seismic data arrives (every ~5 seconds)
        LIGHTWEIGHT: Just dump raw data to queue for processing thread"""
        
        # Track packet timing
        import time
        current_time = time.time()
        time_since_last = None
        if self.last_packet_time is not None:
            time_since_last = current_time - self.last_packet_time
        else:
            self.first_packet_time = current_time
        self.last_packet_time = current_time
        self.packet_times.append(current_time)
        
        # Get raw samples and total count
        samples = trace.data.astype(np.float32)
        sample_count = len(samples)
        self.total_samples_received += sample_count
        
        # Store latest chunk for direct browser access (NO BUFFERING - just latest packet)
        self.latest_raw_chunk = samples.tolist()
        self.latest_chunk_id += 1  # Increment ID so frontend knows it's new data
        
        # Quick non-blocking dump to processing queue
        try:
            self.raw_data_queue.put_nowait((samples, trace.stats.starttime, trace.stats.endtime))
            self.stats['packets_received'] += 1
            
            # Detailed logging
            time_str = f"Δt={time_since_last:.2f}s" if time_since_last else "Δt=N/A"
            seismic_duration = sample_count / self.seismic_sample_rate
            buffer_size = len(self.seismic_buffer)
            print(f"[DATA IN] Packet {self.stats['packets_received']:04d} | {time_str} | Seismic: {sample_count:4d}smpl ({seismic_duration:.1f}s) | Queue: {self.raw_data_queue.qsize()}/{self.raw_data_queue.maxsize} | Buffer: {buffer_size:5d} | Total RX: {self.total_samples_received:.0f}")
            print(f"           Trace time: {trace.stats.starttime} to {trace.stats.endtime}")
        except queue.Full:
            print(f"[DATA IN WARNING] Queue full! Dropped packet (processing thread may be overloaded)")
    
    def _processing_worker(self):
        """Background thread that does all the heavy processing (filtering, normalization)
        This runs at LOWER priority so it doesn't interfere with audio thread"""
        print("[PROCESSING THREAD] Started - waiting for data...")
        
        while self.processing_active:
            try:
                # Block until we get data (timeout to allow checking processing_active)
                samples, start_time, end_time = self.raw_data_queue.get(timeout=0.5)
                
                # 1. High-pass filter (remove drift) - HEAVY OPERATION
                filtered, self.zi = signal.sosfilt(self.sos, samples, zi=self.zi)
                
                # 2. Adaptive normalization
                current_max = np.abs(filtered).max()
                if current_max > 0:
                    self.running_max = 0.9 * self.running_max + 0.1 * current_max
                normalized = filtered / (self.running_max * 2)  # Scale to [-0.5, 0.5]
                
                # 3. Apply gain and clip
                amplified = np.clip(normalized * 3.0, -1.0, 1.0)
                
                # 4. CRITICAL: Clean up any NaN or inf values (linear interpolation)
                # Audio thread should NEVER see corrupted data!
                if not np.all(np.isfinite(amplified)):
                    print(f"[PROCESSING WARNING] Found NaN/inf in processed data - interpolating...")
                    # Find valid indices
                    valid_mask = np.isfinite(amplified)
                    if np.any(valid_mask):
                        # Interpolate over invalid values
                        valid_indices = np.where(valid_mask)[0]
                        invalid_indices = np.where(~valid_mask)[0]
                        # Use linear interpolation to fill gaps
                        amplified[invalid_indices] = np.interp(
                            invalid_indices,
                            valid_indices,
                            amplified[valid_indices]
                        )
                    else:
                        # Everything is corrupted - replace with zeros
                        print(f"[PROCESSING ERROR] Entire packet corrupted - replacing with zeros")
                        amplified = np.zeros_like(amplified)
                
                # Final safety check - ensure all values are finite and clamped
                amplified = np.nan_to_num(amplified, nan=0.0, posinf=1.0, neginf=-1.0)
                amplified = np.clip(amplified, -1.0, 1.0)
                
                # 4.5. Store raw chunk for browser delivery (before sending to audio buffer)
                self.raw_chunk_buffer.extend(amplified)
                
                # 5. Add to seismic buffer (thread-safe deque - no lock needed!)
                # deque.extend() is atomic when called from one side
                before_size = len(self.seismic_buffer)
                self.seismic_buffer.extend(amplified)
                after_size = len(self.seismic_buffer)
                
                # Debug: Print buffer status
                if after_size != before_size:
                    time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"[{time_str}] [PROCESSING] Added {len(amplified)} samples | Buffer: {before_size} → {after_size} | "
                          f"Playback started: {self.playback_started} | Fade requested: {self.fade_out_requested}")
                
                # Start playback once we have enough buffered (10 seconds minimum)
                if not self.playback_started and after_size >= 1000:
                    # CRITICAL: Add fade-in to prevent startup click!
                    # Prepend smooth transition from silence (0.0) to first buffer sample
                    print(f"[PLAYBACK START] Buffer filled to {after_size} samples. Creating fade-in to prevent click...")
                    
                    # Get first sample value from buffer
                    first_sample = self.seismic_buffer[0] if len(self.seismic_buffer) > 0 else 0.0
                    
                    # Create fade-in from 0.0 to first_sample over 1 second
                    fade_in_samples = 100  # 1 second at 100 Hz
                    fade_in = np.linspace(0.0, first_sample, fade_in_samples, dtype=np.float32)
                    # Apply exponential curve for natural fade-in
                    fade_curve = 1.0 - np.exp(-np.linspace(0, 5, fade_in_samples))  # 0 -> 1
                    fade_in = fade_in * fade_curve
                    
                    # Prepend fade-in to buffer (extendleft adds to front of deque)
                    fade_in_list = list(reversed(fade_in))  # Reverse because extendleft reverses
                    self.seismic_buffer.extendleft(fade_in_list)
                    
                    print(f"[PLAYBACK START] Added {fade_in_samples}-sample fade-in from 0.0 to {first_sample:.6f}")
                    
                    self.playback_started = True
                    print(f"[PLAYBACK START] Starting audio playback (total buffer: {len(self.seismic_buffer)} samples)")
                
                # Update diagnostics (non-critical, approximate values ok)
                self.stats.update({
                    'last_update': datetime.utcnow().isoformat(),
                    'sample_count': len(samples),
                    'buffer_size': len(self.seismic_buffer),
                    'current_max': float(current_max),
                    'running_max': float(self.running_max),
                })
                
                # Store recent data for visualization (downsample to 10 Hz)
                decimation_factor = int(self.seismic_sample_rate / 10)
                if decimation_factor > 0:
                    downsampled = filtered[::decimation_factor]
                    self.recent_data.extend(downsampled.tolist())
                
                # Log processing
                print(f"[PROCESSING] Filtered {len(samples)} samples | Buffer: {before_size}→{after_size} | Max: {current_max:.1f} | Running max: {self.running_max:.1f}")
                
            except queue.Empty:
                # Timeout - just continue to check processing_active
                continue
            except Exception as e:
                print(f"[PROCESSING ERROR] {e}")
                import traceback
                traceback.print_exc()
        
        print("[PROCESSING THREAD] Stopped")
    
    def audio_callback(self, outdata, frames, time, status):
        """Called by sounddevice when audio buffer needs filling
        REAL-TIME PRIORITY: Minimal work, just interpolate from pre-processed buffer"""
        if status:
            print(f"[AUDIO WARNING] {status}")
        
        # Don't start until buffer is filled
        if not self.playback_started:
            # Debug: Print why we're not playing (only once per second to avoid spam)
            import time
            if not hasattr(self, '_last_silence_debug_time'):
                self._last_silence_debug_time = 0
            current_time = time.time()
            if current_time - self._last_silence_debug_time > 1.0:
                self._last_silence_debug_time = current_time
                time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                buffer_len = len(self.seismic_buffer)
                print(f"[{time_str}] [AUDIO] Not playing - playback_started={self.playback_started}, "
                      f"buffer={buffer_len}, fade_requested={self.fade_out_requested}")
            outdata[:] = np.zeros((frames, 1))
            self.current_amplitude = 0.0
            return
        
        # If paused, output silence (don't advance playback position)
        if self.paused:
            outdata[:] = np.zeros((frames, 1))
            self.current_amplitude = 0.0
            return
        
        # Base playback rate (at native 100 Hz rate)
        base_playback_rate = self.seismic_sample_rate / self.audio_sample_rate
        
        # CRITICAL: Lock buffer length for entire callback block
        # Don't let it change mid-block even if processing thread adds data
        # This prevents speed multiplier discontinuities within a single audio block
        buffer_len = len(self.seismic_buffer)
        
        # CALCULATE SPEED MULTIPLIER ONCE FOR ENTIRE BLOCK (before the loop)
        # This prevents phase discontinuities from intra-block rate changes
        remaining_samples = max(0, buffer_len - self.playback_position)
        
        # Debug: Track last print time to avoid spam
        import time
        if not hasattr(self, '_last_speed_debug_time'):
            self._last_speed_debug_time = 0
        
        if remaining_samples < 1000:
            # AGGRESSIVE slowdown: 100x slower (0.01x) when buffer is nearly exhausted
            # Target: 1 sample/second at 1 sample remaining (vs normal 100 samples/second)
            # Linear interpolation: 1000 samples → 1.0x, 1 sample → 0.01x (100x slower)
            if remaining_samples > 1:
                # Map from [1, 1000] to [0.01, 1.0]
                # target_speed = 0.01 + (remaining_samples - 1) / (1000 - 1) * (1.0 - 0.01)
                target_speed = 0.01 + ((remaining_samples - 1) / 999.0) * 0.99
            else:
                # At 1 sample or less, go to minimum speed (1 sample per second)
                target_speed = 0.01
            # Ensure we never go below 0.01x (100x slower max)
            target_speed = max(0.01, target_speed)
            # Smooth transition to target speed
            speed_diff = target_speed - self.current_speed_multiplier
            self.current_speed_multiplier += speed_diff * 0.05
            
            # Debug print every 0.5 seconds when buffer is low
            current_time = time.time()
            if current_time - self._last_speed_debug_time > 0.5:
                self._last_speed_debug_time = current_time
                time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                effective_samples_per_sec = target_speed * 100.0  # 100 Hz normal rate
                print(f"[{time_str}] [SPEED] Remaining: {remaining_samples:.0f} | "
                      f"Target: {target_speed:.4f}x | Current: {self.current_speed_multiplier:.4f}x | "
                      f"Effective: {effective_samples_per_sec:.1f} samples/sec | "
                      f"Buffer: {buffer_len} | Pos: {self.playback_position:.2f}")
        else:
            # Normal speed with smooth ramp-up
            if self.current_speed_multiplier < 1.0:
                # Gradually ramp up to 1.0 (prevents clicks when buffer refills)
                remaining_distance = 1.0 - self.current_speed_multiplier
                # Exponential approach: faster when further away, slower when close
                increment = remaining_distance * 0.01  # Per block, not per sample
                self.current_speed_multiplier = min(1.0, self.current_speed_multiplier + increment)
            else:
                self.current_speed_multiplier = 1.0
        
        # Lock playback rate for this entire block (constant for all samples)
        playback_rate = base_playback_rate * self.current_speed_multiplier
        
        # Debug: Also print when buffer is healthy but we're still recovering speed
        if remaining_samples >= 1000 and self.current_speed_multiplier < 0.99:
            current_time = time.time()
            if not hasattr(self, '_last_normal_debug_time'):
                self._last_normal_debug_time = 0
            if current_time - self._last_normal_debug_time > 2.0:  # Every 2 seconds
                self._last_normal_debug_time = current_time
                time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{time_str}] [SPEED] Buffer healthy: {remaining_samples:.0f} remaining | "
                      f"Recovering speed: {self.current_speed_multiplier:.4f}x | "
                      f"Playback rate: {playback_rate:.6f} seismic/audio")
        
        # Handle fade-out if requested (check before generating samples)
        if self.fade_out_requested and not self.fading_out:
            self.fading_out = True
            time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{time_str}] [FADE] Starting fade-out at position {self.playback_position:.2f} | "
                  f"Buffer size: {buffer_len} | fade_samples_remaining: {self.fade_samples_remaining}")
        
        # Generate audio samples by interpolating through seismic buffer
        audio_out = []
        raw_samples = []  # Store raw interpolated samples for visualization
        
        for i in range(frames):
            # NO MORE SPEED CALCULATIONS HERE - use locked playback_rate
            
            # Check if we have data to read
            idx = int(self.playback_position)
            if buffer_len == 0 or idx >= buffer_len - 1:
                # Out of data - HOLD last value (don't jump to zero!)
                self.stats['underruns'] += 1
                if self.stats['underruns'] % 50 == 0:
                    print(f"[AUDIO UNDERRUN #{self.stats['underruns']}] Pos: {self.playback_position:.2f}, Buffer: {buffer_len}, Last: {self.last_raw_sample:.6f}")
                raw_sample = self.last_raw_sample
                # Don't advance playback position
            else:
                # Linear interpolation (deque supports indexing, though O(n) for middle)
                # Since we're reading from the beginning, it's O(1)
                try:
                    frac = self.playback_position - idx
                    current_sample = self.seismic_buffer[idx]
                    next_sample = self.seismic_buffer[min(idx + 1, buffer_len - 1)]
                    raw_sample = current_sample * (1 - frac) + next_sample * frac
                    
                    # Smooth transitions after underruns
                    if abs(raw_sample - self.last_raw_sample) > 0.5:
                        blend_factor = 0.1
                        raw_sample = self.last_raw_sample * (1 - blend_factor) + raw_sample * blend_factor
                    
                    self.last_raw_sample = raw_sample
                    self.playback_position += playback_rate
                except IndexError:
                    # Race condition - buffer changed, use last sample
                    raw_sample = self.last_raw_sample
            
            # SAFETY: Check for NaN/inf (should never happen after processing thread, but just in case)
            # If corrupted, SKIP FORWARD to find next valid sample in buffer
            if not np.isfinite(raw_sample):
                print(f"[AUDIO SAFETY] NaN/inf detected at pos {self.playback_position:.2f} - searching for next valid sample...")
                # Try to find next valid sample (scan up to 100 samples ahead)
                found_valid = False
                search_limit = min(idx + 100, buffer_len - 1)
                for search_idx in range(idx + 1, search_limit):
                    try:
                        test_sample = self.seismic_buffer[search_idx]
                        if np.isfinite(test_sample):
                            raw_sample = test_sample
                            self.playback_position = float(search_idx)
                            found_valid = True
                            print(f"[AUDIO SAFETY] Found valid sample at pos {search_idx} (value: {raw_sample:.6f})")
                            break
                    except IndexError:
                        break
                
                # If no valid sample found ahead, hold last known good value
                if not found_valid:
                    raw_sample = self.last_raw_sample
                    print(f"[AUDIO SAFETY] No valid samples ahead - holding last value: {raw_sample:.6f}")
            
            # Apply low-pass smoothing filter (exponential moving average)
            # y[n] = alpha * x[n] + (1 - alpha) * y[n-1]
            # EVERYTHING goes through this filter - no abrupt changes ever!
            self.smoothed_value = self.smoothing_alpha * raw_sample + (1 - self.smoothing_alpha) * self.smoothed_value
            
            # SAFETY: If smoothed value corrupted after filtering (should be impossible), hold last raw sample
            if not np.isfinite(self.smoothed_value):
                self.smoothed_value = self.last_raw_sample  # Last resort
                print(f"[AUDIO SAFETY] Smoothed value corrupted - holding: {self.smoothed_value:.6f}")
            
            # Clamp to valid range (gentle ceiling/floor, not abrupt reset)
            self.smoothed_value = np.clip(self.smoothed_value, -1.0, 1.0)
            
            # Store raw sample for visualization
            raw_samples.append(raw_sample)
            
            # Calculate fade factor if fade-out is active
            fade_factor = 1.0
            if self.fade_out_requested and self.fading_out:
                if self.fade_samples_remaining > 0:
                    # Calculate fade progress: samples faded / total fade samples
                    samples_faded = self.fade_total_samples - self.fade_samples_remaining
                    fade_progress = samples_faded / self.fade_total_samples if self.fade_total_samples > 0 else 0.0
                    # Linear fade from 1.0 to 0.0
                    fade_factor = max(0.0, 1.0 - fade_progress)
                    self.fade_samples_remaining -= 1
                    
                    # Check if fade is complete
                    if self.fade_samples_remaining <= 0:
                        # Fade complete - now safe to reset everything
                        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print(f"[{time_str}] [FADE] Completed - clearing buffer and resetting playback | "
                              f"Buffer was: {len(self.seismic_buffer)} samples")
                        self.seismic_buffer.clear()
                        self.playback_position = 0
                        self.smoothed_value = 0.0
                        self.last_raw_sample = 0.0
                        self.fade_out_requested = False
                        self.fading_out = False
                        self.fade_factor = 1.0
                        self.playback_started = False
                        print(f"[{time_str}] [FADE] Buffer cleared, playback_started=False")
                        fade_factor = 0.0  # Ensure silence for rest of block
                        # Output remaining samples as silence
                        remaining_frames = frames - i
                        for _ in range(remaining_frames):
                            audio_out.append(0.0)
                            raw_samples.append(0.0)
                        break
            
            # Output smoothed version to audio with fade applied (no sudden jumps - holds value on underrun)
            audio_out.append(self.smoothed_value * fade_factor)
            
            # Store current amplitude for live monitoring
            self.current_amplitude = raw_sample  # Raw for comparison
            self.current_amplitude_smoothed = self.smoothed_value  # Smoothed for audio output
        
        # Store recent data for visualization (downsample to ~10 Hz)
        # Decimate to match visualization rate
        decimation_factor = int(self.audio_sample_rate / 10)  # ~4410 samples -> 1 sample at 10 Hz
        if decimation_factor > 0 and len(raw_samples) >= decimation_factor:
            # Store both raw and smoothed versions
            raw_decimated = raw_samples[::decimation_factor]
            smoothed_decimated = audio_out[::decimation_factor]
            
            # Extend visualization buffers (these will be downsampled further by dashboard)
            for raw_val, smooth_val in zip(raw_decimated, smoothed_decimated):
                self.recent_data_raw_interpolated.append(raw_val)
                self.recent_data_smoothed.append(smooth_val)
        
        # Track seismic samples consumed (INTEGER COUNT ONLY - not fractional!)
        # playback_position already represents the consumed position in the buffer
        # The integer part is the number of seismic samples consumed
        self.total_samples_consumed = int(self.playback_position)
        
        # Output smoothed audio
        outdata[:] = np.array(audio_out).reshape(-1, 1)
    
    def run_audification(self, network, station, channel='HHZ'):
        """Start streaming and audifying"""
        self.stats.update({
            'connected': True,
            'network': network,
            'station': station,
            'channel': channel
        })
        print(f"Connecting to {network}.{station}..{channel}")
        self.select_stream(network, station, channel)
        self.run()  # Blocks forever, streaming data
    
    def get_stats(self):
        """Get current diagnostics"""
        stats = self.stats.copy()
        stats['paused'] = self.paused
        stats['smoothing_time'] = self.smoothing_time  # Include smoothing time for display
        return stats
    
    def get_recent_data(self):
        """Get recent waveform data for visualization (filtered seismic at 10Hz)"""
        return list(self.recent_data)
    
    def get_recent_data_raw_interpolated(self):
        """Get recent raw interpolated waveform data for visualization (at audio rate, downsampled to 10Hz)"""
        return list(self.recent_data_raw_interpolated)
    
    def get_recent_data_smoothed(self):
        """Get recent smoothed waveform data for visualization (at audio rate, downsampled to 10Hz)"""
        return list(self.recent_data_smoothed)
    
    def set_smoothing_time(self, time_seconds):
        """Set smoothing time constant (0.02 to 0.5 seconds)"""
        if 0.02 <= time_seconds <= 0.5:
            self.smoothing_time = time_seconds
            self.smoothing_alpha = self._calculate_smoothing_alpha()
            print(f"[SMOOTHING] Updated to {self.smoothing_time*1000:.0f}ms ({self.smoothing_time}s)")
            return True
        return False
    
    def pause_audio(self):
        """Pause audio playback (data still accumulates in buffer)"""
        self.paused = True
        print("[PAUSE] Audio playback paused")
    
    def resume_audio(self):
        """Resume audio playback"""
        self.paused = False
        print("[RESUME] Audio playback resumed")
    
    def inject_test_samples(self, value, count=10):
        """Inject test samples directly to processed buffer (bypasses processing thread)
        For testing purposes only"""
        if count <= 0:
            return False
        
        # Create test samples directly in the processed range (-1 to 1)
        # Bypass filtering and normalization for immediate injection
        test_samples = np.full(count, float(value), dtype=np.float32)
        test_samples = np.clip(test_samples, -1.0, 1.0)
        
        # Add directly to seismic buffer (thread-safe deque)
        before_size = len(self.seismic_buffer)
        self.seismic_buffer.extend(test_samples)
        after_size = len(self.seismic_buffer)
        
        # Update total samples received
        self.total_samples_received += count
        
        # Update diagnostics
        self.stats['buffer_size'] = len(self.seismic_buffer)
        
        print(f"[INJECT] Added {count} test samples at value {value}. Buffer: {before_size}→{after_size}")
        return True
    
    def skip_samples(self, num_samples):
        """Skip forward by moving playback position ahead (for testing buffer behavior)
        Only clamp if skipping would exceed the buffer - allow landing in 1-1000 range for testing"""
        buffer_len = len(self.seismic_buffer)
        if buffer_len == 0:
            return False
        
        # Calculate what would remain after skipping
        new_position = self.playback_position + num_samples
        
        # Only clamp if we would go beyond the buffer (allows testing 1-1000 range)
        if new_position >= buffer_len - 0.5:
            # Clamp to 0.5 before end (matches underrun behavior)
            self.playback_position = max(0, buffer_len - 0.5)
            remaining = buffer_len - self.playback_position
            print(f"[SKIP] Advanced to end of buffer (would exceed buffer). Position: {self.playback_position:.2f} / {buffer_len} (remaining: {remaining:.1f})")
        else:
            self.playback_position = new_position
            remaining_after_skip = buffer_len - new_position
            print(f"[SKIP] Advanced playback position by {num_samples} samples. New position: {self.playback_position:.2f} / {buffer_len} (remaining: {remaining_after_skip:.0f})")
        
        return True
    
    def request_reset(self):
        """Request a fade-out reset - safe to call from any thread.
        The actual fade and buffer clearing happens in the audio callback."""
        if not self.fade_out_requested:
            # Request fade-out (0.5 seconds at audio rate)
            fade_duration_seconds = 0.5
            self.fade_total_samples = int(fade_duration_seconds * self.audio_sample_rate)
            self.fade_samples_remaining = self.fade_total_samples
            self.fade_out_requested = True
            self.fade_factor = 1.0  # Start at full volume
            print(f"[RESET REQUESTED] Fade-out requested for {self.fade_samples_remaining} samples ({fade_duration_seconds}s)")
        
        # Reset counters and stats (safe to do immediately)
        self.stats['packets_received'] = 0
        self.stats['underruns'] = 0
        self.total_samples_received = 0
        self.total_samples_consumed = 0
        self.packet_times = []
        self.first_packet_time = None
        self.last_packet_time = None
        
        # Clear visualization buffers (safe)
        self.recent_data.clear()
        self.recent_data_raw_interpolated.clear()
        self.recent_data_smoothed.clear()
        
        # Clear processing queue (safe)
        while not self.raw_data_queue.empty():
            try:
                self.raw_data_queue.get_nowait()
            except queue.Empty:
                break
        
        print("[RESET REQUESTED] Statistics cleared, fade-out will complete in audio callback")
    
    def reset_stats(self):
        """Reset all statistics and buffers - now uses fade-out in audio callback"""
        self.request_reset()
    
    def stop_stream(self):
        """Stop the audio stream and close connection"""
        print("[STOP] Stopping audio stream and closing SeedLink connection...")
        
        # Stop processing thread
        self.processing_active = False
        if hasattr(self, 'processing_thread'):
            print("[STOP] Waiting for processing thread to finish...")
            self.processing_thread.join(timeout=2.0)
        
        # Stop audio stream
        if hasattr(self, 'audio_stream') and self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
            print("[STOP] Audio stream stopped")
        
        # Update connection status
        self.stats['connected'] = False
        self.stats['audio_active'] = False
        
        # Close SeedLink connection
        try:
            self.close()
            print("[STOP] SeedLink connection closed")
        except:
            pass
        
        print("[STOP] Stream stopped successfully")
        
        # Exit the process after a short delay
        import sys
        import threading
        def delayed_exit():
            import time
            time.sleep(1)  # Give time for response to be sent
            print("[STOP] Exiting backend...")
            sys.exit(0)
        threading.Thread(target=delayed_exit, daemon=True).start()


# Flask server for diagnostics
app = Flask(__name__)
CORS(app)
audifier = None

@app.route('/')
def index():
    """Serve diagnostic dashboard"""
    import os
    dashboard_path = os.path.join(os.path.dirname(__file__), 'dashboard.html')
    with open(dashboard_path, 'r') as f:
        return f.read()

@app.route('/api/status')
def get_status():
    """Get current streaming status"""
    if audifier:
        stats = audifier.get_stats()
        # Add detailed diagnostics
        stats['total_samples_received'] = audifier.total_samples_received
        # Calculate consumed samples from playback position (always integer!)
        stats['total_samples_consumed'] = int(audifier.playback_position)
        stats['playback_started'] = audifier.playback_started
        stats['buffer_current'] = len(audifier.seismic_buffer)
        stats['buffer_max'] = 10000  # No hard limit, but show nominal
        stats['playback_position'] = audifier.playback_position
        
        # Calculate effective sampling rate
        if audifier.first_packet_time and audifier.last_packet_time:
            time_elapsed = audifier.last_packet_time - audifier.first_packet_time
            if time_elapsed > 0:
                stats['effective_sample_rate'] = audifier.total_samples_received / time_elapsed
            else:
                stats['effective_sample_rate'] = 0
        else:
            stats['effective_sample_rate'] = 0
            
        return jsonify(stats)
    return jsonify({'connected': False, 'error': 'Audifier not initialized'})

@app.route('/api/waveform')
def get_waveform():
    """Get recent waveform data (filtered seismic at 10Hz)"""
    if audifier:
        return jsonify({'data': audifier.get_recent_data()})
    return jsonify({'data': []})

@app.route('/api/waveform_raw_interpolated')
def get_waveform_raw_interpolated():
    """Get recent raw interpolated waveform data (at audio rate, downsampled to 10Hz)"""
    if audifier:
        return jsonify({'data': audifier.get_recent_data_raw_interpolated()})
    return jsonify({'data': []})

@app.route('/api/waveform_smoothed')
def get_waveform_smoothed():
    """Get recent smoothed waveform data (at audio rate, downsampled to 10Hz)"""
    if audifier:
        return jsonify({'data': audifier.get_recent_data_smoothed()})
    return jsonify({'data': []})

@app.route('/api/smoothing_time', methods=['POST'])
def set_smoothing_time():
    """Set smoothing time constant"""
    from flask import request
    if audifier:
        data = request.get_json()
        time_seconds = float(data.get('time', 0.05))
        success = audifier.set_smoothing_time(time_seconds)
        if success:
            return jsonify({'success': True, 'smoothing_time': audifier.smoothing_time})
        else:
            return jsonify({'success': False, 'error': 'Smoothing time must be between 0.02 and 0.5 seconds'})
    return jsonify({'success': False, 'error': 'Audifier not initialized'})

@app.route('/api/packet_history')
def get_packet_history():
    """Get packet arrival timing history"""
    if audifier and len(audifier.packet_times) > 1:
        deltas = []
        for i in range(1, len(audifier.packet_times)):
            deltas.append(audifier.packet_times[i] - audifier.packet_times[i-1])
        return jsonify({
            'packet_count': len(audifier.packet_times),
            'deltas': deltas[-20:],  # Last 20 inter-packet times
            'avg_delta': sum(deltas) / len(deltas) if deltas else 0,
            'min_delta': min(deltas) if deltas else 0,
            'max_delta': max(deltas) if deltas else 0
        })
    return jsonify({'packet_count': 0, 'deltas': [], 'avg_delta': 0, 'min_delta': 0, 'max_delta': 0})

@app.route('/api/live_amplitude')
def get_live_amplitude():
    """Get the current amplitude being played RIGHT NOW (both raw and smoothed)"""
    if audifier:
        return jsonify({
            'amplitude': float(audifier.current_amplitude),
            'amplitude_smoothed': float(audifier.current_amplitude_smoothed)
        })
    return jsonify({'amplitude': 0.0, 'amplitude_smoothed': 0.0})

@app.route('/api/inject_samples', methods=['POST'])
def inject_samples():
    """Inject test samples at specified value (for testing signal jumps)"""
    from flask import request
    if audifier:
        data = request.get_json()
        value = float(data.get('value', 0))
        count = int(data.get('count', 10))
        success = audifier.inject_test_samples(value, count)
        if success:
            return jsonify({'success': True, 'message': f'Injected {count} samples at value {value}', 'buffer_size': len(audifier.seismic_buffer)})
        else:
            return jsonify({'success': False, 'error': 'Invalid parameters'})
    return jsonify({'success': False, 'error': 'Audifier not initialized'})

@app.route('/api/skip_samples', methods=['POST'])
def skip_samples():
    """Skip forward by specified number of samples (for testing buffer behavior)
    If skipping would leave < 1000 samples, clamps to end"""
    from flask import request
    if audifier:
        data = request.get_json()
        num_samples = int(data.get('samples', 1000))
        success = audifier.skip_samples(num_samples)
        if success:
            return jsonify({'success': True, 'message': f'Skipped {num_samples} samples', 'playback_position': audifier.playback_position, 'buffer_size': len(audifier.seismic_buffer)})
        else:
            return jsonify({'success': False, 'error': 'Buffer is empty'})
    return jsonify({'success': False, 'error': 'Audifier not initialized'})

@app.route('/api/reset', methods=['POST'])
def reset_stats():
    """Reset all statistics and buffers"""
    if audifier:
        audifier.reset_stats()
        return jsonify({'success': True, 'message': 'Statistics reset'})
    return jsonify({'success': False, 'error': 'Audifier not initialized'})

@app.route('/api/pause', methods=['POST'])
def pause_audio():
    """Pause audio playback"""
    if audifier:
        audifier.pause_audio()
        return jsonify({'success': True, 'message': 'Audio paused', 'paused': True})
    return jsonify({'success': False, 'error': 'Audifier not initialized'})

@app.route('/api/resume', methods=['POST'])
def resume_audio():
    """Resume audio playback"""
    if audifier:
        audifier.resume_audio()
        return jsonify({'success': True, 'message': 'Audio resumed', 'paused': False})
    return jsonify({'success': False, 'error': 'Audifier not initialized'})

@app.route('/api/stop', methods=['POST'])
def stop_stream():
    """Stop the audio stream and SeedLink connection"""
    if audifier:
        audifier.stop_stream()
        return jsonify({'success': True, 'message': 'Stream stopped'})
    return jsonify({'success': False, 'error': 'Audifier not initialized'})

@app.route('/api/get_raw_chunk')
def get_raw_chunk():
    """Get latest raw chunk from IRIS (NO buffering - just forwards the latest packet)"""
    if audifier:
        # Just send the latest chunk received from IRIS - no accumulation
        chunk_data = audifier.latest_raw_chunk
        
        return jsonify({
            'samples': chunk_data,
            'sample_count': len(chunk_data),
            'sample_rate': audifier.seismic_sample_rate,
            'chunk_id': audifier.latest_chunk_id  # So frontend can detect new vs. duplicate
        })
    return jsonify({'samples': [], 'sample_count': 0, 'sample_rate': 100, 'chunk_id': 0})

@app.route('/api/get_processed_chunk')
def get_processed_chunk():
    """Get processed audio-ready samples (filtered, normalized, clipped)"""
    if audifier:
        chunk_data = list(audifier.raw_chunk_buffer)
        buffer_size = len(audifier.seismic_buffer)
        
        return jsonify({
            'samples': chunk_data,
            'sample_count': len(chunk_data),
            'buffer_size': buffer_size,
            'sample_rate': audifier.seismic_sample_rate
        })
    return jsonify({'samples': [], 'sample_count': 0, 'buffer_size': 0, 'sample_rate': 100})

def run_flask():
    """Run Flask server in background thread"""
    app.run(host='0.0.0.0', port=8888, debug=False, use_reloader=False)

# Usage example
if __name__ == "__main__":
    # Install requirements first:
    # pip install obspy sounddevice scipy numpy flask flask-cors
    
    print("Starting diagnostic server on http://localhost:8888")
    
    # Start Flask server in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Create audifier - plays at 100 Hz (native seismic rate)
    audifier = LiveAudifier()
    
    # Stream from Kīlauea (NPOC station, vertical component)
    try:
        audifier.run_audification('HV', 'NPOC', 'HHZ')
    except KeyboardInterrupt:
        print("\nStopping...")
        audifier.audio_stream.stop()

