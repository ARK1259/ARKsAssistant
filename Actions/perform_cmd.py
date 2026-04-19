from action_configuration import command, end
from functions import (
    cmd_action,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

command, name = next(iter(entities["cmd_commands"].items()))

summarize = "report_controls" in entities
    
cmd_action(action=keyword, cmd=command, summarize=summarize)
