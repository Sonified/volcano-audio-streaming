# This file makes the python_code directory a Python package
__version__ = "1.15"
__commit_message__ = (
    "v1.15 Fix: Loop/finish fades (separate gain stage + early fade-out) - created separate liveAmplitudeGain stage to prevent Live Amplitude from canceling loop fades, fixed playback speed race condition by setting speed before sending data to worklet, fixed fade-out clicks by using loop-soon warning to start fade early while audio still playing, added speed-adjusted fade duration that scales inversely with playback speed, comprehensive fade logging for debugging, adjusted Gain control spacing"
)

# Import key modules to make them available when importing the package
from python_code.main import main
from python_code.audio_utils import create_audio_file, generate_marker_file
from python_code.seismic_utils import compute_time_window, fetch_seismic_data
from python_code.plot_utils import create_seismic_plot
from python_code.marker_utils import generate_marker_file
from python_code.print_manager import print_manager
from python_code.ui_utils import (
    create_directory_button,
    create_audio_open_button,
    create_marker_file_button,
    create_plot_file_button,
    create_buttons_from_results,
    display_marker_file_contents,
    print_results_summary
)
