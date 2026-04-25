"""
Run the Streamlit dashboard.

Usage:
    python -m src.dashboard.app
"""
import subprocess
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

if __name__ == "__main__":
    # Run streamlit app
    app_path = src_path / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])