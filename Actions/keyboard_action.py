from pathlib import Path

from action_configuration import command, end
from starter import (
    speak,
    t,
)
from config_utils import (
    get_config_entry,
)
from functions import (
    resolve_single_action,
    input_keyboard,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

def type_message(message):
    try:
        input_keyboard(message, delay=0.01)
    except Exception as e:
        print(t.t("error.unexpected", e=e))
        end("FAILED")

def load_message_from_file(key_id):
    path = Path(key_id)

    # Check validity
    if not path.exists():
        return None
    if not path.is_file():
        return None

    # Optional: restrict to .txt files
    if path.suffix.lower() != ".txt":
        return None

    # Read contents
    try:
        content = path.read_text(encoding="utf-8")
    except:
        return None

    return str(content)

def find_text():
    key_id, key_value = next(iter(entities["text_files"].items()))
    if not key_id:
        speak(t.t("report.text_not_found", name=key_value))
        end()
    else:
        if load_message_from_file(key_id):
            type_message(load_message_from_file(key_id))
        else:
            type_message(key_id)

def type_preset():
    key_id, key_value = next(iter(entities["text_preset"].items()))
    if key_value == "poem":
        message = (
            "To see the world in a grain of sand"
            +"\nand a heaven in a wild flower"
            +"\nhold infinity in the palm of your hand"
            +"\nand eternity in an hour"
        )

    else:
        message = key_id

    type_message(message)
    end()
        
TEXT_DICT = {
    "text_preset": lambda: type_preset(),
    "text_files": lambda: find_text(),
}

if keyword == "screenshot":
    type_message("print screen")
    end()
elif keyword == "save":
    type_message(["ctrl", "s"])
    end()
elif keyword == "space":
    type_message("space")
    end()
elif keyword == "enter":
    type_message("enter")
    end()
elif keyword == "tab":
    type_message(["alt", "tab"])
    end()
else:
    action_key = resolve_single_action(entities, TEXT_DICT)
    if not action_key:
        end("FAILED")
    
    TEXT_DICT[action_key]()
    end()


