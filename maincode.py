"""
Runs the Assistant
"""

# --- Standard Library ---
import json
import os
import sys
import re
import threading
import pathlib
import platform
import shutil
import psutil
import time
import queue
import traceback
import ctypes

# --- Third-Party Packages ---
import sounddevice as sd
    
# --- Log Output ---
class Logger:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()  # flush after each write

    def flush(self):
        self.terminal.flush()
        self.log.flush()

# --- First Run Check ---

# set config folder
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

# Check if file exists
def is_process_running(pid):
    return psutil.pid_exists(pid)

# --- Save root folder ---
APP_ROOT = pathlib.Path(sys.argv[0]).resolve().parent
os.environ["ARKS_ASSISTANT_ROOT"] = str(APP_ROOT)

# --- Setup config paths ---
config_dir = pathlib.Path(get_config_path("ARKsAssistant"))
config_file = config_dir / "config.json"

def load_config():
    if config_file.exists():
        with config_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}

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

# --- Inject modules path ---
modules_path = get_modules_path()
modules_path_str = str(modules_path)

if modules_path_str not in sys.path:
    sys.path.insert(0, modules_path_str)

# --- Enable ANSI escape code support ---
def enable_ansi_support():
    if os.name == 'nt':  # Windows only
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE = -11
        mode = ctypes.c_uint32()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(handle, mode)
        
enable_ansi_support()

# --- Copy Modules to Locals if needed ---

APP_ROOT = pathlib.Path(APP_ROOT)

modules_path = pathlib.Path(modules_path)

modules_path.mkdir(parents=True, exist_ok=True)

FILES_TO_COPY = {
    "starter.py",
    "config_utils.py",
    "functions.py",
    "action_configuration.py",
    "comprehension.py",
    "config.json",
    "Langs",
    "Commands",
    "Actions",
}

missing_files = []

# Check what’s missing
for filename in FILES_TO_COPY:
    dst = modules_path / filename
    if not dst.exists():
        missing_files.append(filename)

# First launch OR incomplete setup
def init_copy():
    if not config_file.exists():
        print("❌ First Launch. Copy Required!")
        files_to_process = FILES_TO_COPY

    elif missing_files:
        print(f"⚠️ Some modules are missing from {modules_path}:")
        for f in missing_files:
            print(f"   - {f}")

        user_input = input("Do you want to copy missing modules? (y/n): ").lower()

        if user_input != 'y':
            print("❌ Skipping copy.")
            print("❌ The assistant is unable to run without its modules!")
            sys.exit()

        files_to_process = missing_files
    else:
        return

    # Copy logic
    for filename in files_to_process:
        src = APP_ROOT / filename
        dst = modules_path / filename

        if not src.exists():
            print(f"⚠️ Skipped (not found): {filename}")
            continue

        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

        print(f"✅ Copied: {filename}")

if not config_file.exists() or missing_files:
    try:
        init_copy()
    except Exception as e:
        print(t.t("error.unexpected", e=e))

# --- Local Modules ---
from starter import (
    audio_device_info,
    callback,
    check_internet,
    recognizer,
    remove_lock,
    speak,
    read_command_server,
    get_terminal_input,
    is_private,
    t,
    q,
)
from action_configuration import (
    perform_action,
)
from functions import (
    play_audio,
    load_timers_from_config,
)
from config_utils import (
    get_config_entry,
    load_config,
)
from comprehension import (
    parse_command,
)

# Intro

if __name__ == "__main__":
    if not is_private():
        print(f"Running from: {os.getcwd()}")
        print("Microphone devices:")
        print(sd.query_devices())
        print(f"Default device: {sd.default.device}")
        print(f"Current used input device: {audio_device_info("input_device")}")
        print(f"Current input sample rate: {audio_device_info("input_sample_rate")}")

# Loading Timers

load_timers_from_config()

# Setup Vosk recognizer and refresh on every interval. interval can be set/disabled via debug_menu/config.json

if not get_config_entry("vosk", "disable_vosk", default=False, value_type=bool):
    recognizer_en = None

    def refresh_recognizer():
        global recognizer_en
        while True:
            recognizer_en = recognizer()
            refreshrate = get_config_entry("vosk", "refresh_rate", default=60, value_type=int)
            time.sleep(refreshrate)
    recognizer_en = recognizer()

    # Start background thread
    if get_config_entry("vosk", "refresh", default=False, value_type=bool):
        threading.Thread(target=refresh_recognizer, daemon=True).start()

# ANSI “clear‑screen” + “cursor‑home”

print("\033[2J\033[H", end="")

# Check and state network connectivity
# Offline mode can be forced via debug_menu/config.json

if check_internet():
    print(t.t("prompts.online"))
else:
    print(t.t("prompts.offline"))
    if get_config_entry("behavior", "force_offline", default=False, value_type=bool):
        print(t.t("prompts.offline_forced"))
        
# Startup Sound played by command_functions.play_audio, you may change/disable the message via debug_menu/config.json

if get_config_entry("startup", "startup_sound", default=True, value_type=bool):
    play_audio(systemsound="startup", wait=True)
    
# Welcome message said by pyttsx3, you may change/disable the message via debug_menu/config.json

if get_config_entry("startup", "welcome", default=True, value_type=bool):
    welcomemessage = get_config_entry("startup", "welcome_message", default=t.t("defaults.welcome_message"))
    speak(welcomemessage)

# Handle_Input is counted as the core of ARKsAssistant and is where voice commands are turned into text before being registered
# at comprehension and sent to action_configuration

wake_last_time = 0

def handle_input():
    printall = get_config_entry("vosk", "print_input", default=False, value_type=bool)
    disable_vosk = get_config_entry("vosk", "disable_vosk", default=False, value_type=bool)
    wake_word = get_config_entry("comprehension", "wake_word", default=t.t("defaults.wake_word"), value_type=str)
    use_wake_word = get_config_entry("comprehension", "use_wake_word", default=True, value_type=bool)
    wake_timeout = get_config_entry("comprehension", "wake_timeout", default=10, value_type=int)
    wake_notification = get_config_entry("comprehension", "wake_notification", default=True, value_type=bool)
    use_server = get_config_entry("server", "open_tcp", default=False, value_type=bool)

    config = load_config()
    if "system" not in config or not isinstance(config["system"], dict):
        config["system"] = {}

    global wake_last_time

    # --- Manual typing mode ---
    if disable_vosk:
        print(t.t("report.vosk_disabled"))
        while True:
            text = None

            # Check TCP first
            if use_server:
                text = read_command_server()

            # Check terminal input
            if not text:
                text = get_terminal_input()

            if text:
                command = parse_command(text, True)

                if command and command.get("intent", {}):
                    attr = command.get("attributes")

                    prompt = attr.get("prompt")

                    intent = command["intent"]
                    print(t.t("prompts.command", text=intent))

                    keyword = command["keyword"]
                    if keyword == "core" and "reboot_controls" in command["entities"]:
                        return "RESTART"

                    if prompt:
                        speak(prompt)

                    perform_action(
                        command
                    )

                    break
                else:
                    print(t.t("error.invalid_command"))

            time.sleep(0.05)  # small sleep to avoid busy loop
        return
    
    # --- Vosk mode ---
    else:
        wait_printed = False
        normal_printed = False
        sound_played = None
        activated = None
        tcp = None

        with sd.RawInputStream(
            device=audio_device_info("input_device"),
            samplerate=audio_device_info("input_sample_rate"),
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=callback
        ):
            while True:
                now = time.time()

                # I have no clue what this is, but it was easy to figure out when I made it! good luck.
                if not wait_printed:
                    if not tcp or tcp is False:
                        if use_wake_word:
                            if (now - wake_last_time) > wake_timeout:
                                if wake_notification:
                                    play_audio(systemsound="deactivate", wait=False, volume=0.4)
                                    sound_played = False
                                print(t.t("report.wait_wake", wake_word=wake_word))
                                wait_printed = True
                                activated = False
                            elif not normal_printed:
                                if wake_notification:
                                    if sound_played is False and activated is True:
                                        play_audio(systemsound="activate", wait=False, volume=0.4)
                                        sound_played = True
                                print(t.t("prompts.wait_wake"))
                                normal_printed = True
                                activated = True
                        else:
                            print(t.t("prompts.wait_wake"))
                            wait_printed = True

                # Get the latest audio chunk only
                try:
                    data = q.get(timeout=0.1)
                    while not q.empty():  # keep discarding until last item
                        data = q.get_nowait()
                except queue.Empty:
                    continue

                # Feed recognizer
                try:
                    if not recognizer_en.AcceptWaveform(data):
                        recognizer_en.PartialResult()
                        # This is a partial result most of the time. You can check
                        # recognizer_en.PartialResult() here if you want.
                        # Don't spam prints here.
                        continue
                except:
                    recognizer_en = recognizer()
                    if not recognizer_en.AcceptWaveform(data):
                        continue
                
                tcp = False
                if use_server:
                    text = read_command_server()
                    if text and text != "":
                        tcp = True
                else:
                    text = None

                if not text or text=="" and not tcp:
                    result = json.loads(recognizer_en.Result())
                    text_raw = result.get("text", "").strip().lower()
                    text = re.sub(r"[^\w\s]", "", text_raw)

                if tcp is True:
                    command = parse_command(text, tcp = True)
                else:
                    command = parse_command(text, activated)

                if printall and text != "":
                    print(text)

                if not command:
                    continue

                if command.get("activated", {}) and use_wake_word:
                    if not tcp or tcp is False:
                        wake_last_time = time.time()
                        normal_printed = False
                        wait_printed = False
                        sound_played = False
                        activated = True
                    if not command.get("intent", {}):
                        continue
                
                if command and command.get("intent", {}):
                    if wake_notification and use_wake_word:
                        if sound_played is False and activated is True and tcp is False:
                            play_audio(systemsound="activate", wait=False, volume=0.4)
                    
                    if use_wake_word:
                        if activated is False:
                            if not tcp or tcp is False:
                                continue

                    if not tcp or tcp is False:
                        wait_printed = False
                    
                    if command:
                        attr = command.get("attributes")        

                        prompt = attr.get("prompt")
                        
                        intent = command["intent"]
                        print(t.t("prompts.command", text=intent))

                        keyword = command["keyword"]
                        if keyword == "core" and "reboot_controls" in command["entities"]:
                            return "RESTART"

                        if prompt:
                            speak(prompt)
                            
                        perform_action(
                            command
                        )

                        if use_wake_word:
                            if not tcp or tcp is False:
                                wake_last_time = time.time()

                        # Clear audio queue efficiently
                        with q.mutex:
                            q.queue.clear()

                        break

# Try running the core

try:
    while True:
        state = handle_input()
        if state == "RESTART":
            play_audio(systemsound="notification", wait=False)
            print(t.t("report.core_restarted"))
            continue
except KeyboardInterrupt:
    print(t.t("error.interrupted"))
except Exception as e:
    print(t.t("error.unexpected", e=e))
    traceback.print_exc()
finally:

    # Shutdown message, can be changed/disabled via debug_menu/config.json

    if get_config_entry("shutdown", "good_bye", default=True, value_type=bool):
        speak(get_config_entry("shutdown", "good_bye_message", default=t.t("defaults.good_bye_message"), value_type=str))

    # Shutdown audio file, can be changed/disabled via debug_menu/config.json

    if get_config_entry("shutdown", "shutdown_sound", default=True, value_type=bool):
        play_audio(systemsound="shutdown", wait=True)
        
    remove_lock()
    print(t.t("report.cleanup"))
