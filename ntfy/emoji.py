from typing import List, Tuple

from mautrix.util.logging import TraceLogger

try:
    import emoji
    WHITE_CHECK_MARK = emoji.emojize(":white_check_mark:")
except ImportError:
    emoji = None
    WHITE_CHECK_MARK = "✅"


def parse_tags(log: TraceLogger, tags: List[str]) -> Tuple[List[str], List[str]]:
    if emoji is None:
        log.warn("Please install the `emoji` package for emoji support")
        return ([], tags)
    emojis = []
    non_emoji_tags = []

    for tag in tags:
        emojized = emoji.emojize(f":{tag}:")
        if emoji.is_emoji(emojized):
            emojis.append(emojized)
        else:
            non_emoji_tags.append(tag)
    return (emojis, non_emoji_tags)
