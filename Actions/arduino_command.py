from action_configuration import command, end
from starter import (
    speak,
    t,
)
from functions import (
    resolve_single_action,
    arduino_message,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

LIGHT_ACTIONS = {
    "state_on": lambda pin: arduino_message(f"{pin}:100"),
    "terminate_controls": lambda pin: arduino_message(f"{pin}:0"),
}
HUMID_ACTIONS = {
    "state_on": lambda : arduino_message(message="HUMID:ON"),
    "state_auto": lambda : arduino_message(message="HUMID:AUTO"),
    "terminate_controls": lambda : arduino_message(message="HUMID:OFF"),
}
HUMID_AUTO_ACTIONS = {
    "maximum_values": "HMAX:PRINT",
    "minimum_values": "HMIN:PRINT",
}

def get_hlimit(action_key):
    key = entities[action_key]
    message = HUMID_AUTO_ACTIONS[action_key]

    response = arduino_message(message=message, expect_response=True)
    raw_value = response[7:-3].strip()
    if not response or not raw_value:
        end("FAILED")
        
    return key, raw_value

def state_humidity():
    response = arduino_message(message="TELLHUMIDITY", expect_response=True)
    clear_response = response[:-1].strip()
    if not response:
        end("FAILED")
    speak(t.t("report.room_humidity", response=clear_response))
    return response

if keyword == "humidity":
    action_key = resolve_single_action(entities, HUMID_AUTO_ACTIONS)
    
    if action_key:
        key, raw_value = get_hlimit(action_key)
        speak(t.t("report.auto_humidity", limit=key, value=raw_value))
        end()

    humidity = state_humidity()
    end(humidity)

elif keyword == "set_humidity":
    action_key = resolve_single_action(entities, HUMID_AUTO_ACTIONS)
    if not action_key:
        end("FAILED")

    value = entities["number"]
    if 20 >= value or value >= 100:
        speak(t.t("arduino.wrong_limit"))
        end()

    limit = "HMAX" if action_key == "maximum_values" else "HMIN"

    command = (limit + ":" + str(value))
    response = arduino_message(message=command, expect_response=True)
    if response == "Cannot HMAX<HMIN!":
        speak(t.t("report.hlimit_fail"))
        end()

    key, raw_value = get_hlimit(action_key)
        
    speak(t.t("report.hlimit_set", limit=key, value=raw_value))
    end()

if keyword == "humidifier":
    action_key = resolve_single_action(entities, HUMID_ACTIONS)
    if not action_key:
        end("FAILED")
else:
    action_key = resolve_single_action(entities, LIGHT_ACTIONS)
    if not action_key:
        end("FAILED")
    section_id, section_name = next(iter(entities["light_section"].items()))
    pin = section_id

if keyword == "humidifier":
    HUMID_ACTIONS[action_key]()
else:
    LIGHT_ACTIONS[action_key](pin)