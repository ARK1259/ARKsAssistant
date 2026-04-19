from action_configuration import command, end
from config_utils import (
    get_config_entry,
)
from functions import (
    get_weather_wapi,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

city_id, city_name = next(iter(entities["city"].items()))
unit = entities.get("temp_unit", {})

if not unit:
    unit = get_config_entry("temperature_unit", default=None, value_type=str)

if city_id is None or city_id == (None, None):
    end("FAILED")

get_weather_wapi(city_id, city_name, unit)