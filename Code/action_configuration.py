# --- Standard Library ---
import sys, os, subprocess

# --- Third-Party Packages ---
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

# --- Local Modules ---
import command_functions
import config_utils
from starter import check_internet, recognizer, speak

"""
This is where commands are redirected to functions
A command may call a function from Command_functions or elsewhere
It may also have the code that it performs written under its elif line
debug_menu can be used to add commands and functions, you may also add a python file
which then will be moved to the resource_path to be addresed, the import will accordingly
be added to the top as well

Commands can require a/multiple step(s) to be performed
currently supported requirements are:
"confirm_requried" must pass the command_functions.wait_for_confirmation in order to be performed
"network_required" must pass the starter.check_internet to be performed. many sections of the code use "online required" so this may not be the only check
"notification_required" must play "notification" sound via command_functions.play_audio. this is mostly used to identify the command recognition in case of an abcense of prompt
"""

def perform_action(command, confirm_required=False, network_required=False, notification_required=False):
    if confirm_required:
        print(f"⚠️ Confirmation required for: {command}")
        confirmed = command_functions.wait_for_confirmation()

        if not confirmed:
            speak("Command Cancelled.")
            return
        else:
            speak("Command Confirmed.")

    if network_required:
        if not check_internet():
            speak("Sorry! There is no internet connection! Command cannot be performed!")
            return
        else:
            print("Performing command...")
    
    if notification_required:
        command_functions.play_audio(systemsound="notification", wait=False)

    """
    All commands will be performed here
    All most be elif conditions
    """

    if command == "terminate assistant program":
        sys.exit()
    
    elif command == "run debug menu":
        try:
            # Get absolute path to debug_menu.py
            script_path = config_utils.resource_path("debug_menu.py")
            print(script_path)
            
            # Launch in a new terminal and wait until it is closed, then auto-close
            subprocess.call(
                ["cmd", "/c", "start", "/wait", "cmd", "/c", "python", "-u", script_path],
                shell=True
            )

            print("Debug menu closed. Returning to Assistant.")

        except Exception as e:
            print("Error launching debug menu:", e)

        except KeyboardInterrupt:
            print("Interrupted by user!")
            print("Going back to Assistant")
        except SystemExit:
            raise  # allow the program to exit
        except Exception as e:
            print(f"Error: {e}")
            print("Going back to Assistant")

        def check_for_restart():
            change = config_utils.get_config_entry("system", "lib_changed", default=False, value_type=bool)
            force = config_utils.get_config_entry("system", "restart_on_debug", default=False, value_type=bool)
            if change is True:
                return True
            elif force is True:
                return True
            else:
                return False
        if check_for_restart():
            data = config_utils.load_config()
            if "system" not in data:
                data["system"] = {}
            data["system"]["lib_changed"] = "False"
            config_utils.save_config(data)
            command_functions.restart_assistant()

    elif command == "lock system":
        command_functions.system_power_action("lock")

    elif command == "sleep system":
        command_functions.system_power_action("sleep")

    elif command == "shutdown system":
        command_functions.system_power_action("shutdown")

    elif command == "restart system":
        command_functions.system_power_action("restart")

    elif command == "hibernate system":
        command_functions.system_power_action("hibernate")

    elif command == "check system status":
        command_functions.get_system_status()

    elif command == "list active phrases":
        command_functions.print_list_grid(recognizer(printphrases=True))

    elif command == "list active commands":
        command_functions.print_list_grid(config_utils.load_commands().get("commands", {}))

    elif command == "toggle youtube music": 
        command_functions.send_music_command("toggle-play")

    elif command == "next music track":
        command_functions.send_music_command("next")

    elif command == "previous music track":
        command_functions.send_music_command("previous")

    elif command == "toggle media":
        command_functions.input_keyboard("play/pause media")

    elif command == "next media track":
        command_functions.input_keyboard("next track")

    elif command == "previous media track":
        command_functions.input_keyboard("previous track")

    elif command == "set system volume":
        command_functions.set_system_volume()

    elif command == "current crypto price":
        command_functions.get_crypto_price()

    elif command == "whats todays weather":
        command_functions.get_weather_wapi()

    elif command == "tell me a joke":
        command_functions.get_ninja_data("jokes")

    elif command == "todays my last day":
        command_functions.get_ninja_data("bucketlist")

    elif command == "launch application":
        command_functions.launch_app()
    
    elif command == "close application":
        command_functions.close_app()
    
    elif command == "take screen shot":
        command_functions.input_keyboard("print screen")

    elif command == "play audio file":
        command_functions.play_audio(True, wait=False, volume=0.75)

    elif command == "play funny music":
        command_functions.play_audio("C:/Users/ARK1259/Music/NCS/Gift.mp3", wait=False, volume=0.30)

    elif command == "lights on":
        command_functions.arduino_message("9:100")

    elif command == "lights off":
        command_functions.arduino_message("9:0")

    elif command == "play video file":
        command_functions.play_video(True)

    elif command == "restart assistant program":
        command_functions.restart_assistant()
