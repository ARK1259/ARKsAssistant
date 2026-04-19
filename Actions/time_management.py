import locale
import time
from datetime import datetime

from action_configuration import command, end
from starter import (
    speak,
    t,
)
from functions import (
    add_timer
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

locale.setlocale(locale.LC_TIME, '')  # use system locale

now = datetime.now()

if keyword == "timer":
    number = entities["number"]
    unit_id, unit_name = next(iter(entities["time_unit"].items()))

    delay_seconds = int(number) * int(unit_id)
    trigger_at = int(time.time() + delay_seconds)

    add_timer(
        {
            "id": f"{number}_{unit_id}_{now}",
            "trigger_at": trigger_at,
            "message": "timer has been reached"
        }
    )
    speak(f"A {number} {unit_name} timer has been set!")
    end()

# Detect if locale uses AM/PM by checking if %p gives something meaningful
uses_ampm = bool(now.strftime('%p').strip())

if uses_ampm:
    hour = now.strftime('%I').lstrip('0')
    minute = now.minute
    ampm = now.strftime('%p')
    format = "A M" if ampm == "AM" else "P M"
    clock = f"{hour} {minute} {format}"
else:
    hour = now.strftime('%H')
    minute = now.minute
    clock = f"{hour} {minute}"

if keyword == "time":
    speak(t.t("report.time_is", clock=clock))

else:
    end("FAILED")