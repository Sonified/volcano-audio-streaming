# This file makes the python_code directory a Python package
__version__ = "1.09"
__commit_message__ = (
    "v1.09 Refactor: Migrated SeedLink from threads to KILLABLE subprocesses - clean shutdown with no reconnection spam, unbuffered real-time logging, SIGTERM/SIGKILL termination, subprocess architecture for both local and Render backends"
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
