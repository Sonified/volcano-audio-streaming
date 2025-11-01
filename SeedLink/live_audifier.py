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
from datetime import datetime
from flask import Flask, jsonify, render_template
from flask_cors import CORS

class LiveAudifier(EasySeedLinkClient):
    def __init__(self):
        super().__init__('rtserve.iris.washington.edu:18000')
        self.audio_sample_rate = 44100  # Standard audio rate
        self.seismic_sample_rate = 100  # HHZ channels are 100 Hz
        # Store RAW seismic samples - no maxlen, we'll manage it manually
        self.seismic_buffer = []  # Just a simple list that grows
        
        # High-pass filter (remove DC offset and low freq noise)
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
        
        # Playback position in seismic buffer
        self.playback_position = 0.0  # Float for smooth interpolation
        self.current_amplitude = 0.0  # Current amplitude being played (raw)
        self.current_amplitude_smoothed = 0.0  # Current smoothed amplitude
        
        # Low-pass smoothing filter (exponential moving average at audio rate)
        self.smoothing_time = 0.05  # Default 50ms smoothing
        self.smoothed_value = 0.0  # Current smoothed output value
        self.smoothing_alpha = self._calculate_smoothing_alpha()
        
        # Store both raw and smoothed samples for visualization
        self.recent_data_raw_interpolated = deque(maxlen=1000)  # Raw interpolated at audio rate
        self.recent_data_smoothed = deque(maxlen=1000)  # Smoothed at audio rate
        
        # Pause state
        self.paused = False
        
        # Start audio stream at 44.1 kHz
        self.audio_stream = sd.OutputStream(
            samplerate=44100,
            channels=1,
            callback=self.audio_callback,
            blocksize=4410  # 0.1 second blocks
        )
        self.audio_stream.start()
        self.stats['audio_active'] = True
        print("=" * 80)
        print("🔊 Audio stream: 44.1 kHz with smooth interpolation")
        print("⏱️  MANUAL PLAYBACK: Step through seismic buffer at controlled rate")
        print(f"📦 Buffer: Simple growing list, auto-trimmed behind playback")
        print(f"🎵 Frequency range: 0.1 Hz - 50 Hz (infrasound/low freq)")
        print(f"🎚️  Playback rate: {self.seismic_sample_rate / self.audio_sample_rate:.6f} seismic/audio sample")
        print(f"🎛️  Smoothing filter: {self.smoothing_time*1000:.0f}ms time constant (exponential low-pass)")
        print("⏳ Waiting for seismic data from IRIS SeedLink...")
        print("=" * 80)
    
    def _calculate_smoothing_alpha(self):
        """Calculate smoothing alpha from time constant"""
        # alpha = dt / tau, where dt = 1/44100, tau = smoothing_time
        dt = 1.0 / self.audio_sample_rate
        return dt / self.smoothing_time
    
    def on_data(self, trace):
        """Called when new seismic data arrives (every ~5 seconds)"""
        
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
        
        # Get raw samples (int32 at 100 Hz)
        samples = trace.data.astype(np.float32)
        self.total_samples_received += len(samples)
        
        # 1. High-pass filter (remove drift)
        filtered, self.zi = signal.sosfilt(self.sos, samples, zi=self.zi)
        
        # 2. Adaptive normalization
        current_max = np.abs(filtered).max()
        if current_max > 0:
            self.running_max = 0.9 * self.running_max + 0.1 * current_max
        normalized = filtered / (self.running_max * 2)  # Scale to [-0.5, 0.5]
        
        # 3. Store RAW seismic samples (no upsampling yet)
        # Apply gain to normalized data
        amplified = np.clip(normalized * 3.0, -1.0, 1.0)
        
        # 4. Add to seismic buffer - just append!
        before_size = len(self.seismic_buffer)
        self.seismic_buffer.extend(amplified)
        after_size = len(self.seismic_buffer)
        
        # Trim old data that's been played (keep 10 seconds ahead of playback position)
        keep_ahead = 1000  # 10 seconds at 100 Hz
        if self.playback_position > keep_ahead:
            trim_point = int(self.playback_position - keep_ahead)
            self.seismic_buffer = self.seismic_buffer[trim_point:]
            self.playback_position -= trim_point
        
        # Start playback once we have enough buffered (10 seconds of seismic data minimum)
        if not self.playback_started and after_size >= 1000:
            self.playback_started = True
            print(f"[PLAYBACK START] Buffer filled to {after_size} seismic samples, starting audio...")
        
        # Update diagnostics
        self.stats.update({
            'last_update': datetime.utcnow().isoformat(),
            'sample_count': len(samples),
            'buffer_size': len(self.seismic_buffer),
            'current_max': float(current_max),
            'running_max': float(self.running_max),
            'packets_received': self.stats['packets_received'] + 1
        })
        
        # Store recent data for visualization (downsample to 10 Hz for visualization)
        decimation_factor = int(self.seismic_sample_rate / 10)
        if decimation_factor > 0:
            downsampled = filtered[::decimation_factor]
            self.recent_data.extend(downsampled.tolist())
            # Smoothed version will be stored from audio callback
        
        # Detailed logging
        time_str = f"Δt={time_since_last:.2f}s" if time_since_last else "Δt=N/A"
        seismic_duration = len(samples) / self.seismic_sample_rate
        print(f"[DATA IN] Packet {self.stats['packets_received']:04d} | {time_str} | Seismic: {len(samples):4d}smpl ({seismic_duration:.1f}s) | Buffer: {before_size:5d}→{after_size:5d} | Playback pos: {self.playback_position:.1f} | Total RX: {self.total_samples_received:.0f} | Total consumed: {self.total_samples_consumed:.0f}")
        print(f"           Trace time: {trace.stats.starttime} to {trace.stats.endtime}")
    
    def audio_callback(self, outdata, frames, time, status):
        """Called by sounddevice when audio buffer needs filling
        Steps through seismic buffer and interpolates smoothly at 44.1 kHz"""
        if status:
            print(f"[AUDIO WARNING] {status}")
        
        # Don't start until buffer is filled
        if not self.playback_started:
            outdata[:] = np.zeros((frames, 1))
            return
        
        # If paused, output silence (don't advance playback position)
        if self.paused:
            outdata[:] = np.zeros((frames, 1))
            self.current_amplitude = 0.0
            return
        
        # How fast to step through seismic data (at native 100 Hz rate)
        # playback_rate = 100 Hz / 44100 Hz = 0.00226757 seismic samples per audio sample
        playback_rate = self.seismic_sample_rate / self.audio_sample_rate
        
        buffer_len = len(self.seismic_buffer)
        
        # Generate audio samples by interpolating through seismic buffer
        audio_out = []
        raw_samples = []  # Store raw interpolated samples for visualization
        
        for i in range(frames):
            # Check if we have enough buffer ahead
            if self.playback_position >= buffer_len - 1:
                # Out of data - output silence and record underrun
                self.stats['underruns'] += 1
                if self.stats['underruns'] % 50 == 0:
                    print(f"[AUDIO UNDERRUN #{self.stats['underruns']}] Playback pos: {self.playback_position:.2f}, Buffer size: {buffer_len}")
                raw_sample = 0.0
            else:
                # Linear interpolation between current and next sample
                idx = int(self.playback_position)
                frac = self.playback_position - idx
                
                current_sample = self.seismic_buffer[idx]
                next_sample = self.seismic_buffer[min(idx + 1, buffer_len - 1)]
                
                interpolated = current_sample * (1 - frac) + next_sample * frac
                raw_sample = interpolated
                
                # Advance playback position
                self.playback_position += playback_rate
            
            # Apply low-pass smoothing filter (exponential moving average)
            # y[n] = alpha * x[n] + (1 - alpha) * y[n-1]
            self.smoothed_value = self.smoothing_alpha * raw_sample + (1 - self.smoothing_alpha) * self.smoothed_value
            
            # Store raw sample for visualization
            raw_samples.append(raw_sample)
            
            # Output smoothed version to audio
            audio_out.append(self.smoothed_value)
            
            # Store current amplitude for live monitoring (use smoothed for consistency)
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
        
        # Track seismic samples consumed (not audio samples!)
        seismic_samples_consumed = frames * playback_rate
        self.total_samples_consumed += seismic_samples_consumed
        
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
    
    def reset_stats(self):
        """Reset all statistics and buffers (but keep streaming)"""
        # Reset counters
        self.stats['packets_received'] = 0
        self.stats['underruns'] = 0
        self.total_samples_received = 0
        self.total_samples_consumed = 0
        self.playback_position = 0.0
        
        # Reset timing data
        self.packet_times = []
        self.first_packet_time = None
        self.last_packet_time = None
        
        # Clear buffers (but keep streaming active)
        self.seismic_buffer = []
        self.recent_data.clear()
        self.recent_data_raw_interpolated.clear()
        self.recent_data_smoothed.clear()
        self.smoothed_value = 0.0  # Reset smoothing filter state
        self.playback_started = False
        
        print("[RESET] All statistics and buffers cleared. Restarting from fresh state...")
    
    def stop_stream(self):
        """Stop the audio stream and close connection"""
        print("[STOP] Stopping audio stream and closing SeedLink connection...")
        
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
        stats['total_samples_consumed'] = audifier.total_samples_consumed
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

