# Read and Write configurations

# --- Standard Library ---
import os
import sys
import json
import platform
from pathlib import Path

def resource_path(relative_path):
    """
    Returns the absolute path to a resource file.
    Works both for normal Python scripts and PyInstaller executables,
    always pointing to the folder containing the exe/script.
    """
    if getattr(sys, "frozen", False):
        # Running as PyInstaller exe
        base_path = os.path.dirname(sys.executable)
    else:
        # Running as normal Python script
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)

def get_config_path(app_name="ARKsAssistant"):
    system = platform.system()

    if system == "Windows":
        base_dir = os.getenv("LOCALAPPDATA")
        config_path = Path(base_dir) / app_name
    elif system == "Darwin":  # macOS
        config_path = Path.home() / "Library" / "Application Support" / app_name
    else:  # Linux and others
        config_path = Path.home() / ".config" / app_name

    config_path.mkdir(parents=True, exist_ok=True)
    return config_path

config_dir = get_config_path("ARKsAssistant")
config_file = os.path.join(config_dir, "config.json")

def save_config(data):
    with open(config_file, "w") as f:
        json.dump(data, f, indent=4)

def load_config():
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return json.load(f)
    return {}

def load_commands():
    commands_file = resource_path("commands.json")
    with open(commands_file, "r") as f:
        return json.load(f)
    
def get_config_entry(section: str, key: str = None, default=None, value_type=str):
    config = load_config()

    value = config.get(section) if key is None else config.get(section, {}).get(key)

    if value is None or (isinstance(value, str) and not value.strip()):
        return default

    try:
        if value_type == bool:
            if isinstance(value, bool):
                return value
            value_lower = str(value).strip().lower()
            if value_lower in ("true", "yes", "1"):
                return True
            elif value_lower in ("false", "no", "0"):
                return False
            else:
                return default

        elif value_type == list:
            return value if isinstance(value, list) and value else default

        return value_type(value)

    except (ValueError, TypeError):
        return default