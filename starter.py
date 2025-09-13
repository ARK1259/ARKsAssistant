# --- Standard Library ---
import atexit
import json
import os
import queue
import shutil
import socket
import sys
import threading
import time

# --- Third-Party Packages ---
import psutil
import pygame
import pyttsx3
import serial
import sounddevice as sd
from serial.tools import list_ports
from colorama import Fore, Back, init


try:
    base_path = sys._MEIPASS
except AttributeError:
    base_path = os.path.abspath(".")

vosk_dll_path = os.path.join(base_path, "_internal", "vosk")
os.environ["PATH"] = vosk_dll_path + os.pathsep + os.environ["PATH"]

from vosk import KaldiRecognizer, Model, SetLogLevel

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

# --- Local Modules ---
from config_utils import resource_path, get_config_path, load_commands, get_config_entry, load_config


# Set a lock to avoid duplicate launch

LOCKFILE = get_config_path("ARKsAssistant") / "assistant.lock"

# Check if lock file exists

def is_process_running(pid):
    return psutil.pid_exists(pid)

if os.path.exists(LOCKFILE):
    with open(LOCKFILE, 'r') as f:
        try:
            old_pid = int(f.read().strip())
            if is_process_running(old_pid):
                print("❌ Assistant is already running.")
                sys.exit()
        except ValueError:
            print("⚠️ Corrupted lock file. Proceeding.")

# Write current PID to lock file

with open(LOCKFILE, 'w') as f:
    f.write(str(os.getpid()))

# Register cleanup for program exit

@atexit.register
def remove_lock():
    if os.path.exists(LOCKFILE):
        os.remove(LOCKFILE)

# Get the terminal size for command_functions.print_list_grid() or else

cols = shutil.get_terminal_size(fallback=(80, 24)).columns

# Pygame setup

pygame.mixer.init()

# Audio queue

q = queue.Queue()
def callback(indata, frames, time_data, status):
    if status:
        print(status)
    q.put(bytes(indata))

# Get audio devices, input/output and their information
# Currently output device is constantly set to default system sound, thus changing it won't have any effects

def audio_device_info(key):
    default_input = sd.default.device[0]
    default_output = sd.default.device[1]
    if key == "inputdevice":
        return get_config_entry("audio", "inputdevice", default=default_input, value_type=int)
    elif key == "outputdevice":
        return get_config_entry("audio", "outputdevice", default=default_output, value_type=int)
    elif key == "inputsamplerate":
        return get_config_entry("audio", "inputsamplerate", default=16000, value_type=int)
    else:
        print (f"An error has accured: The {key} was not found!")


# Check internet connectivity function

def check_internet(host="8.8.8.8", port=53, timeout=3):
    if get_config_entry("behavior", "forceofflinemode", default=False, value_type=bool):
        return False
    else:
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except Exception:
            return False

# Background thread to monitor connection

def monitor_connection(interval=5):
    silent = get_config_entry("behavior", "arduino", default=False, value_type=bool)
    previous_status = None

    while True:
        current_status = check_internet()

        if current_status != previous_status:
            HAS_INTERNET = current_status
            if HAS_INTERNET:
                if not silent:
                    print("[Connection Status] ✅ Internet connection available.")
            else:
                if not silent:
                    print("[Connection Status] ❌ Internet connection lost.")
            previous_status = current_status
            HAS_INTERNET = current_status

        time.sleep(interval)

threading.Thread(target=monitor_connection, daemon=True).start()

# Your online SAPI5 Natural Voice Adaptor voice function

def speak_online(text):
    voiceid = get_config_entry("voices", "onlinevoice", default=5, value_type=int)
    print(f"[Online Assistant] -> {text}")
    for voice in voices:
        # This will allow the voice to default to 0 if voice 5 is not found
        if "aria" in voice.name.lower():
            tts_engine.setProperty('voice', voices[int(voiceid)].id)
            break

# Offline speak function using pyttsx3

def speak_offline(text):
    voiceid = get_config_entry("voices", "offlinevoice", default=1, value_type=int)
    print(f"[Offline Assisant] -> {text}")
    for voice in voices:
        # This will allow the voice to default to 0 if voice 1 is not found
        if "aria" in voice.name.lower():
            tts_engine.setProperty('voice', voices[int(voiceid)].id)
            break

# Unified speak function switching dynamically

def speak(text):
    global voices
    global tts_engine

    if get_config_entry("behavior", "arduino", default=False, value_type=bool):
        arduino.write(b"LINE1:Assistant: ")
        time.sleep(1)
        arduino.write(f"LINE2:{text}".encode())

    dontspeak = get_config_entry("voices", "dontspeak", default=False, value_type=bool)
    if dontspeak:
        print(f"[Text Only] {text}")
        return

    offlinevoice = get_config_entry("voices", "constantofflinevoice", default=False, value_type=bool)
    speedrate = get_config_entry("voices", "speedrate", default=170, value_type=int)
    volumelevel = get_config_entry("voices", "volumelevel", default=1, value_type=float)

    tts_engine = pyttsx3.init()
    voices = tts_engine.getProperty('voices')
    tts_engine.setProperty('rate', speedrate)
    tts_engine.setProperty('volume', volumelevel)

    if not offlinevoice:
        if check_internet():
            speak_online(text)
        else:
            speak_offline(text)
    else:
        speak_offline(text)

    tts_engine.say(text)
    tts_engine.runAndWait()
    tts_engine.stop()

# Setup Arduino connection

arduino = None

if get_config_entry("behavior", "arduino", default=False, value_type=bool):

    def get_arduino(baud=9600, timeout=1):
        # Try to get from config
        confport = get_config_entry("behavior", "arduinoport", default=None, value_type=str)
        print(confport)
        
        # If no configured port, try to auto-detect
        if confport:
            ports = [confport]
        else:
            ports = [p.device for p in list_ports.comports()]

        # Try each port until one works
        for port in ports:
            try:
                arduino = serial.Serial(port, baud, timeout=timeout)
                time.sleep(2)  # let Arduino reset
                return arduino
            except serial.SerialException as e:
                print(f"[!] Could not connect on {port}: {e}")
                continue

        # Nothing worked
        print("[!] No Arduino found")
        return None
    
    arduino = get_arduino()
        
# Values from 1 to 100 for whereever that needs them

volume_numbers = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred"
    ]

# All the phrases/words required for Vosk vocabulary will be listed here

def get_phrases():
    all_english_commands = (
    list(load_commands().get("commands", {}))
    + list(volume_numbers)
    + list(
        get_config_entry(
        "crypto_names", key=None,
        default=["bitcoin", "ethereum", "dogecoin", "solana", "litecoin", "cardano", "tron", "ripple"],
        value_type=list
    ))
    + [get_config_entry("behavior", "confirm", default="confirm", value_type=str)]
    + [get_config_entry("behavior", "decline", default="decline", value_type=str)]
    + [get_config_entry("vosk", "wake_word", default="hey computer", value_type=str)]
    + list(
        get_config_entry(
        "city_names", key=None,
        default=["tokyo", "london", "chicago", "istanbul", "tehran"],
        value_type=list
    ))
    + list(load_config().get("applications",{}))
    )
    return [word for word in all_english_commands if all(ord(c) < 128 for c in word)]
   
# Vosk Log level, -1, 0 , 1 , 2 , are accepted, -1 is nothing is printed, 0 only errors, 1 more things "idk", 2 everything
# This only works on some systems, it is not working all the time.

loglevel = get_config_entry("vosk", "loglevel", default=-1, value_type=int)
SetLogLevel(loglevel)

# Loading vosk recognizer

_last_phrases = []
model_en_path = get_config_entry("vosk", "vosk-en", default=resource_path("models/vosken1"), value_type=str)
model_en = Model(model_en_path)

def recognizer(printphrases=False, command=True):
    global _last_phrases

    current_phrases = get_phrases()
    if not current_phrases:
        current_phrases = []

    if current_phrases != _last_phrases:
        _last_phrases = list(current_phrases)

    if not printphrases:
        dictionary = get_config_entry("vosk", "dictionary", default=True, value_type=bool)
        if dictionary or command is False:
            return KaldiRecognizer(model_en, audio_device_info("inputsamplerate"), json.dumps(_last_phrases))
        else:
            return KaldiRecognizer(model_en, audio_device_info("inputsamplerate"))
    else:
        return _last_phrases

# Setting values for command handeling in repetition

cooldown_seconds = get_config_entry("behavior", "command_cooldown", default=0.5, value_type=float)
last_trigger_time = 0