from action_configuration import command, end
from starter import (
    speak,
    t,
)
from functions import (
    resolve_single_action,
    cmd_action,
    get_system_status,
    wait_for_confirmation,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

SYSTEM_ACTIONS = {
    "terminate_controls": {
        "func": lambda: cmd_action("shutdown"),
        "name": "shutdown",
        "sensitive": True,
    },
    "reboot_controls": {
        "func": lambda: cmd_action("restart"),
        "name": "restart",
        "sensitive": True,
    },
    "system_state_sleep": {
        "func": lambda: cmd_action("sleep"),
        "name": "sleep",
        "sensitive": True,
    },
    "system_state_hibernate": {
        "func": lambda: cmd_action("hibernate"),
        "name": "hibernate",
        "sensitive": True,
    },
    "system_state_lock": {
        "func": lambda: cmd_action("lock"),
        "name": "lock",
        "sensitive": True,
    },
    "status_controls": {
        "func": lambda: get_system_status(),
        "sensitive": False,
    },
}

action_key = resolve_single_action(entities, SYSTEM_ACTIONS)

if not action_key:
    end("FAILED")

action = SYSTEM_ACTIONS[action_key]

if action["sensitive"]:
    speak(t.t("request.do_you_want", command=f"{action["name"]} {keyword}"))
    print(t.t("request.confirm_command", command="system_control"))

    confirmed = wait_for_confirmation()
    if not confirmed:
        speak(t.t("prompts.command_canceled"))
        end()
    else:
        speak(t.t("prompts.command_confirmed"))

action["func"]()
