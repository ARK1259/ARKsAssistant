from action_configuration import command, end
from starter import (
    speak,
    is_private,
    t,
)
from functions import (
    resolve_single_action,
    send_music_command,
    set_system_volume,
    input_keyboard,
    play_audio,
    play_video,
)

intent = command["intent"]
keyword = command["keyword"]
entities = command["entities"]

CONTROL_ACTIONS = {
    "volume_controls": {
        "music": lambda n: send_music_command("volume", n),
        "system": lambda n: set_system_volume(n),
        "needs_number": True,
    },
    "continue_controls": {
        "music": lambda _: send_music_command("play"),
        "system": lambda _: input_keyboard("play/pause media"),
    },
    "pause_controls": {
        "music": lambda _: send_music_command("pause"),
        "system": lambda _: input_keyboard("stop media"),
    },
    "toggle_controls": {
        "music": lambda _: send_music_command("toggle-play"),
        "system": lambda _: input_keyboard("play/pause media"),
    },
    "next_controls": {
        "music": lambda _: send_music_command("next"),
        "system": lambda _: input_keyboard("next track"),
    },
    "previous_controls": {
        "music": lambda _: send_music_command("previous"),
        "system": lambda _: input_keyboard("previous track"),
    },
}
CONTROL_FILES = {
    "video_files": lambda video_name, video_path: play_video(video_name, video_path),
    "audio_files": lambda audio_name, audio_path: play_audio(audio_name, audio_path),
}

music = bool(keyword == "music")

control = resolve_single_action(entities, CONTROL_ACTIONS)
if not control:
    end("FAILED")

action = CONTROL_ACTIONS[control]

if keyword in ("video", "audio"):
    media_type = "video_files" if keyword == "video" else "audio_files"
    if not media_type:
        end("FAILED")

    media_path, media_name = next(iter(entities[media_type].items()))
    if media_path:
        if not is_private():
            print(f"type: {media_type}, id: {media_name}, path: {media_path}")

        speak(t.t("prompts.playing_media", name=media_name, type=keyword))
        CONTROL_FILES[media_type](media_name, media_path)
        end()
    else:
        speak(t.t("report.file_not_located", name=media_name))
        end("FAILED")

# Volume requires a number
if action.get("needs_number"):
    number = entities.get("number")
    if number is None:
        end("FAILED")
else:
    number = None

executor = action["music"] if music else action["system"]
executor(number)
