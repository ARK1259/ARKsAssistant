"""
The logic that is sent out after comprehension will be redirected to its intended action file
The action files are coded in python
There exists only 2 values that matter to these files as a redirection from the assistant:

    "value"
    command
    command = "This is fed in as logic from maincode, and then is renamed to command. Count it the same as whatever comprehension outputs."

    "function"
    end(value)
    end(value) = "In action files, you can use 'return' however, it will look awkward when looking at the file as a proper python code
                    that is why I have included the end method as a solution, whatever you give into end(value) will be digested at
                    the end of perform_action"

The logic fed in from comprehension may also have 2 keys:bool in ["attributes"]:

    ["attributes"]["notify"] = "If true, will play notification sound before going to the action file"

    ["attributes"]["online"] = "If true, will check for online connection before going to the action file"
"""

# --- Standard Library ---
import textwrap, traceback

# --- Local Modules ---
from functions import (
    play_audio,
)
from starter import (
    speak,
    is_private,
    get_modules_path,
    check_internet,
    t,
)

command = None

def build_commands_api():
    api = {}

    for name, value in globals().items():
        # Skip private/internal names
        if name.startswith("_"):
            continue

        # Skip builtins
        if name in ("__builtins__",):
            continue

        api[name] = value

    return api

class ActionEnd(Exception):
    def __init__(self, *values):
        self.values = values

def end(*values):
    raise ActionEnd(*values)

def perform_action(logic):
    global command
    command = logic

    if command["attributes"]["notify"] is True:
        play_audio(systemsound="notification", wait=False)

    if command["attributes"]["online"] and not check_internet():
        speak(t.t("report.no_connection"))
        return

    modules_path = get_modules_path()

    command_file = modules_path / f"Actions/{command["intent"]}.py"

    if not command_file.exists():
        if not is_private():
            print(f"[ACTION FILE ERROR]: {command_file}")
        speak(t.t("report.unknown_command"))
        return
    
    print(t.t("report.performing"))

    code = command_file.read_text()

    wrapped_code = (
        "def __action__(entities):\n"
        + textwrap.indent(code, "    ")
    )

    exec_namespace = {
        "__name__": "__main__",
        "__file__": str(command_file)
    }

    if is_private():
        command_file = "PRIVATE"

    # ---------- 1. Try loading the action file ----------
    try:
        exec(wrapped_code, exec_namespace)
    except Exception as e:
        # Developer-facing log
        if not is_private():
            print(f"[ACTION LOAD ERROR] {command_file}:\n{e}")

        # User-facing response
        speak(t.t("report.action_load_failed"))
        return

    # ---------- 2. Try running the action ----------

    action = exec_namespace.get("__action__")
    if not callable(action):
        speak(t.t("report.action_run_failed"))
        print(f"[ACTION ERROR] {command_file}: __action__ not callable")
        return
    try:
        result = exec_namespace["__action__"](command["entities"])
    except ActionEnd as e:
        if len(e.values) == 0:
            result = None
        elif len(e.values) == 1:
            result = e.values[0]
        else:
            result = e.values  # tuple, just like return
    except Exception as e:
        if not is_private():
            print(f"[ACTION RUNTIME ERROR] in {command_file}")
            traceback.print_exc()

        speak(t.t("report.action_run_failed"))
        return

    # ---------- 3. Handle action result ----------
    if not result:
        return
    elif result == "SUCCESS":
        return
    elif result == "FAILED":
        speak(t.t("report.unable_to_understand"))
        return
    return