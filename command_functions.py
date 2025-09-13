# --- Standard Library ---
import os
import sys
import re
import shutil
import subprocess
import threading
import time
import difflib
import json

# --- Third-Party Packages ---
import cv2
import keyboard
import psutil
import pygame
import requests
from colorama import Back, Fore, init
from comtypes import CLSCTX_ALL
from ctypes import cast, POINTER
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from word2number import w2n

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
from config_utils import load_config, save_config, get_config_entry, resource_path
from starter import arduino, check_internet, q, recognizer, speak, LOCKFILE
from tkinter import Tk, filedialog

# Functions

# Wait for command confirm/decline

def wait_for_confirmation():
    confirm = get_config_entry("behavior", "confirm", default="confirm", value_type=str)
    decline = get_config_entry("behavior", "decline", default="decline", value_type=str)
    repeatition = get_config_entry("behavior", "repeatition", default=3, value_type=int)
    timeout = get_config_entry("behavior", "timeout", default=5, value_type=int)
    printinput = get_config_entry ("vosk", "printinput", default=False, value_type=bool)
    printall = get_config_entry("vosk", "printall", default=False, value_type=bool)
    disablevosk = get_config_entry("vosk", "disablevosk", default=False, value_type=bool)

    if disablevosk:
        # Text-based confirmation
        for attempt in range(repeatition):
            print(f"[Waiting for typed response] Attempt {attempt + 1}/{repeatition}")
            response = input(f"Type '{confirm}' or '{decline}': ").strip().lower()

            if response == confirm:
                print("[CONFIRM] → confirmed")
                return True
            elif response == decline:
                print("[CONFIRM] → declined")
                return False
            else:
                if attempt < repeatition - 1:
                    speak(f"Sorry, I did not understand. Please type {confirm} or {decline}.")
                else:
                    print(f"Invalid choice: {response}",f"\nPlease use {confirm} or {decline}")
        return False

    # --- Normal Vosk-based confirmation ---
    recognizer_en = recognizer(command=False)
    for attempt in range(repeatition):
        # 🔹 Clear queue before each attempt
        with q.mutex:
            q.queue.clear()

        start_time = time.time()
        print(f"[Waiting for response] Attempt {attempt + 1}/{repeatition}")
        print(f"say {confirm} or {decline}:")

        while time.time() - start_time < timeout + 0.3:
            if not q.empty():
                data = q.get()
                if recognizer_en.AcceptWaveform(data):
                    result = json.loads(recognizer_en.Result())
                    text = result.get("text", "").strip().lower()

                    if printall or printinput:
                        print(text)

                    if text == confirm:
                        print("[CONFIRM] → confirmed")
                        return True
                    elif text == decline:
                        print("[CONFIRM] → declined")
                        return False

        if attempt < repeatition - 1:
            speak(f"Sorry, I did not understand. Please say {confirm} or {decline}.")
        else:
            print(f"Invalid choice",f"\nPlease use {confirm} or {decline}")

        time.sleep(0.5)
        with q.mutex:
            q.queue.clear()
            
    return False

# Print a list

def print_list_grid(items, padding=2, title=False):
    # Convert everything to string
    items = list(map(str, items))

    # 1. Get terminal width
    width = shutil.get_terminal_size(fallback=(80, 24)).columns

    # 2. Longest item determines cell width
    cell_width = max(map(len, items)) + padding

    # 3. Calculate number of columns
    cols = max(1, width // cell_width)

    # 4. Calculate number of rows
    rows = (len(items) + cols - 1) // cols

    # 5. Arrange items in column-major order
    grid = [items[r::rows] for r in range(rows)]
    for row in grid:
        if title:
            print("".join(word.title().ljust(cell_width) for word in row))
        else:
            print("".join(word.ljust(cell_width) for word in row))

# Ask for a single entry from a list in config or a list set by default

def ask_single_entry(
        section: str = "",
        defaultlist: list = [],
        nickname: str = "",
        type = list,
        online=True
        ):
    printinput = get_config_entry ("vosk", "printinput", default=False, value_type=bool)
    printall = get_config_entry("vosk", "printall", default=False, value_type=bool)
    strictness = get_config_entry("vosk", "strictness", default=0.8, value_type=float)
    timeout = get_config_entry("behavior", "timeout", default=5, value_type=int)
    if online:
        if not check_internet():
            speak("There is no internet connection, command cannot be performed!")
            return
        
    entrylist = [c.lower() for c in get_config_entry(section, key=None, default=defaultlist, value_type=type)]
    if not entrylist:
        speak(f"No {nickname} names are configured.")
        return

    singular = len(entrylist) == 1
    if singular:
        entryname = entrylist[0]
        print(f"[{nickname.title()}] → {entryname.title()}")
        return entryname

    disablevosk = get_config_entry("vosk", "disablevosk", default=False, value_type=bool)
    speak(f"Which {nickname} would you like?")
    print_list_grid(entrylist, title=True)

    entryname = None

    if disablevosk:
        # --- Typed input mode ---
        entryname = input(f"Type {nickname} name: ").strip().lower()
    else:
        # --- Vosk voice input mode ---
        recognizer_en = recognizer(command=False)
        time.sleep(0.4)
        # Clear queue safely
        while not q.empty():
            q.get_nowait()

        start_time = time.time()
        while time.time() - start_time < timeout + 0.3:
            if not q.empty():
                data = q.get()
                if recognizer_en.AcceptWaveform(data):
                    result = json.loads(recognizer_en.Result())
                else:
                    continue  # skip partial results
                entryname = result.get("text", "").strip().lower()
                break

    if printall or printinput:
        print(entryname)

    # --- Fuzzy matching ---
    matched_command = None
    best_score = 0.0
    for cmd in entrylist:
        score = difflib.SequenceMatcher(None, entryname, cmd).ratio()
        if score > best_score:
            best_score = score
            matched_command = cmd

    if best_score < strictness:
        matched_command = None  # ignore if below threshold

    # --- Execute matched command ---
    if matched_command:
        print(f"[{nickname.title()}] → {entryname.title()}")
        return entryname
    else:
        speak(f"I couldn't hear or recognize any {nickname} name. Is there anything else I can assist you with?")

# Get a volume, 0 to 100, refer to starter.volume_numbers

def ask_volume():
    timeout = get_config_entry("behavior", "timeout", default=5, value_type=int)
    disablevosk = get_config_entry("vosk", "disablevosk", default=False, value_type=bool)

    volume_text = None

    print("Specify volume, 0 to 100:")

    if disablevosk:
        # --- Typed input mode ---
        volume_text = input(f"Type Volume number: ").strip().lower()
    else:
        recognizer_en = recognizer(command=False)
        time.sleep(0.4)
        with q.mutex:
            q.queue.clear()


        start_time = time.time()
        while time.time() - start_time < timeout + 0.3:
            if not q.empty():
                data = q.get()
                if recognizer_en.AcceptWaveform(data):
                    result = json.loads(recognizer_en.Result())
                    volume_text = result.get("text", "").strip().lower()
                    print("[VOLUME] →", volume_text)
                    break

    if volume_text:
        try:
            # Try word-to-number (e.g., "seventy five")
            volume_value = w2n.word_to_num(volume_text)
        except:
            try:
                # Try direct number (e.g., "75")
                volume_value = int(re.search(r"\d{1,3}", volume_text).group())
            except:
                return

        volume_value = max(0, min(volume_value, 100))  # Clamp
        return volume_value
    else:
        return None
    
# Input keys

def is_known_key(name: str) -> bool:
    """Check if the given key name is valid in the keyboard library."""
    try:
        return bool(keyboard.key_to_scan_codes(name))
    except (KeyError, ValueError):
        return False

def input_keyboard(input_data: str | list, delay: float = 0.1, verbose: bool = True):
    """
    Simulates keyboard input. Handles:
    - Single key: "enter"
    - Hotkey combo: ["ctrl", "s"]
    - Special keys like "play/pause media", "volume up", etc.
    - Sentence typing: "Hello world!"
    """
    try:
        if isinstance(input_data, list):
            # hotkey combo
            keyboard.send('+'.join(input_data))
            if verbose:
                print(f"Keys pressed: {' + '.join(input_data)}")

        elif isinstance(input_data, str):
            if len(input_data.strip()) == 1 or is_known_key(input_data):
                keyboard.send(input_data)
                if verbose:
                    print(f"Key pressed: {input_data}")
            else:
                keyboard.write(input_data, delay=delay)
                if verbose:
                    print(f"Typed sentence: \"{input_data}\"")

        else:
            raise ValueError("Unsupported input type.")

    except Exception as e:
        print(f"[Error] Could not simulate input: {input_data}. Reason: {e}")

# Fetching crypto price from coingecko

def get_crypto_price(repeat=True):
    while True:
        crypto = ask_single_entry(
            section="crypto_names",
            defaultlist=["bitcoin", "ethereum", "dogecoin", "solana", "litecoin", "cardano", "tron", "ripple"],
            nickname="crypto currency",
            online=True
        )
        if not crypto:
            return
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto}&vs_currencies=usd"
        print(url)
    
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            price = data[crypto]["usd"]
            message = f"The current price of {crypto.capitalize()} is {price} US dollars."
            speak(message)
        except:
            if check_internet():
                speak("I couldn't retrieve the price. Maybe the cryptocurrency name wasn't recognized.")
                break
            else:
                speak("there is no intenet connection, command cannot be performed!")
                break
        if repeat:
            speak(f"Would you like to know another crypto currency's price?")
            confirmed = wait_for_confirmation()
            if confirmed:
                continue
            else:
                speak(f"Okay, ending crypto currency price check. Is there anything else I can help you with?")
                break

# Launch an exe file

def launch_app(exe_filter=("*.exe", "*.msi")):
    """
    Launches an application. If not configured, asks user to locate the executable.

    Parameters:
        app_key (str): A key like "telegram" or "vscode".
        display_name (str): Human-friendly name for prompts. Defaults to capitalized key.
        exe_filter (str): File type filter for open dialog.
    """
    config = load_config()

    # Ensure 'applications' section exists
    if "applications" not in config:
        config["applications"] = {}

    # Get app name
    resault = ask_single_entry("applications", nickname="application", type=dict, online=False)

    # Handle None
    if not resault:
        return
    
    # Display Name
    appname = resault.title()

    app_path = config["applications"].get(resault)

    if not app_path or not os.path.exists(app_path):
        print("Choose the app directory:")

        # Create a hidden root window
        root = Tk()
        root.withdraw()
        root.lift() # Bring it to the front
        root.attributes('-topmost', True)

        speak(f"Could you show me where {appname} is located?")

        selected_path = filedialog.askopenfilename(
            title=f"Locate {appname} Executable",
            filetypes=[("Executable Files", exe_filter)],
            parent=root
        )
        
        # Restore normal behavior (optional, avoids permanent topmost window)
        root.attributes('-topmost', False)
        root.destroy()

        if selected_path:
            speak(f"Alright, Opening {appname}!")

        if not selected_path:
            print(f"No file selected for {appname}.")
            speak(f"I was not able to locate {appname}!")
            return

        config["applications"][resault] = selected_path
        save_config(config)

        app_path = selected_path

    subprocess.Popen(app_path, shell=True)

# Exit an exe file

def close_app():
    resault = ask_single_entry("applications", nickname="application", type=dict, online=False)
    appname = resault.title()
    try:
        exe_path = get_config_entry("applications", resault)
        process_name = os.path.basename(exe_path)
        subprocess.run(["taskkill", "/f", "/im", process_name], shell=True)
        print(f"{process_name} closed.")
    except KeyError:
        print(f"No path configured for '{appname}'.")
    except Exception as e:
        print(f"Error closing {appname}: {e}")

# State system resource usage as well as network connectivity

def get_system_status(taskmanager=False):
        if check_internet():
            connection = "Network connection is stable."
        else:
            connection = "Network connection is not present."
        
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        ram_used = ram.used // (1024 ** 2)
        ram_total = ram.total // (1024 ** 2)
        ram_percent = ram.percent

        # Launch Taskmangar if True
        if taskmanager:
            input_keyboard(["ctrl", "shift", "esc"], verbose=False)    

        report = f"CPU usage is {cpu}, and RAM usage is {ram_percent} percent. {connection}"
        print(report)
        speak(report)

# Perform a system power action

def system_power_action(action: str):
    """
    Performs system-level power actions.

    Supported actions:
        - Logoff
        - Lock
        - sleep
        - shutdown
        - restart
        - hibernate

    Args:
        action (str): The system command to execute.
    """
    commands = {
        "logoff": "shutdown /l",
        "lock": "rundll32.exe user32.dll,LockWorkStation",
        "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "shutdown": "shutdown /s /t 1",
        "restart": "shutdown /r /t 1",
        "hibernate": "shutdown /h"
    }

    cmd = commands.get(action.lower())

    if cmd:
        print(f"[System] Executing: {action}")
        subprocess.run(cmd, shell=True)
    else:
        print(f"[System] Unknown action: {action}")

# Restart the assistant

def restart_assistant():
    """Restart the program safely in a new terminal on Windows, waiting for lock file."""

    python = sys.executable  # Python interpreter OR exe if frozen
    script = os.path.abspath(sys.argv[0])

    # Path to helper script (write it next to the exe or script)
    helper_script = os.path.join(os.path.dirname(script), "_restart_helper.py")

    # Write helper script
    with open(helper_script, "w", encoding="utf-8") as f:
        f.write(f"""
import time, os, subprocess, serial.tools.list_ports

LOCKFILE = r"{LOCKFILE}"
PYTHON = r"{python}"
SCRIPT = r"{script}"

print("[Helper] Waiting for lock file to be released...")
while os.path.exists(LOCKFILE):
    time.sleep(0.5)

time.sleep(1)
print("[Helper] Starting assistant...")
subprocess.Popen(["cmd.exe", "/C", PYTHON, SCRIPT], creationflags=subprocess.CREATE_NEW_CONSOLE)
os._exit(0)
""")

    if getattr(sys, "frozen", False):
        # Running from exe → we must use pythonw.exe or bundled python to run helper
        subprocess.Popen(
            ["python", helper_script],  # must call python, not the exe
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    else:
        # Normal Python run
        subprocess.Popen(
            [python, helper_script],
            creationflags=subprocess.CREATE_NO_WINDOW
        )

    sys.exit()

# Set system volume

def set_system_volume():
    level = ask_volume()
    if level is not None:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))

        # Set volume (0.0 to 1.0)
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        speak(f"System volume set to {level}%")
    else:
        print("⚠️ No volume number found in command.")
        speak("I couldn't hear any volume value.")

# Youtube Music API
# Uses youtube music api to interact with youtube music
# currently only tested on https://github.com/th-ch/youtube-music/ API plugin

def send_music_command(endpoint):
    url = f"http://localhost:26538/api/v1/{endpoint}"
    headers = {
        "Authorization": "Bearer",
        "Accept": "*/*"
    }

    if endpoint == "volume":
        level = ask_volume()
        if level is None:
            print("⚠️ No volume number found in command.")
            speak("I couldn't hear any volume value.")
            return

        headers["Content-Type"] = "application/json"
        data = {"volume": level}
        try:
            r = requests.post(url, headers=headers, json=data)
            print(f"Set volume {level}% → {r.status_code}")
            speak(f"Music volume set to {level}%")
        except Exception as e:
            print("❌ Error:", e)
            speak("There was an error in setting the volume")
    else:
        try:
            r = requests.post(url, headers=headers)
            print(f"{endpoint.upper()}: {r.status_code} → {r.text}")
        except Exception as e:
            print("❌ Error:", e)   
 
# Getting the weather condition from weatherapi.com
# API must be set in config.json for this to work
# CURRENTLY DOES NOT WORK FOR ME, IDK WHY

def get_weather_wapi():
    city = ask_single_entry(
        section="city_names",
        defaultlist=["tokyo", "london", "chicago", "istanbul", "tehran"],
        nickname="city",
        online=True
    )
    if not city:
        return
    api_key = get_config_entry("apis", "weatherapi")
    if api_key is None:
        print("No API key found! \n Go to https://www.weatherapi.com/my/ to get your API key")
        speak("You have not set your API key yet! Fetch your API key from weather API then use debug menu to set your API.")
        return
    url = f"http://api.weatherapi.com/v1/current.json?key={api_key}&q={city}&aqi=no"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        temp = data["current"]["temp_c"]
        desc = data["current"]["condition"]["text"]
        humidity = data["current"]["humidity"]
        report = (
            f"The weather in {city.title()} is {desc}. "
            f"The temperature is {temp} degrees Celsius with {humidity} percent humidity."
        )
        
        print(f"URL: {url}")
        speak(report)

        if "error" in data:
            message = data["error"].get("message", "Unknown error.")
            print(f"❌ API error: {message}")
            speak("I couldn't retrieve the information. Please check your API key.")
            return
        
    except Exception as e:
        if check_internet():
            print("❌ Weather error:", e)
            print("\nWeatherapi.com error or perhaps you have not set up your API key correctly!")
            speak("I couldn't retrieve the weather.")
        else:
            speak("there is no intenet connection, command cannot be performed!")

# Getting the weather condition from wttr.in

def get_weather_wttr():
    city = ask_single_entry(
        section="city_names",
        defaultlist=["tokyo", "london", "chicago", "istanbul", "tehran"],
        nickname="city",
        online=True
    )
    if not city:
        return
    url = f"https://wttr.in/{city}?format=j1"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        current_condition = data['current_condition'][0]
        temp = current_condition['temp_C']
        desc = current_condition['weatherDesc'][0]['value']
        humidity = current_condition['humidity']

        report = (
            f"The weather in {city.title()} is {desc}. "
            f"The temperature is {temp} degrees Celsius with {humidity} percent humidity."
        )

        print("URL:", url)
        speak(report)

        if "error" in data:
            message = data["error"].get("message", "Unknown error.")
            print(f"❌ API error: {message}")
            speak("I couldn't retrieve the information. Please check your API key.")
            return
        
    except Exception as e:
        if check_internet():
            print("❌ Weather error:", e)
            print("\nWeatherapi.com error or perhaps you have not set up your API key correctly!")
            speak("I couldn't retrieve the weather.")
        else:
            speak("there is no intenet connection, command cannot be performed!")

# Get an endpoint using ninjasapi
# There are many endpoints that ninjasapi supports but this function is super limited, and in future updates will be improved
# API must be set in config.json for this to work

def get_ninja_data(endpoint, speak_result=True):
    """
    Universal NinjaAPI fetcher.
    
    endpoint: str -> API endpoint (e.g., "jokes", "quotes", "facts", "bucketlist")
    speak_result: bool -> whether to speak the result aloud
    """
    if not check_internet():
        speak("There is no internet connection, command cannot be performed!")
        return None

    api_key = get_config_entry("apis", "ninjasapi")
    if api_key is None:
        print("No API key found! \n Go to https://api-ninjas.com/profile to get your API key")
        speak("You have not set your API key yet! Fetch your API key from Ninja API then use debug menu to set your API.")
        return None

    api_url = f"https://api.api-ninjas.com/v1/{endpoint}"
    try:
        response = requests.get(api_url, headers={'X-Api-Key': api_key}, timeout=5)
        if response.status_code == requests.codes.ok:
            data = response.json()

            result = None

            # Case 1: list response (like jokes, quotes, facts, riddles)
            if isinstance(data, list) and len(data) > 0:
                for key in ("joke", "quote", "fact", "riddle", "question", "item"):
                    if key in data[0]:
                        result = data[0][key]
                        break
                if result is None:
                    result = str(data[0])  # fallback stringify

            # Case 2: dict response (like bucketlist endpoint)
            elif isinstance(data, dict):
                for key in ("item", "joke", "quote", "fact", "riddle", "question"):
                    if key in data:
                        result = data[key]
                        break
                if result is None:
                    result = str(data)

            if result:
                print(f"URL: {api_url}")
                if speak_result:
                    speak(result)
                return result
            else:
                print(f"No {endpoint} result found.")
                speak(f"Sorry, I couldn't find a {endpoint}.")
                return None
        else:
            print(f"Error: {response.status_code} {response.text}")
            speak("There was an error fetching the data.")
            return None
    except Exception as e:
        print(f"❌ Exception: {e}")
        speak("There was an error connecting to the API.")
        return None

# Play video files

def play_video(ask: bool = False , video_path: str = None, loop=False, playback_speed=1.0, file_type = ("*.mp4", "*.mov", "*.mkv")):
    """
    Play a video file using OpenCV.
    Press 'space' to quit.

    Args:
        file_path (str): Path to the video file.
        loop (bool): If True, restarts the video when it ends.
        playback_speed (float): Speed multiplier. >1.0 is faster, <1.0 is slower.
    """
    data = load_config()

    if ask:
        resault = ask_single_entry("video", nickname="video", type=dict, online=False)
        if not resault:
            return None
        
        video_name = resault.title()
        video_path = data["video"].get(resault)  # now always safe

        if not video_path or not os.path.exists(video_path):
            print("Choose the video directory:")
            speak(f"Could you show me where {video_name} is located?")

            # Create a hidden root window
            root = Tk()
            root.withdraw()
            root.lift()                      # Bring it to the front
            root.attributes('-topmost', True)

            selected_path = filedialog.askopenfilename(
                title=f"Locate {video_name} file",
                filetypes=[("Video Files", file_type)],
                parent=root
            )

            # Restore normal behavior (optional, avoids permanent topmost window)
            root.attributes('-topmost', False)
            root.destroy()

            if selected_path:
                speak(f"Alright, Playing {video_name}!")
            else:
                print(f"No file selected for {video_name}.")
                speak(f"I was not able to locate {video_name}!")
                return

            data["video"][resault] = selected_path
            save_config(data)
            video_path = selected_path

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Failed to open video: {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25  # fallback if FPS not detected

    wait_time = max(int(1000 / (fps * playback_speed)), 1)  # in milliseconds

    print("Press 'space' to quit the video.")

    while True:
        ret, frame = cap.read()

        if not ret:  # End of video
            if loop:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            else:
                break

        cv2.imshow("Video Playback", frame)

        # Quit if 'space' is pressed
        if cv2.waitKey(wait_time) & 0xFF == ord(' '):
            break

    cap.release()
    cv2.destroyAllWindows()

# Play audio files

def play_audio(ask: bool = True, path: str = None, volume=1.0, speed=1.0, loop=0,
               stop_key="space", systemsound: str = None, wait=True, file_type = ("*.mp3", "*.wav", "*.ogg")):
    """
    Play an audio file using pygame with options for volume, speed, looping.
    - System sounds: no stop key
    - Normal files: global stop key via 'keyboard' library

    :param path: Path to the audio file
    :param volume: Volume level (0.0 to 1.0)
    :param speed: Playback speed (1.0 = normal, pitch changes!)
    :param loop: Number of loops (-1 = infinite, 0 = play once, n = loop n times)
    :param stop_key: Global key name (string, e.g., "space", "s", "esc") to stop playback
    :param systemsound: Play a predefined system sound ("shutdown", "notification", etc.)
    :param wait: If True, block until sound ends/stopped. If False, return immediately.
    """

    data = load_config()

    # Determine file path
    audio_path = None

    if systemsound:
        default_path = resource_path(f"sounds\{systemsound}.mp3")
        file_path = get_config_entry("sounds", key=systemsound,
                                     default=default_path, value_type=str)
        audio_path = file_path
    else:
        if ask:
            resault = ask_single_entry("audio", nickname="audio", type=dict, online=False)
            if not resault:
                return None
            
            audio_name = resault.title()
            audio_path = data["audio"].get(resault)  # now always safe

            if not audio_path or not os.path.exists(audio_path):
                print("Choose the audio directory:")
                speak(f"Could you show me where {audio_name} is located?")

                # Create a hidden root window
                root = Tk()
                root.withdraw()
                root.lift()                      # Bring it to the front
                root.attributes('-topmost', True)

                selected_path = filedialog.askopenfilename(
                    title=f"Locate {audio_name} file",
                    filetypes=[("Audio Files", file_type)],
                    parent=root
                )

                # Restore normal behavior (optional, avoids permanent topmost window)
                root.attributes('-topmost', False)
                root.destroy()

                if selected_path:
                    speak(f"Alright, Playing {audio_name}!")
                else:
                    print(f"No file selected for {audio_name}.")
                    speak(f"I was not able to locate {audio_name}!")
                    return

                data["audio"][resault] = selected_path
                save_config(data)
                audio_path = selected_path
        else:
            audio_path = path

    if not audio_path:
        return None

    # Init mixer fresh
    if pygame.mixer.get_init():
        pygame.mixer.quit()
    pygame.mixer.init()

    # Load sound
    sound = pygame.mixer.Sound(audio_path)
    sound.set_volume(volume)

    # Adjust speed (affects pitch)
    if speed != 1.0:
        freq, size, chan = pygame.mixer.get_init()
        new_freq = int(freq * speed)
        pygame.mixer.quit()
        pygame.mixer.init(frequency=new_freq, size=size, channels=chan)
        sound = pygame.mixer.Sound(audio_path)
        sound.set_volume(volume)

    # Play
    channel = sound.play(loops=loop)

    if systemsound is None:
        print(f"Playing '{audio_path}' (Press '{stop_key}' to stop)")

    def monitor_stop():
        """Run in background thread to check stop key."""
        while channel.get_busy():
            if systemsound is None and keyboard.is_pressed(stop_key):
                channel.stop()
                break
            time.sleep(0.1)  # avoid CPU hogging

    # Start background thread if not waiting
    if not wait:
        threading.Thread(target=monitor_stop, daemon=True).start()
        return channel

    # Blocking wait
    monitor_stop()
    return channel

# Turn off/on lights via Arduino

def arduino_message(message = None):
    if message is None:
        print(f"No message was given: {message}")
        return
    if get_config_entry("behavior", "arduino", default=False, value_type=bool):
        if arduino:
            print (arduino)
            arduino.write(f"{message}".encode())
        else:
            print(f"Arduino is not set up: {arduino}")
            speak("I was unable to access arduino, could it be turned off? or not set up correctly?")
    else:
        print(f"Arduino is not set up: {arduino}")
        speak("You first need to turn on Arduino in the debug_menu before using its commands!")