from action_configuration import command, end
from functions import (
    resolve_single_action,
    get_crypto_info,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

CRYPTO_ACTIONS = {
    "crypto_action_price": lambda crypto_id, crypto_name: get_crypto_info(crypto_id, crypto_name, "price"),
    "crypto_action_trending": lambda : get_crypto_info(action = "trending"),
    "status_controls": lambda crypto_id, crypto_name: get_crypto_info(crypto_id, crypto_name, "status")
}

action_key = resolve_single_action(entities, CRYPTO_ACTIONS)
if not action_key:
    end("FAILED")

if action_key != "crypto_action_trending":
    crypto_id, crypto_name = next(iter(entities["crypto"].items()))
    CRYPTO_ACTIONS[action_key](crypto_id, crypto_name)
else:
    CRYPTO_ACTIONS[action_key]()