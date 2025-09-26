# Runs the Assistant

# --- Standard Library ---
import json
import os
import sys
import re
import threading
import difflib
import time
import queue
import traceback
from datetime import datetime

# --- Log Output ---

class Logger:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()   # <-- flush after each write

    def flush(self):
        self.terminal.flush()
        self.log.flush()

os.makedirs("Log", exist_ok=True)

now = datetime.now()
clock = now.strftime('%H_%M_%S')
sys.stdout = sys.stderr = Logger(f"Log/output_{clock}.log")

# --- Third-Party Packages ---
import sounddevice as sd
from colorama import Back, Fore, init

# --- Setup the folder containing maincode.py ---
def main_folder():
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller exe
        return os.path.dirname(sys.executable)
    else:
        # Running as normal Python script
        return os.path.dirname(os.path.abspath(__file__))

# Prepend folder to sys.path BEFORE imports
_main_path = main_folder()
sys.path.insert(0, _main_path)

# --- DEBUG ---
print("Modules path:", _main_path)
print("Contents:", os.listdir(_main_path))

# --- Local Modules ---
from action_configuration import perform_action
from command_functions import print_list_grid, play_audio
from config_utils import get_config_entry, load_commands
from starter import (
    audio_device_info,
    callback,
    check_internet,
    cooldown_seconds,
    last_trigger_time,
    q,
    recognizer,
    remove_lock,
    speak,
)

# Intro



if __name__ == "__main__":
    print(f"Running from: {os.getcwd()}")
    print("Microphone devices:")
    print(sd.query_devices())
    print(f"Default device: {sd.default.device}")
    print(f"Current used input device: {audio_device_info("inputdevice")}")
    print(f"Current input sample rate: {audio_device_info("inputsamplerate")}")

# ANSI “clear‑screen” + “cursor‑home”

print("\033[2J\033[H", end="")

# Check and state network connectivity
# Offline mode can be forced via debug_menu/config.json

if check_internet():
    print("ONLINE MODE")
else:
    print("OFFLINE MODE !! THE MODE WILL SWITCH AUTOMATICALLY UPON INTERNET CONNECTIVITY")
    if get_config_entry("behavior", "forceofflinemode", default=False, value_type=bool):
        print("FORCED OFFLINE MODE!!")

# Startup Sound played by command_functions.play_audio, you may change/disable the message via debug_menu/config.json

if get_config_entry("launchreq", "playstartup", default=True, value_type=bool):
    play_audio(systemsound="startup", wait=True)

# Wellcome message said by pyttsx3, you may change/disable the message via debug_menu/config.json

if get_config_entry("launchreq", "dowelcome", default=True, value_type=bool):
    welcomemessage = get_config_entry("launchreq", "welcomemessage", default="Hello! I am at your service! call me if you need anything.")
    speak(welcomemessage)

# Print active commands on start. can be disabled via debug_menu/config.json

if get_config_entry("launchreq", "printcommands", default=True, value_type=bool):
    print("Active commands:")
    print_list_grid(list(load_commands().get("commands", {}).keys()))

# Setup Vosk recognizer and refresh on every interval. interval can be set/disabled via debug_menu/config.json

recognizer_en = None

def refresh_recognizer():
    global recognizer_en
    while True:
        recognizer_en = recognizer()
        refreshrate = get_config_entry("vosk", "refreshrate", default=10, value_type=int)
        time.sleep(refreshrate)

recognizer_en = recognizer()

# Start background thread
if get_config_entry("vosk", "refresh", default=True, value_type=bool):
    threading.Thread(target=refresh_recognizer, daemon=True).start()

# This is where commands are recognized and the respective section is addressed

def handle_commands():
    minwords = get_config_entry("vosk", "minwords", default=2, value_type=int)
    maxwords = get_config_entry("vosk", "maxwords", default=4, value_type=int)
    printinput = get_config_entry("vosk", "printinput", default=False, value_type=bool)
    printall = get_config_entry("vosk", "printall", default=False, value_type=bool)
    strictness = get_config_entry("vosk", "strictness", default=0.8, value_type=float)
    wake_word = get_config_entry("vosk", "wake_word", default="hey assistant", value_type=str)
    use_wake_word = get_config_entry("vosk", "use_wake_word", default=True, value_type=bool)
    wake_timeout = get_config_entry("vosk", "wake_timeout", default=6, value_type=int)
    disable_vosk = get_config_entry("vosk", "disablevosk", default=False, value_type=bool)

    commands_data = load_commands()
    commands_dict = commands_data.get("commands", {})
    sensitive_commands = commands_data.get("sensitive_commands", {})
    online_commands = commands_data.get("online_commands", {})
    notify_commands = commands_data.get("notify_commands", {})

    filler_words = {"um", "uh", "hmm", "okay", "like", "the", "that", "you know"}

    global last_trigger_time

    # --- Manual typing mode ---
    if disable_vosk:
        print("📝 Vosk disabled. Type your commands instead.")
        while True:
            text = input("> ").strip().lower()
            words = text.split()

            if (
                len(words) < minwords
                or len(words) > maxwords
                or text in filler_words
            ):
                print("Invalid Command!")
                continue

            if text in commands_dict:
                print(f"[Command] -> {text}")
                response = commands_dict[text]
                if response:
                    speak(response)

                perform_action(
                    text,
                    confirm_required=text in sensitive_commands,
                    network_required=text in online_commands,
                    notification_required=text in notify_commands
                )
                break
            else:
                print("Invalid Command!")
        return

    else:
        # --- Vosk mode ---
        if use_wake_word:
            print(f"🎤 Awaiting Wake Word... ({wake_word})")
            wake_active = False
        else:
            print("🎤 Awaiting voice command...")

        with sd.RawInputStream(
            device=audio_device_info("inputdevice"),
            samplerate=audio_device_info("inputsamplerate"),
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=callback
        ):
            while True:
                # --- Timeout check ---
                if use_wake_word and wake_active:
                    if time.time() - wake_start_time > wake_timeout:
                        play_audio(systemsound="click", wait=False)
                        print("⏲️ Wake word timeout, returning to sleep mode...")
                        wake_active = False
                        continue

                # Get the latest audio chunk only
                try:
                    data = q.get_nowait()
                    while not q.empty():  # keep discarding until last item
                        data = q.get_nowait()
                except queue.Empty:
                    continue

                if not recognizer_en.AcceptWaveform(data):
                    continue  # skip partials

                result = json.loads(recognizer_en.Result())
                text = re.sub(r"[^\w\s]", "", result.get("text", "").strip().lower())
                if not text:
                    continue

                if printall:
                    print(text)

                # --- Wake word check ---
                if use_wake_word and not wake_active:
                    if wake_word == text:  # strict match only
                        play_audio(systemsound="notification", wait=False)
                        print("Wake word detected, now listening for commands...")
                        wake_active = True
                        wake_start_time = time.time()
                    continue

                # --- Skip short/filler words ---
                words = text.split()
                if (
                    len(words) < minwords
                    or len(words) > maxwords
                    or all(w in filler_words for w in words)
                ):
                    continue

                if printinput:
                    print(text)

                # --- Fuzzy matching for commands only ---
                best_score, matched_command = max(
                    (
                        (difflib.SequenceMatcher(None, text, cmd).ratio(), cmd)
                        for cmd in commands_dict.keys()
                    ),
                    key=lambda x: x[0],
                    default=(0.0, None)
                )

                if matched_command and best_score >= strictness:
                    print(f"[Command] -> {matched_command} (score={best_score:.2f})")
                    response = commands_dict[matched_command]
                    if response:
                        speak(response)

                    perform_action(
                        matched_command,
                        confirm_required=matched_command in sensitive_commands,
                        network_required=matched_command in online_commands,
                        notification_required=matched_command in notify_commands
                    )

                    last_trigger_time = time.time()

                    # Clear audio queue efficiently
                    with q.mutex:
                        q.queue.clear()

                    if use_wake_word:
                        wake_active = False
                        break
                    break

# Try running the code

try:
    while True:
        handle_commands()
except KeyboardInterrupt:
    print("Interrupted by user.")
except Exception as e:
    print("Unexpected error occurred:")
    traceback.print_exc()
finally:

    # Shutdown message, can be changed/disabled via debug_menu/config.json

    if get_config_entry("launchreq", "dogoodby", default=True, value_type=bool):
        speak(get_config_entry("launchreq", "shutdownmessage", default="bye bye!", value_type=str))

    # Shutdown audio file, can be changed/disabled via debug_menu/config.json

    if get_config_entry("launchreq", "playshutdown", default=True, value_type=bool):
        play_audio(systemsound="shutdown", wait=True)
        
    remove_lock()
    print("Resources cleaned up.")
