"""
Holds the functions that would run into issues if they were to run from Maincode
"""

# --- Standard Library ---
import atexit
import json
import os
import queue
import re
import string
import socket
import pathlib
import msvcrt
import builtins
import sys
import threading
import time
import warnings
from tkinter import Tk, filedialog
from queue import Queue, Empty
from datetime import datetime

# --- Third-Party Packages ---
import psutil

#...
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API.*",
    category=UserWarning
)
import pygame
#...

import pyttsx3
import serial
import sounddevice as sd
from serial.tools import list_ports

#...
try:
    base_path = sys._MEIPASS
except AttributeError:
    base_path = os.path.abspath(".")
vosk_dll_path = os.path.join(base_path, "_internal", "vosk")
os.environ["PATH"] = vosk_dll_path + os.pathsep + os.environ["PATH"]

from vosk import KaldiRecognizer, Model, SetLogLevel
#...

# --- Local Modules ---
from config_utils import (
    resource_path,
    get_config_path,
    load_langs,
    load_commands,
    get_config_entry,
    load_config,
    save_config,
    get_modules_path,
)

# Setup STDOUT and TCP

client_connections = []
client_lock = threading.Lock()

class TCPLogger:
    """
    Logger that mirrors print output to stdout and TCP clients.
    Handles ongoing get_terminal_input line correctly.
    Supports multi-argument prints and dynamic functions like print_list_grid.
    """
    def __init__(self, prefix=""):
        self.prefix = prefix

    def log(self, *args, sep=" ", end="\n", file=None, flush=True):
        global terminal_buffer, _prompt_shown

        if file is None:
            file = sys.stdout

        # Combine all args like print does
        text = sep.join(str(a) for a in args)

        # --- If user is typing, temporarily erase current line ---
        if _prompt_shown and terminal_buffer:
            file.write("\r" + " " * (len(terminal_buffer) + 2) + "\r")

        # 1) Output to console
        file.write(self.prefix + text + end)
        if flush:
            file.flush()

        # 2) Send to all TCP clients
        TCPSender.send_line(self.prefix + text)

        # 3) Repaint prompt and buffer if user is typing
        if _prompt_shown and terminal_buffer:
            file.write("> " + terminal_buffer)
            file.flush()

class TCPStdout:
    def __init__(self):
        self._buffer = ""

    def write(self, s):
        # Always write to real console
        sys.__stdout__.write(s)

        # Buffer until newline for TCP
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            TCPSender.send_line(line)

    def flush(self):
        sys.__stdout__.flush()

class TCPSender:
    """
    Sends text lines to all connected TCP clients.
    """
    @staticmethod
    def send_line(message: str):
        data = (message + "\n").encode("utf-8")
        with client_lock:
            dead = []
            for conn in client_connections:
                try:
                    conn.sendall(data)
                except Exception as e:
                    # if sending fails, mark this conn as dead
                    sys.__stdout__.write(t.t("error.server_response", e=e))
                    dead.append(conn)

            for dc in dead:
                try:
                    dc.close()
                except:
                    pass
                if dc in client_connections:
                    client_connections.remove(dc)

class CombinedStdout:
    def __init__(self, logfile):
        self.console = sys.__stdout__
        self.log = open(logfile, "a", encoding="utf-8")
        self._buffer = ""

    def write(self, s):
        # Console
        self.console.write(s)

        # File
        self.log.write(s)
        self.log.flush()

        # TCP (line-buffered)
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            TCPSender.send_line(line)

    def flush(self):
        self.console.flush()
        self.log.flush()

# Set Print Privacy Function

def is_private():
    private = get_config_entry("system", "private_mode", default=False, value_type=bool)
    if private is False:
        return False
    else:
        return True

# Ensure path string is absolute and normalized
config_path_str = os.path.abspath(get_config_path("ARKsAssistant"))
if config_path_str not in sys.path:
    sys.path.insert(0, config_path_str)

# --- Initiate Logging ---
clock = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')

# Create Log folder inside config_dir
log_dir = os.path.join(config_path_str, "Log")
os.makedirs(log_dir, exist_ok=True)

# Delete logs older than the keep_time set in config.json or default of 7 days
log_age = get_config_entry("system", "keep_logs_days", default=7, value_type=int)
HOLD_DURATION = log_age * 24 * 60 * 60  # seconds
now = time.time()

for filename in os.listdir(log_dir):
    file_path = os.path.join(log_dir, filename)

    if not os.path.isfile(file_path):
        continue

    try:
        file_age = now - os.path.getmtime(file_path)
        if file_age > HOLD_DURATION:
            os.remove(file_path)
    except OSError:
        pass  # ignore files that can't be accessed/deleted

# Create timestamped log file
log_file = os.path.join(log_dir, f"output_{clock}.log")

sys.stdout = sys.stderr = CombinedStdout(log_file)

# --- DEBUG ---
if not is_private():
    print("Root path:", pathlib.Path(sys.argv[0]).resolve().parent)
    print("Modules path:", get_modules_path())
    print("Contents:", os.listdir(get_modules_path()))

    # --- Setup Modules path as System ---

    print("---- sys.path ----")
    for p in sys.path:
        print(p)
    print("------------------")


    print("Final import paths:")
    for p in sys.path:
        print("  ", p)

# --- Setting up Translator ---
class Translator:
    def __init__(self, lang="en", lang_dir="langs"):
        self.lang_dir = lang_dir
        self.set_language(lang)

    def set_language(self, lang):
        self.data = load_langs(lang)

    def t(self, key, **kwargs):
        """Translate a key with optional formatting arguments."""
        parts = key.split(".")
        value = load_langs(lang)
        try:
            for p in parts:
                value = value[p]
        except KeyError:
            return key  # fallback: return key name if missing

        # If it's a string, format it. Otherwise, just return it.
        if isinstance(value, str):
            return value.format(**kwargs)
        else:
            return value
    def get_list(self, list_name):
        """
        Return dictionary of translated names for a given list, e.g. 'cryptos' or 'cities'.
        Example: translator.get_list("cryptos")
        """
        return self.data.get("defaults", {}).get(list_name, {})

# --- Setting up the language file ---
def set_language():
    config = load_config()

    # Locate lang folder relative to this file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    lang_dir = os.path.join(base_dir, "Langs")
    commands_dir = os.path.join(base_dir, "Commands")

    if not os.path.isdir(lang_dir):
        print("❌ Language folder not found.")
        return None
    if not os.path.isdir(commands_dir):
        print("❌ Commands folder not found.")
        return None

    # Collect language files
    langs = []
    for file in os.listdir(lang_dir):
        if file.endswith(".json"):
            code = file[:-5]  # remove .json
            # Only include if corresponding command file exists
            command_file = os.path.join(commands_dir, f"{code}.json")
            if os.path.isfile(command_file):
                langs.append(code)

    if not langs:
        print("❌ No language files found.")
        return None

    # Try to read display names from JSON
    lang_display = {}

    for code in langs:
        try:
            with open(os.path.join(lang_dir, f"{code}.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
                lang_display[code] = data.get("language", code)
        except Exception:
            lang_display[code] = code

    # Ask user
    while True:
        print("Available languages:")
        # Sort by display name
        sorted_codes = sorted(langs, key=lambda c: lang_display[c].lower())
        for i, code in enumerate(sorted_codes, 1):
            print(f"{i}. {lang_display[code]} ({code.upper()})")

        choice = input("Choose your language: ").strip().lower()

        # Numeric choice
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sorted_codes):
                lang = sorted_codes[idx]
                break

        # Code choice (en / fa / etc.)
        if choice in langs:
            lang = choice
            break

        print("❌ Wrong input")

    # Save config
    config.setdefault("system", {})
    config["system"]["language"] = lang
    save_config(config)

    print(f"Your language has been set to: {lang_display.get(lang, lang)} ({lang})")
    return lang

saved_lang = get_config_entry("system", "language", default=None, value_type=str)
if not saved_lang:
    lang = set_language()
    t = Translator(lang)
else:
    lang = saved_lang
    t = Translator(lang)

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
                print(t.t("error.already_running"))
                sys.exit()
        except ValueError:
            print(t.t("error.broken_lock"))

# Write current PID to lock file

with open(LOCKFILE, 'w') as f:
    f.write(str(os.getpid()))

# Register cleanup for program exit

@atexit.register
def remove_lock():
    if os.path.exists(LOCKFILE):
        os.remove(LOCKFILE)

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
    if key == "input_device":
        return get_config_entry("sound_devices", "input_device", default=default_input, value_type=int)
    elif key == "output_device":
        return get_config_entry("sound_devices", "output_device", default=default_output, value_type=int)
    elif key == "input_sample_rate":
        return get_config_entry("sound_devices", "input_sample_rate", default=16000, value_type=int)
    else:
        print(t.t("error.get_audio_device", key=key))

# Check internet connectivity function

def check_internet(host="8.8.8.8", port=53, timeout=3):
    if get_config_entry("behavior", "force_offline", default=False, value_type=bool):
        return False
    else:
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except Exception:
            return False

# Background thread to monitor internet connection

def monitor_connection(interval=5):
    print_status = get_config_entry("behavior", "print_internet_connectivity", default=True, value_type=bool)
    previous_status = None
    
    while True:
        current_status = check_internet()

        if current_status != previous_status:
            HAS_INTERNET = current_status
            if HAS_INTERNET:
                if print_status:
                    print(t.t("report.internet_connected"))
            else:
                if print_status:
                    print(t.t("report.internet_disconnected"))
            previous_status = current_status
            HAS_INTERNET = current_status

        time.sleep(interval)

threading.Thread(target=monitor_connection, daemon=True).start()

# Setup Arduino connection

arduino = None
arduino_lock = threading.Lock()

_cached_ports = []
_last_port_scan = 0

def list_ports_cached(refresh_interval=5):
    global _cached_ports, _last_port_scan
    now = time.time()
    if now - _last_port_scan > refresh_interval:
        _cached_ports = [p.device for p in list_ports.comports()]
        _last_port_scan = now
    return _cached_ports

_arduino_last_print = {
    "port_trying": None,
    "port_error": None,
    "port_connected": None,
    "port_missing": None,
    "not_found": None,
    "not_set_up": None,
    "reconnect_failed": None,
    "close_error": None,
}

def print_once(key, msg):
    """
    Print a message only if it differs from the last message for this key.
    """
    global _arduino_last_print
    if _arduino_last_print.get(key) != msg:
        print(msg)
        _arduino_last_print[key] = msg

def reset_arduino_print_state():
    global _arduino_last_print
    for key in _arduino_last_print:
        _arduino_last_print[key] = None

def set_arduino(conn):
    global arduino
    with arduino_lock:
        arduino = conn

def arduino_is_alive(conn, timeout=3, port=None):
    ping = get_config_entry("arduino", "ping_connectivity", default=True, value_type=bool)

    if not conn or not conn.is_open:
        return False
    if not ping:
        return True

    try:
        conn.write_timeout = timeout
        conn.timeout = timeout

        conn.reset_input_buffer()
        conn.write(b"PING\n")
        conn.flush()

        buffer = b""
        start = time.time()

        while time.time() - start < timeout:
            if conn.in_waiting:
                buffer += conn.read(conn.in_waiting)
                if b"PONG" in buffer:
                    return True
            time.sleep(0.1)

        return False

    except (serial.SerialTimeoutException, serial.SerialException, OSError):
        return False
    
def get_arduino(baud=9600, timeout=1):
    """
    Tries to connect to an Arduino over USB or Bluetooth serial COM ports.
    Returns a Serial object or None.
    """
    confport = get_config_entry("arduino", "port", default=None, value_type=str)

    # If user specified port, try only that
    ports = [confport] if confport else list_ports_cached()

    if not ports:
        print_once("port_missing", t.t("arduino.port_missing"))
        return None

    _last_attempt = {}  # key=port, value=last_attempt_time

    for port in ports:
        with arduino_lock:
            if arduino and arduino.port == port:
                continue

        now = time.time()
        if port in _last_attempt and now - _last_attempt[port] < 5:
            continue
        _last_attempt[port] = now

        result = [None]  # store result from thread

        def target():
            try:
                arduino_conn = serial.Serial(port, baud, timeout=timeout)
                if arduino_is_alive(arduino_conn, port=port):
                    print_once("port_connected", t.t("arduino.port_connected", port=port))
                    result[0] = arduino_conn
                    return
                
                arduino_conn.close()  # failed handshake
            except Exception as e:
                print_once("port_error", t.t("arduino.port_error", port=port, e=e))

        thread = threading.Thread(target=target)
        thread.start()
        print_once("port_trying", t.t("arduino.port_trying", port=port))
        thread.join(timeout=10)  # max time to try connecting this port

        if thread.is_alive():
            print_once("port_error", t.t("arduino.port_timeout", port=port))
            continue  # try next port

        if result[0]:
            return result[0]  # successfully connected

    # If no port worked
    print_once("not_found", t.t("arduino.not_found"))
    return None

def arduino_watchdog(
    check_interval=1,
    reconnect_interval=3,
    baud=9600,
    timeout=1,
):
    """
    Keeps Arduino connection alive, reconnects if disconnected,
    prints proper messages when disconnected or reconnected,
    and stops after max_retries failed reconnect attempts.
    """
    max_retries = get_config_entry("arduino", "retry_count", default=3, value_type=int)

    global arduino
    failed_reconnects = 0

    while True:
        start = time.time()
        with arduino_lock:
            current = arduino

        # --- Check if connected Arduino is alive ---
        if current:
            alive = False
            try:
                alive = arduino_is_alive(current, timeout=1)
            except Exception:
                alive = False

            if alive:
                # Arduino is alive, reset failure counter
                failed_reconnects = 0
                time.sleep(check_interval)
                continue

        # --- If not connected, try to reconnect ---
        conn = get_arduino(baud=baud, timeout=timeout)
        if conn:
            set_arduino(conn)
            reset_arduino_print_state()
            failed_reconnects = 0
        else:
            failed_reconnects += 1
            print_once("reconnect_failed", t.t("arduino.reconnect_failed", count=failed_reconnects, max=max_retries))
            if failed_reconnects >= max_retries:
                print_once("not_found", t.t("arduino.not_found"))
                break  # stop the watchdog thread
            time.sleep(reconnect_interval)

        # Adaptive sleep to maintain roughly check_interval
        elapsed = time.time() - start
        time.sleep(max(check_interval - elapsed, 0))

    print_once("not_set_up", t.t("arduino.not_set_up", arduino=arduino))

def get_current_arduino():
    with arduino_lock:
        return arduino

def arduino_checkup():
    global arduino
    if get_config_entry("arduino", "connect", default=False, value_type=bool):
        try:
            threading.Thread(
                target=arduino_watchdog,
                daemon=True
            ).start()
        except Exception as e:
            print(t.t("error.unexpected", e=e))
            arduino = None

arduino_checkup()

def arduino_send_prompt(prompt: str, timeout: float = 3.0, expect_response: bool = True):
    """
    Send a prompt/command to the Arduino and return only the response
    until the <END> marker is received.
    """

    conn = get_current_arduino()

    if not conn or not conn.is_open:
        print_once("arduino_not_connected", t.t("arduino.not_connected"))
        return None

    try:
        # Clear old buffer
        conn.reset_input_buffer()

        # Send command
        conn.write((prompt.strip() + "\n").encode())
        conn.flush()

        if not expect_response:
            return None

        start_time = time.time()
        lines = []

        while time.time() - start_time < timeout:
            if conn.in_waiting:
                raw = conn.readline().decode(errors="ignore").strip()

                if not raw:
                    continue

                # Stop if Arduino signals end of response
                if raw == "<END>":
                    break

                lines.append(raw)

            time.sleep(0.01)

        if not lines:
            return None

        # Return only last meaningful line
        return lines[-1]

    except Exception as e:
        print_once("arduino_send_error", str(e))
        return None
    
# online speak function using pyttsx3

def speak_online(text):
    voiceid = get_config_entry("tts", "online_voice", default=5, value_type=int)
    non_english_id = get_config_entry("tts", "non_english_voice", default=1, value_type=int)

    if lang != "en":
        voiceid = non_english_id

    print(t.t("prompts.online_assistant", text=text))
    for voice in voices:
        # This will allow the voice to default to 0 if voice 5 is not found
        if "aria" in voice.name.lower():
            tts_engine.setProperty('voice', voices[int(voiceid)].id)
            break

# Offline speak function using pyttsx3

def speak_offline(text):
    voiceid = get_config_entry("tts", "offline_voice", default=1, value_type=int)
    non_english_id = get_config_entry("tts", "non_english_voice", default=1, value_type=int)

    if lang != "en":
        voiceid = non_english_id

    print(t.t("prompts.offline_assistant", text=text))
    for voice in voices:
        # This will allow the voice to default to 0 if voice 1 is not found
        if "aria" in voice.name.lower():
            tts_engine.setProperty('voice', voices[int(voiceid)].id)
            break

# Unified speak function switching dynamically

def speak(text):
    offline_voice = get_config_entry("tts", "force_offline_voice", default=True, value_type=bool)
    speech_rate = get_config_entry("tts", "speech_rate", default=170, value_type=int)
    volume = get_config_entry("tts", "volume", default=1, value_type=float)

    global voices
    global tts_engine

    if get_config_entry("arduino", "connect", default=False, value_type=bool):
        arduino = get_current_arduino()
        if arduino:
            try:
                arduino.write((t.t("arduino.static_line") + "\n").encode())
                time.sleep(0.5)
                arduino.write((t.t("arduino.second_line", text=text) + "\n").encode())
            except (serial.SerialTimeoutException, serial.SerialException, OSError) as e:
                if is_private():
                    e = "PRIVATE"
                print(f"Arduino write error: {e}")
                set_arduino(None)

    dontspeak = get_config_entry("tts", "disable_tts", default=False, value_type=bool)
    if dontspeak:
        print(t.t("prompts.text_assistant", text=text))
        return

    tts_engine = pyttsx3.init()
    voices = tts_engine.getProperty('voices')
    tts_engine.setProperty('rate', speech_rate)
    tts_engine.setProperty('volume', volume)

    if not offline_voice:
        if check_internet():
            speak_online(text)
        else:
            speak_offline(text)
    else:
        speak_offline(text)

    tts_engine.say(text)
    tts_engine.runAndWait()
    tts_engine.stop()

# --- Start tcp server ---
# Using the tcp server, you are allowed to interact with the assistant using the server, and read its output on your client
# The server can have its ip and port set in config.json

SOCKET_HOST = get_config_entry("server", "host", default="0.0.0.0", value_type=str)
SOCKET_PORT = get_config_entry("server", "port", default=11446, value_type=int)

# Queue that will hold incoming commands
command_queue = Queue()

def start_command_server(host=SOCKET_HOST, port=SOCKET_PORT):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()
    server.setblocking(False)
    if is_private() is False:
        print(t.t("server.server_listening", port=port, host=host))
    return server

def _client_handler(conn, addr):
    """
    Handles a single client connection.
    Reads multiple lines and enqueues them into command_queue.
    Also registers this connection so we can send replies.
    """
    print(t.t("server.new_client", addr=addr))
    conn.settimeout(0.1)
    buffer = ""

    # register client
    with client_lock:
        client_connections.append(conn)

    try:
        while True:
            try:
                chunk = conn.recv(1024)
                if not chunk:
                    print(t.t("server.client_disconnected", addr=addr))
                    break
                buffer += chunk.decode("utf-8", errors="ignore")
                # process complete lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    message = line.strip()
                    if message:
                        print(t.t("server.message_recieved", addr=addr, message=message))
                        command_queue.put(message)
            except socket.timeout:
                # no data right now, loop again
                continue
    except Exception as e:
        if is_private():
            e="PRIVATE"
        print(t.t("error.tcp_client", e=e, addr=addr))
    finally:
        # unregister client
        with client_lock:
            if conn in client_connections:
                client_connections.remove(conn)
        conn.close()
        print(t.t("server.connection_closed", addr=addr))

def send_server_response(message: str):
    """
    Sends a line of text back to all connected clients.
    """
    data = (message + "\n").encode("utf-8")
    with client_lock:
        dead_conns = []
        for conn in client_connections:
            try:
                conn.sendall(data)
            except Exception as e:
                if is_private():
                    e="PRIVATE"
                print(t.t("error.server_response", e=e))
                dead_conns.append(conn)

        # remove dead connections
        for dc in dead_conns:
            try:
                dc.close()
            except:
                pass
            if dc in client_connections:
                client_connections.remove(dc)

def _server_accept_loop(server):
    """
    Loop that accepts new connections and spawns per-client handlers.
    """
    print(t.t("server.loop_started"))
    while True:
        try:
            conn, addr = server.accept()
        except BlockingIOError:
            # no pending connections
            time.sleep(0.05)
            continue
        except Exception as e:
            if is_private():
                e="PRIVATE"
            print(t.t("error.server_loop", e=e))
            time.sleep(0.5)
            continue

        if is_private() is True:
            addr = "PRIVATE"

        threading.Thread(
            target=_client_handler,
            args=(conn, addr),
            daemon=True
        ).start()

server = None
if get_config_entry("server", "open_tcp", default=False, value_type=bool):
    try:
        server = start_command_server()
        threading.Thread(target=_server_accept_loop, args=(server,), daemon=True).start()
    except Exception as e:
        if is_private():
            e="PRIVATE"
        print(t.t("error.unexpected", e=e))
        server = None

    logger = TCPLogger()

    # Keep original built-in print in case you need it
    _builtin_print = builtins.print

def read_command_server(timeout=0.0):
    try:
        # Non-blocking if timeout == 0
        return command_queue.get(timeout=timeout)
    except Empty:
        return None

# Helper for non-blocking terminal input

terminal_buffer = ""
_prompt_shown = False  # internal flag

def get_terminal_input(prompt="> "):
    global terminal_buffer, _prompt_shown

    # Show the prompt once, when starting a new line
    if not _prompt_shown and terminal_buffer == "":
        print(prompt, end="", flush=True)
        _prompt_shown = True

    while msvcrt.kbhit():
        char = msvcrt.getwch()
        if char in ("\r", "\n"):
            line = terminal_buffer
            terminal_buffer = ""  # reset buffer
            _prompt_shown = False  # next call will reprint prompt
            print("")  # simulate Enter
            return line
        elif char == "\b":  # backspace
            if terminal_buffer:
                terminal_buffer = terminal_buffer[:-1]
                # erase character from console
                print("\b \b", end="", flush=True)
        else:
            terminal_buffer += char
            print(char, end="", flush=True)

    return None

# All the phrases/words required for Vosk vocabulary will be listed here

def extract_words_from_regex(pattern):
    """
    Extracts literal words from a regex pattern.
    Example:
    \\b(today|tomorrow|tonight)\\b → ['today', 'tomorrow', 'tonight']
    """
    # remove boundaries and escapes
    cleaned = re.sub(r"\\[bdsw]", " ", pattern)
    final = re.findall(r"[a-zA-Z]+", cleaned)

    # extract words
    return final

def get_commands_vocab():
    commands = load_commands(lang)
    vocab = set()

    intent_defs = commands.get("INTENT_DEFINITIONS", {})
    entity_defs = commands.get("ENTITY_DEFINITIONS", {})
    general_prompts = commands.get("GENERAL_PROMPTS", {})

    # ---- INTENTS ----
    for intent in intent_defs.values():
        
        # ---- ADD PROMPT CONDITIONS FROM INTENT DEFS ----
        prompts = intent.get("prompts", {})
        if prompts:
            for k, v in prompts.items():
                found_key = prompts.get(k)
                if found_key:
                    if isinstance(found_key, bool):
                        continue
                    elif isinstance(found_key, list):
                        for val in found_key:
                            vocab.update(val.lower().split())
                    else:
                        vocab.update(v.lower().split())

        keywords = intent.get("keywords", {})

        if not isinstance(keywords, dict):
            continue

        source = keywords.get("source")
        additional = keywords.get("additional", {})

        # --- Case 1: entity-based keywords ---
        if source == "entity_values":
            entity_name = keywords.get("entity")

            values = (
                entity_defs
                .get(entity_name, {})
                .get("values", {})
            )

            if isinstance(values, dict):
                for key, val in values.items():
                    if isinstance(val, dict) and "translation" in val:
                        vocab.update(val["translation"].lower().split())
                    if isinstance(val, dict) and "prompts" in val:
                        prompts = val["prompts"]
                        for k, v in prompts.items():
                            found_key = prompts.get(k)
                            if found_key:
                                if isinstance(found_key, bool):
                                    continue
                                elif isinstance(found_key, list):
                                    for val in found_key:
                                        vocab.update(val.lower().split())
                                else:
                                    vocab.update(v.lower().split())
                    elif isinstance(val, str):
                        vocab.update(val.lower().split())
                    else:
                        vocab.update(key.lower().split())

            elif isinstance(values, list):
                for val in values:
                    vocab.update(val.lower().split())

        # --- Case 2: additional-only keywords (NO source) ---
        if isinstance(additional, dict):
            for key, val in additional.items():
                if isinstance(val, dict) and "translation" in val:
                    if isinstance(val["translation"], list):
                        for t in val["translation"]:
                            vocab.update(t.lower().split())
                    else:
                        vocab.update(val["translation"].lower().split())
                if isinstance(val, dict) and "prompts" in val:
                    prompts = val["prompts"]
                    for k, v in prompts.items():
                        found_key = prompts.get(k)
                        if found_key:
                            if isinstance(found_key, bool):
                                continue
                            elif isinstance(found_key, list):
                                for val in found_key:
                                    vocab.update(val.lower().split())
                            else:
                                vocab.update(v.lower().split())

                elif isinstance(val, str):
                    vocab.update(val.lower().split())
                else:
                    vocab.update(key.lower().split())

    # ---- ENTITIES ----
    for entity in entity_defs.values():
        if entity["type"] == "gazetteer":
            values = entity.get("values", [])

            if isinstance(values, dict):
                # Refer to elsewhere if specified
                for key, mapped_value in values.items():
                    if key == "READ":
                        type = dict if mapped_value["type"] == "dict" else list
                        values = get_config_entry(mapped_value["section"], value_type=type)
                        continue
                    else:
                        values.update({key: mapped_value})
                        
                for k, v in values.items():
                    if isinstance(v, str):
                        vocab.update(v.lower().split())
                    else:
                        vocab.update(k.lower().split())

            elif isinstance(values, list):
                for v in values:
                    vocab.update(v.lower().split())

        elif entity["type"] == "regex":
            patterns = entity.get("patterns", [])

            if isinstance(patterns, dict):
                pattern_list = patterns.values()
            else:
                pattern_list = patterns

            for pattern in pattern_list:
                words = extract_words_from_regex(pattern)
                vocab.update(w.lower() for w in words)

    # ---- GENERAL PROMPTS ----
    if general_prompts:
        for k, v in general_prompts.items():
            found_key = general_prompts.get(k)
            if found_key:
                if isinstance(found_key, bool):
                    continue
                elif isinstance(found_key, list):
                    for val in found_key:
                        vocab.update(val.lower().split())
                else:
                    vocab.update(v.lower().split())

    cleaned = {
        w.strip(string.punctuation).lower()
        for w in vocab
        if w.strip(string.punctuation)
    }

    final_vocabulary = sorted(list(cleaned))
    return final_vocabulary

def get_phrases():
    all_vocabulary = (
    list(get_commands_vocab())
    + [get_config_entry("phrases", "confirm", default=t.t("defaults.confirm"), value_type=str)]
    + [get_config_entry("phrases", "decline", default=t.t("defaults.decline"), value_type=str)]
    + [get_config_entry("comprehension", "wake_word", default=t.t("defaults.wake_word"), value_type=str)]
    + list(load_config().get("applications",{}))
    )
    if lang == "en":
        return [word for word in all_vocabulary if isinstance(word, str) and all(ord(c) < 128 for c in word)]
    else:
        # return [word for word in all_vocabulary if isinstance(word, str) and word.strip()]
        return all_vocabulary
   
# Vosk Log level, -1, 0 , 1 , 2 , are accepted, -1 is nothing is printed, 0 only errors, 1 more things "idk", 2 everything
# This only works on some systems, it is not working all the time.

loglevel = get_config_entry("vosk", "log_level", default=-1, value_type=int)
SetLogLevel(loglevel)

# Set up the vosk model

def get_vosk_model():
    while True:
        config = load_config()

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        value = filedialog.askdirectory(
            title = t.t("titles.vosk_model_window")
        )
        root.destroy()

        # User clicked Cancel
        if not value:
            print(t.t("error.vosk_selection_cancel1"))
            print(t.t("error.vosk_selection_cancel2"))
            sys.exit()

        # Try to load model
        try:
            model = Model(value)

            # Save selection to config
            config.setdefault("vosk", {})
            config["vosk"][f"vosk-{lang}"] = value
            save_config(config)

            print(t.t("report.vosk_model_set"))
            break  # success, exit loop
        except Exception as e:
            if is_private():
                e="PRIVATE"
            print(t.t("error.vosk_failed", e=e))
            continue

    return model

if not get_config_entry("vosk", "disable_vosk", default=False, value_type=bool):
    try:
        try:
            config_model_path = get_config_entry("vosk", f"vosk-{lang}", value_type=str)
            model = Model(config_model_path)
        except:
            default = resource_path(f"models/vosk{lang}1")
            model = Model(default)
    except:
        print(t.t("error.vosk_wrong_directory"))
        model = get_vosk_model()

# Loading vosk recognizer

_last_phrases = []

def recognizer(printphrases=False, command=True):
    global _last_phrases
    vocabulary = get_config_entry("vosk", "vocabulary", default=True, value_type=bool)

    if vocabulary:
        current_phrases = get_phrases()
        if not current_phrases:
            current_phrases = []

        if current_phrases != _last_phrases:
            _last_phrases = list(current_phrases)

        if printphrases:
            return _last_phrases
        
        if vocabulary and command and lang == "en":
            return KaldiRecognizer(model, audio_device_info("input_sample_rate"), json.dumps(_last_phrases))
    else:
        return KaldiRecognizer(model, audio_device_info("input_sample_rate"))