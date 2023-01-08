from types import SimpleNamespace
from typing import List, Tuple

from mautrix.util.logging import TraceLogger

try:
    import emoji
except ImportError:
    # basic list of supported emoji, based on https://docs.ntfy.sh/publish/#tags-emojis
    emoji_dict = {
        "+1": "👍",
        "-1": "👎️",
        "facepalm": "🤦",
        "partying_face": "🥳",
        "warning": "⚠️",
        "no_entry": "⛔",
        "tada": "🎉",
        "rotating_light": "🚨",
        "no_entry_sign": "🚫",
        "heavy_check_mark": "✔️",
        "triangular_flag_on_post": "🚩",
        "cd": "💿",
        "loudspeaker": "📢",
        "skull": "💀",
        "computer": "💻",
        "white_check_mark": "✅",
    }
    emoji = SimpleNamespace()
    emoji.emojize = lambda e: emoji_dict.get(e[1:-1], e)
    emoji.is_emoji = lambda e: e in emoji_dict.values()

WHITE_CHECK_MARK = emoji.emojize(":white_check_mark:")


def parse_tags(log: TraceLogger, tags: List[str]) -> Tuple[List[str], List[str]]:
    if emoji is None:
        log.warn("Please install the `emoji` package for full emoji support")
    emojis = []
    non_emoji_tags = []

    for tag in tags:
        emojized = emoji.emojize(f":{tag}:")
        if emoji.is_emoji(emojized):
            emojis.append(emojized)
        else:
            non_emoji_tags.append(tag)
    return (emojis, non_emoji_tags)
