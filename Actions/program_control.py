import os

from action_configuration import command, end
from starter import (
    speak,
    t,
)
from functions import (
    resolve_single_action,
    restart_assistant,
    launch_app,
    close_app,
    wait_for_confirmation,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

def reboot_app(app_name, app_dir):
    if app_name == "self":
        restart_assistant()
    else:
        close_app(app_name, app_dir)
        launch_app(app_name, app_dir)

PROGRAM_ACTIONS = {
    "launch_controls": lambda app_name, app_dir: launch_app(app_name, app_dir),
    "terminate_controls": lambda app_name, app_dir: close_app(app_name, app_dir),
    "reboot_controls": lambda app_name, app_dir: reboot_app(app_name, app_dir),
}

def go_standby():
    speak(t.t("prompts.standby_mode"))
    user = input()
    print(f"You typed: {user}")
    speak(t.t("report.im_back"))
    end()
    
if keyword == "self_standby":
    go_standby()

action_key = resolve_single_action(entities, PROGRAM_ACTIONS)
if not action_key:
    end("FAILED")

if keyword == "self":
    speak(t.t("request.do_you_want", command=f"{entities[action_key]} {t.t("defaults.my_program")}"))
    print(t.t("request.confirm_command", command=action_key))
    confirmed = wait_for_confirmation()

    if confirmed:
        PROGRAM_ACTIONS[action_key](keyword, "")
    else:
        speak(t.t("prompts.command_canceled"))
        end()

if "app_names" in entities and keyword in ("open", "close", "reboot"):
    app_dir, app_name = next(iter(entities["app_names"].items()))

if not app_dir or not os.path.exists(app_dir):
    speak(t.t("report.file_not_located", name=app_name))
    end()

action_key = (
    "launch_controls" if keyword == "open"
    else "terminate_controls" if keyword == "close"
    else "reboot_controls"
)

PROGRAM_ACTIONS[action_key](app_name, app_dir)