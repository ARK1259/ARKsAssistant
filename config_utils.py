"""
Read and Write jsons
These function may be used many times in the code
Having them as their own seperate module will reduce repeatition
"""

# --- Standard Library ---
import os
import sys
import json
import platform
import pathlib

def resource_path(relative_path):
    """
    Returns the absolute path to a resource file.
    Works both for normal Python scripts and PyInstaller executables,
    always pointing to the folder containing the exe/script.
    """
    APP_ROOT = os.getenv("ARKS_ASSISTANT_ROOT", os.getcwd())
    if getattr(sys, "frozen", False):
        # Running as PyInstaller exe
        base_path = os.path.dirname(sys.executable)
    else:
        # Running as normal Python script
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    if APP_ROOT:
        return os.path.join(APP_ROOT, relative_path)
    else:
        return os.path.join(base_path, relative_path)

def get_config_path(app_name="ARKsAssistant"):
    system = platform.system()

    if system == "Windows":
        base_dir = os.getenv("LOCALAPPDATA")
        config_path = pathlib.Path(base_dir) / app_name
    elif system == "Darwin":  # macOS
        config_path = pathlib.Path.home() / "Library" / "Application Support" / app_name
    else:  # Linux and others
        config_path = pathlib.Path.home() / ".config" / app_name

    config_path.mkdir(parents=True, exist_ok=True)
    return config_path

APP_ROOT = pathlib.Path(sys.argv[0]).resolve().parent
config_dir = get_config_path("ARKsAssistant")
config_file = os.path.join(config_dir, "config.json")

temp_config = None
temp_commands = None
temp_langs = None

def temp_json(value=None, name=None):
    global temp_config, temp_commands, temp_langs

    if not name:
        return
    
    if value:
        if name == "config":
            temp_config = value
        elif name == "commands":
            temp_commands = value
        elif name == "langs":
            temp_langs = value
    else:
        print("USING TEMP!")
        if name == "config":
            return temp_config
        elif name == "commands":
            return temp_commands
        elif name == "langs":
            return temp_langs

def save_config(data):
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_config():
    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            try:
                value = json.load(f)
                if value != temp_config:
                    temp_json(value, "config")
            except Exception as e:
                print(f"FAILED CONFIG JSON: {e}")
                return temp_json(name="config")
            return value
    return {}

def get_config_entry(section: str, key: str = None, default=None, value_type=str, values_only=False):
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
            if isinstance(value, list):
                return value if value else default
            elif isinstance(value, dict):
                # only return values if explicitly requested
                return list(value.values()) if values_only else list(value.keys())
            return default

        elif value_type == dict and values_only:
            # return dict values if user explicitly wants them
            return list(value.values()) if isinstance(value, dict) else default

        return value_type(value)

    except (ValueError, TypeError):
        return default
    
def get_modules_path():
    system_cfg = load_config().get("system", {})

    modules_path = system_cfg.get("modules_path")
    force_local = system_cfg.get("force_local_modules", False)

    # Normalize force_local to bool
    if isinstance(force_local, str):
        force_local = force_local.lower() == "true"

    if force_local:
        return APP_ROOT

    if not modules_path:
        return config_dir

    modules_path = pathlib.Path(modules_path).expanduser().resolve()

    starter_file = modules_path / "starter.py"
    if not starter_file.exists():
        return config_dir

    return modules_path

modules_path = get_modules_path() 
commands_dir = modules_path / "Commands"
langs_dir = modules_path / "Langs"

def load_commands(lang):
    path = get_config_entry("system", "custom_commands_file", default=None, value_type=str)
    
    if path and os.path.exists(path):
        commands_file = path
    else:
        commands_file = os.path.join(commands_dir, f"{lang}.json")
        if not os.path.exists(commands_file):
            # fallback to English
            commands_file = os.path.join(commands_dir, "en.json")

    # Open safely
    with open(commands_file, "r", encoding="utf-8") as f:
        try:
            value = json.load(f)
            if value != temp_commands:
                temp_json(value, "commands")
        except Exception as e:
            print(f"FAILED COMMANDS JSON: {e}")
            return temp_json(name="commands")
        return value
    
def load_langs(lang):
    path = get_config_entry("system", "custom_langs_file", default=None, value_type=str)
    
    if path and os.path.exists(path):
        langs_file = path
    else:
        langs_file = os.path.join(langs_dir, f"{lang}.json")
        if not os.path.exists(langs_file):
            # fallback to English
            langs_file = os.path.join(langs_dir, "en.json")
            
    with open(langs_file, "r", encoding="utf-8") as f:
        try:
            value = json.load(f)
            if value != temp_commands:
                temp_json(value, "langs")
        except Exception as e:
            print(f"FAILED LANGS JSON: {e}")
            return temp_json(name="langs")
        return value
    
