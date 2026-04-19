"""
The funcitons that are considered as somewhat general and are to be used throughout the code
will be located here instead of their own dedicated action files, this way they can be used anywhere
"""

# --- Standard Library ---
import os
import sys
import re
import shutil
import subprocess
import threading
import time
import serial
import json
import tempfile
import warnings

# --- Third-Party Packages ---
import vlc
import keyboard
import psutil

#...
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API.*",
    category=UserWarning
)
import pygame
#...

import requests
from comtypes import CLSCTX_ALL
from ctypes import cast, POINTER
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from word2number import w2n

# --- Local Modules ---
from config_utils import (
    load_config, 
    save_config, 
    get_config_entry,
    resource_path,
)
from comprehension import (
    confirm_text,
)
from starter import (
    check_internet,
    q,
    recognizer,
    speak, 
    LOCKFILE, 
    t,
    read_command_server,
    get_terminal_input,
    set_arduino,
    get_current_arduino,
    arduino_checkup,
    is_private,
    arduino_send_prompt,
)

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

# Wait for command confirm/decline

def wait_for_confirmation():
    confirm = get_config_entry("phrases", "confirm", default=t.t("defaults.confirm"), value_type=str)
    decline = get_config_entry("phrases", "decline", default=t.t("defaults.decline"), value_type=str)
    repetition = get_config_entry("behavior", "ask_repetition", default=3, value_type=int)
    timeout = get_config_entry("behavior", "ask_timeout", default=5, value_type=int)
    printall = get_config_entry("vosk", "print_input", default=False, value_type=bool)
    disablevosk = get_config_entry("vosk", "disable_vosk", default=False, value_type=bool)
    use_server = get_config_entry("server", "open_tcp", default=False, value_type=bool)

    if disablevosk:
        # Text-based confirmation
        for attempt in range(repetition):
            # Show the confirmation prompt (info text)
            print(t.t("prompts.response_confirmation", attempt=attempt, repetition=repetition))
            # Loop until we get a valid confirmation / decline
            while True:
                text = None

                # 1) Try to read from server first (non-blocking)
                if use_server:
                    text = read_command_server()

                # 2) If nothing from server, check terminal (non-blocking)
                if not text:
                    prompt_str = t.t("input.type_confirmation", confirm=confirm, decline=decline)
                    text = get_terminal_input(prompt_str)

                # 3) If still nothing, just sleep a bit and continue
                if not text:
                    time.sleep(0.05)
                    continue

                # 4) We have some text, try to interpret it
                command = confirm_text(text)

                if command == True:
                    print(t.t("report.confirmed"))
                    return True
                elif command == False:
                    print(t.t("report.declined"))
                    return False
                else:
                    # Invalid answer, tell user and break inner loop
                    print(t.t("error.invalid_confirm", text=text, confirm=confirm, decline=decline))
                    break  # go to next attempt

            # Only speak again if there are attempts left
            if attempt < repetition - 1:
                speak(t.t("request.type_confirm",
                        confirm=confirm,
                        decline=decline))

        # If we exhaust all attempts without valid confirm/decline
        return False

    # --- Normal Vosk-based confirmation ---
    recognizer_en = recognizer()
    for attempt in range(repetition):
        # 🔹 Clear queue before each attempt
        with q.mutex:
            q.queue.clear()

        start_time = time.time()
        print(t.t("prompts.response_confirmation", attempt=attempt + 1, repetition=repetition))
        print(t.t("request.confirmation", confirm=confirm, decline=decline))

        while time.time() - start_time < timeout + 0.3:
            if not q.empty():
                data = q.get()
                if recognizer_en.AcceptWaveform(data):
                    result = json.loads(recognizer_en.Result())
                    text = result.get("text", "").strip().lower()
                    command = None
                    if not text or text=="":
                        text = read_command_server()

                    if text and text!="":
                        command = confirm_text(text)

                    if printall:
                        print(text)

                    if command is None:
                        continue
                    elif command == True:
                        print(t.t("report.confirmed"))
                        return True
                    elif command == False:
                        print(t.t("report.declined"))
                        return False

        if attempt < repetition - 1:
            speak(t.t("request.say_confirm", confirm=confirm, decline=decline))
        else:
            print(t.t("error.invalid_confirm", text=text, confirm=confirm, decline=decline))

        time.sleep(0.5)
        with q.mutex:
            q.queue.clear()
            
    return False

# Restart the assistant

def restart_assistant():
    """Restart the program safely in a new terminal on Windows, waiting for lock file."""
    script_path = os.path.abspath(sys.argv[0])

    # Create a temporary batch file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.bat', delete=False) as bat_file:
        bat_path = bat_file.name
        bat_file.write(f"""
@echo off
:waitloop
if exist "{LOCKFILE}" (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
start "" "{script_path}"
del "%~f0"
""")

    # Launch the batch file in a new console
    subprocess.Popen([bat_path], shell=True)
    sys.exit()
    
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
                print(t.t("report.key_pressed", keys=" + ".join(input_data)))

        elif isinstance(input_data, str):
            if len(input_data.strip()) == 1 or is_known_key(input_data):
                keyboard.send(input_data)
                if verbose:
                    print(t.t("report.key_pressed", keys=input_data))
            else:
                keyboard.write(input_data, delay=delay)
                if verbose:
                    print(t.t("report.sentence_typed", input_data=input_data))

        else:
            raise ValueError(t.t("error.invalid_input"))

    except Exception as e:
        if is_private():
            e = "PRIVATE"
        print(t.t("error.input_exception", input_data=input_data, e=e))

# Launch an exe file

def launch_app(app_name, app_dir):

    # speak(t.t("report.opening_app", appname=app_name))
    try:
        subprocess.Popen(app_dir, shell=True)
    except Exception as e:
        print(t.t("error.unexpected", e=e))

# Exit an exe file

def close_app(app_name, app_dir):
    if app_name == "self":
        sys.exit()

    try:
        process_name = os.path.basename(app_dir)
        subprocess.run(["taskkill", "/f", "/im", process_name], shell=True)
        print(t.t("report.app_closed", process_name=process_name))
    except KeyError:
        print(t.t("report.path_not_configured", appname=app_name))
    except Exception as e:
        if is_private():
            e = "PRIVATE"
        print(t.t("error.closing_app", appname=app_name, e=e))

# State system resource usage as well as network connectivity

def get_system_status(taskmanager=False):
        if check_internet():
            connection = t.t("report.network_stable")
        else:
            connection = t.t("report.network_unpresent")
        
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        ram_used = ram.used // (1024 ** 2)
        ram_total = ram.total // (1024 ** 2)
        ram_percent = ram.percent

        # Launch Taskmangar if True
        if taskmanager:
            input_keyboard(["ctrl", "shift", "esc"], verbose=False)    

        report = t.t("report.system_status", cpu=cpu, ram_percent=ram_percent, connection=connection)
        print(report)
        speak(report)

# Summerize ping output

def summarize_ping(output: str) -> str:
    # Extract packet stats
    packets_match = re.search(
        r"Sent = (\d+), Received = (\d+), Lost = (\d+) \((\d+)% loss\)",
        output
    )

    latency_match = re.search(
        r"Minimum = (\d+)ms, Maximum = (\d+)ms, Average = (\d+)ms",
        output
    )

    if not packets_match or not latency_match:
        return "Unable to parse ping output."

    sent, received, lost, loss_percent = packets_match.groups()
    min_latency, max_latency, avg_latency = latency_match.groups()

    return t.t("report.ping_output", sent=sent, received=received, loss_percent=loss_percent, avg_latency=avg_latency)

# Perform a system power action

def cmd_action(action: str = None, cmd: str = None, summarize: bool = False):
    default_commands = {
        "log off": "shutdown /l",
        "lock": "rundll32.exe user32.dll,LockWorkStation",
        "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "shutdown": "shutdown /s /t 2",
        "restart": "shutdown /r /t 2",
        "hibernate": "shutdown /h",
    }

    # Merge: config overrides defaults, defaults stay otherwise
    commands = {**default_commands}
    set_command = None

    if action is not None:
        set_command = commands.get(action.lower())
        if set_command:
            cmd = set_command

    if set_command is None and cmd is not None:
        cmd = cmd

    if cmd:
        if is_private():
            cmd_display = "PRIVATE"
        else:
            cmd_display = cmd
        print(t.t("prompts.cmd_command", action=action, cmd=cmd_display))
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True
            )

            output = result.stdout      # standard output
            error_output = result.stderr
            return_code = result.returncode
            
            if not is_private():
                print("Output:", output)
                print("Error:", error_output)
                print("Return code:", return_code)

            if action == "ping" and summarize is True:
                report = summarize_ping(output)
                speak(report)

            if cmd in ("restart", "shutdown"):
                sys.exit()
        except Exception as e:
            if is_private():
                e = "PRIVATE"
            print(t.t("error.unexpected", e=e))
    else:
        print(t.t("prompts.unknown_command", action=action))

# Set system volume

def set_system_volume(level):
    if not level:
        return
    level = max(0, min(100, int(level)))
    if level is not None:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))

        # Set volume (0.0 to 1.0)
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        speak(t.t("report.volume_set", level=level))
    else:
        print(t.t("report.volume_not_found"))
        speak(t.t("report.volume_not_heard"))

# Youtube Music API
# Uses youtube music api to interact with youtube music
# currently only tested on https://github.com/th-ch/youtube-music/ API plugin

def send_music_command(endpoint, volume = None):
    url = f"http://localhost:26538/api/v1/{endpoint}"
    headers = {
        "Authorization": "Bearer",
        "Accept": "*/*"
    }

    if endpoint == "volume":
        if not volume:
            return
        else:
            level = volume
        if level is None:
            print(t.t("report.volume_not_found"))
            speak(t.t("report.volume_not_heard"))
            return

        headers["Content-Type"] = "application/json"
        data = {"volume": level}
        try:
            r = requests.post(url, headers=headers, json=data)
            print(t.t("report.volume_set", level=level))
            speak(t.t("report.volume_set_music", level=level))
        except Exception as e:
            if is_private():
                e = "PRIVATE"
            print(t.t("error.error", e=e))
            speak(t.t("report.volume_error"))
    else:
        try:
            r = requests.post(url, headers=headers)
            print(f"{endpoint.upper()}: {r.status_code} → {r.text}")
        except Exception as e:
            if is_private():
                e = "PRIVATE"
            print(t.t("error.error", e=e))   

# Fetching crypto info from coingecko

def get_crypto_info(crypto_id=None, crypto_name=None, action=None):
    def humanize_number(n):
        billion = t.t("defaults.billion")
        million = t.t("defaults.million")
        thousand = t.t("defaults.thousand")
        if n >= 1_000_000_000:
            return f"{n/1_000_000_000:.2f} {billion}"
        elif n >= 1_000_000:
            return f"{n/1_000_000:.2f} {million}"
        elif n >= 1_000:
            return f"{n/1_000:.2f} {thousand}"
        else:
            return f"{n:.2f}"

    if action == "status":
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_id}&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true"
    elif action == "price":
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_id}&vs_currencies=usd"
    elif action == "trending":
        url = "https://api.coingecko.com/api/v3/search/trending"
    elif action is None:
        return

    if is_private() is False:
        print(url)

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if action == "price":
            price = data[crypto_id]["usd"]
            speak(t.t("report.crypto_price", crypto=crypto_name, price=price))
        elif action == "status":
            price = data[crypto_id]["usd"]
            change = f"{data[crypto_id]['usd_24h_change']:+.1f}%"
            volume = humanize_number(data[crypto_id]["usd_24h_vol"])
            speak(t.t("report.crypto_status", crypto=crypto_name, price=price, change=change, volume=volume))
        elif action == "trending":
            name = data["coins"][0]["item"]["name"]
            speak(t.t("report.crypto_trending", crypto=name))

    except:
        if check_internet():
            speak(t.t("report.crypto_fail"))
        else:
            speak(t.t("report.no_connection"))
 
# Getting the weather condition from weatherapi.com
# API must be set in config.json for this to work

def get_weather_wapi(city_id, city_name, unit):

    website="https://www.weatherapi.com/my/"
    website_name=t.t("defaults.weather_website_name")
    api_key = get_config_entry("apis", "weatherapi", value_type=str)

    if api_key is None:
        print(t.t("report.api_not_found", website=website))
        speak(t.t("request.set_api", website_name=website_name))
        return

    url = f"http://api.weatherapi.com/v1/current.json?key={api_key}&q={city_id}&aqi=no"
    safe_url = f"http://api.weatherapi.com/v1/current.json?key=HIDDEN&q={city_id}&aqi=no"

    if unit is None:
        unit = get_config_entry("system", "temperature_unit", value_type=str)
        if not unit:
            unit = t.t("temperature_unit")
            if not unit:
                unit = "c"
                unit_display = "Celsius"

    if unit in("c", "centigrade", "celsius", "1"):
        unit = "c"
        unit_display = "Celsius"
    elif unit in("f", "farenheit", "2"):
        unit = "f"
        unit_display = "Farenheit"

    temp_unit = f"temp_{unit}"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        temp = data["current"][temp_unit]
        desc = data["current"]["condition"]["text"]
        humidity = data["current"]["humidity"]

        if desc.lower() == "sunny":
            desc = t.t("defaults.sunny")
        if desc.lower() == "cloudy":
            desc = t.t("defaults.cloudy")
        if desc.lower() == "clear":
            desc = t.t("defaults.clear")
        if desc.lower() == "partly cloudy":
            desc = t.t("defaults.partly_cloudy")
        if desc.lower() == "mist":
            desc = t.t("defaults.mist")
        if desc.lower() == "light rain":
            desc = t.t("defaults.light_rain")
        if desc.lower() == "overcast":
            desc = t.t("defaults.overcast")
        if desc.lower() == "light snow":
            desc = t.t("defaults.light_snow")
        if desc.lower() == "patchy light snow":
            desc = t.t("defaults.patchy_light_snow")

        report = (
            t.t("report.weather", city=city_name.title(), desc=desc),
            t.t("report.weather_detail", temp=temp, humidity=humidity, unit_display=unit_display)
        )

        print(t.t("prompts.url", url=safe_url))
        clean_report = " ".join(report)
        speak(clean_report)

        if "error" in data:
            message = data["error"].get("message", "Unknown error.")
            print(t.t("error.api", message=message))
            speak(t.t("report.info_not_found"))
            return
        
    except Exception as e:
        if is_private():
            e = "PRIVATE"
        if check_internet():
            print(t.t("error.error", e=e))
            print(t.t("error.api_detail", website=website))
            speak(t.t("report.weather_failed"))
        else:
            speak(t.t("report.no_connection"))

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
        speak(t.t("report.no_connection"))
        return None
    
    website = "https://api-ninjas.com/profile"
    website_name = t.t("defaults.ninjas_website_name")

    api_key = get_config_entry("apis", "ninjasapi", value_type=str)
    if api_key is None:
        print(t.t("report.api_not_found", website=website))
        speak(t.t("request.set_api", website_name=website_name))
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
                print(t.t("prompts.url", url=api_url))
                if speak_result:
                    speak(result)
                return result
            else:
                print(t.t("report.endpoint_missing", endpoint=endpoint))
                speak(t.t("report.say_endpoint_missing", endpoint=endpoint))
                return None
        else:
            print(t.t("error.request", status=response.status_code, text=response.text))
            speak(t.t("report.error_fetching_data"))
            return None
    except Exception as e:
        if is_private():
            e = "PRIVATE"
        print(t.t("error.error", e=e))
        speak(t.t("report.error_connecting_api"))
        return None

# Play video files

def play_video(
        video_name: str = None,
        video_path: str = None,
        loop=False,
        playback_speed=1.0,
        stop_key="q"
    ):
    """
    Play a video file with audio using VLC backend.
    Press stop_key to quit.
    """

    # Handle "ask" like before

    if not video_path or not os.path.exists(video_path):
        speak(t.t("report.file_not_located", name=video_name))
        return None
    
    # --- VLC SETUP ---
    instance = vlc.Instance()
    media = instance.media_new(video_path)

    player = instance.media_player_new()
    player.set_media(media)

    # Playback speed
    try:
        player.set_rate(playback_speed)
    except Exception as e:
        if is_private():
            e = "PRIVATE"
        print(t.t("error.unexpected", e=e))

    # Start playback
    player.play()

    print(t.t("prompts.cancel_media", name=video_name, stop_key=stop_key))

    time.sleep(0.1)  # allow VLC to initialize

    # --- LOOP / STOP HANDLING ---
    while True:
        if keyboard.is_pressed(stop_key):
            break

        # Detect end of video
        state = player.get_state()
        if state == vlc.State.Ended:
            if loop:
                player.stop()
                player.play()
            else:
                break

        time.sleep(0.05)

    # Cleanup
    player.stop()

# Play audio files

audio_cond = threading.Condition()
audio_waiting = 0
audio_playing = False

def play_audio(audio_name: str = None, audio_path: str = None, volume=1.0, speed=1.0, loop=0,
               stop_key="q", systemsound: str = None, wait=True, allow_cancel = False):
    global audio_waiting, audio_playing

    with audio_cond:
        audio_waiting += 1
        while audio_playing:
            audio_cond.wait()
        audio_waiting -= 1
        audio_playing = True

    try:
        if systemsound:
            audio_name = systemsound
            default_path = resource_path(f"Sounds/{systemsound}.mp3")
            file_path = get_config_entry("system_sounds", key=systemsound, default=default_path, value_type=str)
            if not file_path or not os.path.exists(file_path):
                audio_path = default_path
            else:
                audio_path = file_path

        elif audio_path:
            audio_path=audio_path
            if is_private() is False:
                audio_name = audio_path
            else:
                audio_name = "PRIVATE"

        if not audio_path or not os.path.exists(audio_path):
            speak(t.t("report.file_not_located", name=audio_name))
            return None

        sound = pygame.mixer.Sound(audio_path)
        sound.set_volume(volume)

        channel = sound.play(loops=loop)

        def monitor_stop():
            while channel.get_busy():
                if systemsound is None and keyboard.is_pressed(stop_key):
                    channel.stop()
                    break
                time.sleep(0.1)

        threading.Thread(target=monitor_stop, daemon=True).start()

        if not systemsound or allow_cancel is True:
           print(t.t("prompts.cancel_media", name=audio_name, stop_key=stop_key))

        # Ensure sound actually starts
        while not channel.get_busy():
            time.sleep(0.01)

        # If someone else is waiting, finish playback
        if not wait:
            while True:
                with audio_cond:
                    if audio_waiting == 0:
                        break
                if not channel.get_busy():
                    break
                time.sleep(0.05)
        else:
            while channel.get_busy():
                time.sleep(0.05)

        return channel

    finally:
        # 🔑 ALWAYS release playback slot
        with audio_cond:
            audio_playing = False
            audio_cond.notify()

# Turn off/on lights via Arduino

def arduino_message(message=None, timeout=3, expect_response:bool=False):
    if message is None:
        print(t.t("arduino.message_missing", message=message))
        return
    
    arduino = get_current_arduino()

    if not get_config_entry("arduino", "connect", default=False, value_type=bool):
        print(t.t("arduino.not_set_up", arduino=arduino))
        speak(t.t("arduino.hint"))
        return

    if not arduino:
        if get_config_entry("arduino", "reconnect_on_commands", default=True, value_type=bool):
            arduino_checkup()
            time.sleep(3)
        arduino = get_current_arduino()
        if not arduino:
            print(t.t("arduino.not_set_up", arduino=None))
            speak(t.t("arduino.no_access"))
            return  

    old_timeout = None
    old_write_timeout = None

    try:
        if timeout is not None:
            old_timeout = arduino.timeout
            old_write_timeout = arduino.write_timeout

            arduino.timeout = timeout
            arduino.write_timeout = timeout

        if expect_response:
            response = arduino_send_prompt(message)
            return response
        else:
            arduino.write(f"{message}\n".encode())
            arduino.flush()

    except (serial.SerialTimeoutException, serial.SerialException, OSError) as e:
        if is_private():
            e = "PRIVATE"
        print(f"Arduino write error: {e}")
        set_arduino(None)

    finally:
        if old_timeout is not None:
            try:
                arduino.timeout = old_timeout
                arduino.write_timeout = old_write_timeout
            except Exception:
                pass

# Stops action files from taking two entity actions at the same time and breaking

def resolve_single_action(entities, action_map):
    found = [key for key in action_map if key in entities]
    if len(found) != 1:
        return None  # ambiguous or missing
    return found[0]

# Timer management related functions
# ---

timers = {}
def activate_alarm():
    try:
        return
    except Exception as e:
        if is_private():
            e = "PRIVATE"
        print(t.t("error.unexpected", e=e))
        return

def _timer_callback(timer_id, message):
    """Internal callback when a timer fires."""
    # Speak or print the message
    print(message)  # or print(message) if speak is unavailable

    # Play notification sound
    play_audio(systemsound="ringtone", wait=True, loop=4, allow_cancel=True)

    # Remove timer from memory and config
    timers.pop(timer_id, None)

    data = load_config()
    data["timers"] = [t for t in data.get("timers", []) if t["id"] != timer_id]
    save_config(data)

def add_timer(timer_data):
    trigger_at = timer_data["trigger_at"]
    timer_id = timer_data["id"]
    message = timer_data["message"]

    # Save timer to config
    data = load_config()
    data.setdefault("timers", []).append(timer_data)
    save_config(data)

    # Schedule it immediately
    delay = trigger_at - time.time()
    t = threading.Timer(delay, _timer_callback, args=(timer_id, message))
    timers[timer_id] = t
    t.start()

    return timer_id

def load_timers_from_config():
    """Load and schedule all timers from config on startup."""
    data = load_config()
    for t in data.get("timers", []):
        timer_id = t["id"]
        message = t.get("message", "Timer done")
        trigger_at = t.get("trigger_at", time.time())
        delay_seconds = max(0, trigger_at - time.time())

        t_obj = threading.Timer(delay_seconds, _timer_callback, args=(timer_id, message))
        timers[timer_id] = t_obj
        t_obj.start()

def cancel_timer(timer_id):
    """Cancel a running timer."""
    if timer_id in timers:
        timers[timer_id].cancel()
        del timers[timer_id]

        # Remove from config as well
        data = load_config()
        data["timers"] = [t for t in data.get("timers", []) if t["id"] != timer_id]
        save_config(data)

# ---