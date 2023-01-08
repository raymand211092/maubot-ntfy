import asyncio
import html
import json
from typing import Any, List, Tuple

from aiohttp import ClientTimeout
from maubot import MessageEvent, Plugin
from maubot.handlers import command
from mautrix.types import (EventType, Format, MessageType,
                           TextMessageEventContent)
from mautrix.util.async_db import UpgradeTable
from mautrix.util.config import BaseProxyConfig
from mautrix.util.formatter import parse_html

from .config import Config
from .db import DB, Topic, upgrade_table
from .emoji import parse_tags, WHITE_CHECK_MARK


class NtfyBot(Plugin):
    db: DB
    config: Config
    tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        await super().start()
        self.config.load_and_update()
        self.db = DB(self.database, self.log)
        await self.resubscribe()

    async def stop(self) -> None:
        await super().stop()
        await self.clear_subscriptions()

    async def on_external_config_update(self) -> None:
        self.log.info("Refreshing configuration")
        self.config.load_and_update()

    async def resubscribe(self) -> None:
        await self.clear_subscriptions()
        await self.subscribe_to_topics()

    async def clear_subscriptions(self) -> None:
        tasks = self.tasks[:]
        if not tasks:
            return None

        for task in tasks:
            if not task.done():
                self.log.debug("cancelling subscription task...")
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self.log.exception("Subscription task errored", exc_info=exc)
        self.tasks[:] = []

    async def can_use_command(self, evt: MessageEvent) -> bool:
        if evt.sender in self.config["admins"]:
            return True
        levels = await self.client.get_state_event(evt.room_id, EventType.ROOM_POWER_LEVELS)
        user_level = levels.get_user_level(evt.sender)
        if user_level < 50:
            await evt.reply("You don't have the permission to manage ntfy subscriptions in this room.")
            return False
        return True

    @command.new(name=lambda self: self.config["command_prefix"], help="Manage ntfy subscriptions.", require_subcommand=True)
    async def ntfy(self) -> None:
        pass

    @ntfy.subcommand("subscribe", aliases=("sub"), help="Subscribe this room to a ntfy topic.")
    @command.argument("topic", "topic URL", matches="(([a-zA-Z0-9-]{1,63}\\.)+[a-zA-Z]{2,6}/[a-zA-Z0-9_-]{1,64})")
    async def subscribe(self, evt: MessageEvent, topic: Tuple[str, Any]) -> None:
        # see https://github.com/binwiederhier/ntfy/blob/82df434d19e3ef45ada9c00dfe9fc0f8dfba15e6/server/server.go#L61 for the valid topic regex
        if not await self.can_use_command(evt):
            return None
        server, topic = topic[0].split("/")
        db_topic = await self.db.get_topic(server, topic)
        if not db_topic:
            db_topic = await self.db.create_topic(Topic(id=-1, server=server, topic=topic, last_event_id=None))
        existing_subscriptions = await self.db.get_subscriptions(db_topic.id)
        sub, _ = await self.db.get_subscription(db_topic.id, evt.room_id)
        if sub:
            await evt.reply("This room is already subscribed to %s/%s", server, topic)
        else:
            await self.db.add_subscription(db_topic.id, evt.room_id)
            await evt.reply("Subscribed this room to %s/%s", server, topic)
            await evt.react(WHITE_CHECK_MARK)
            if not existing_subscriptions:
                await self.subscribe_to_topic(db_topic)

    @ntfy.subcommand("unsubscribe", aliases=("unsub"), help="Unsubscribe this room from a ntfy topic.")
    @command.argument("topic", "topic URL", matches="(([a-zA-Z0-9-]{1,63}\\.)+[a-zA-Z]{2,6}/[a-zA-Z0-9_-]{1,64})")
    async def unsubscribe(self, evt: MessageEvent, topic: Tuple[str, Any]) -> None:
        # see https://github.com/binwiederhier/ntfy/blob/82df434d19e3ef45ada9c00dfe9fc0f8dfba15e6/server/server.go#L61 for the valid topic regex
        if not await self.can_use_command(evt):
            return None
        server, topic = topic[0].split("/")
        db_topic = await self.db.get_topic(server, topic)
        if not db_topic:
            await evt.reply("This room is not subscribed to %s/%s", server, topic)
            return
        sub, _ = await self.db.get_subscription(db_topic.id, evt.room_id)
        if not sub:
            await evt.reply("This room is not subscribed to %s/%s", server, topic)
            return
        await self.db.remove_subscription(db_topic.id, evt.room_id)
        await evt.reply("Unsubscribed this room from %s/%s", server, topic)
        await evt.react(WHITE_CHECK_MARK)

    async def subscribe_to_topics(self) -> None:
        topics = await self.db.get_topics()
        for topic in topics:
            await self.subscribe_to_topic(topic)

    async def subscribe_to_topic(self, topic: Topic) -> None:
        def log_task_exc(task: asyncio.Task) -> None:
            if task.done() and not task.cancelled():
                exc = task.exception()
                self.log.exception(
                    "Subscription task errored", exc_info=exc)
                # TODO: restart subscription#

        self.log.info("Subscribing to %s/%s", topic.server, topic.topic)
        url = "%s/%s/json" % (topic.server, topic.topic)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if topic.last_event_id:
            url += "?since=%s" % topic.last_event_id

        self.log.debug("Subscribing to URL %s", url)
        task = self.loop.create_task(
            self.run_topic_subscription(topic, url))
        self.tasks.append(task)
        task.add_done_callback(self.tasks.remove)
        task.add_done_callback(log_task_exc)

    async def run_topic_subscription(self, topic: Topic, url: str) -> None:
        async with self.http.get(url, timeout=ClientTimeout()) as resp:
            while True:
                line = await resp.content.readline()
                # convert to string and remove trailing newline
                line = line.decode("utf-8").strip()
                self.log.debug("Received notification: %s", line)
                message = json.loads(line)
                if message["event"] != "message":
                    continue
                # persist the received message id
                await self.db.update_topic_id(topic.id, message["id"])

                # build matrix message
                html_content = self.build_message_content(
                    topic.server, message)
                text_content = await parse_html(html_content.strip())

                content = TextMessageEventContent(
                    msgtype=MessageType.TEXT,
                    format=Format.HTML,
                    formatted_body=html_content,
                    body=text_content,
                )

                subscriptions = await self.db.get_subscriptions(topic.id)
                for sub in subscriptions:
                    try:
                        await self.client.send_message(sub.room_id, content)
                    except Exception as exc:
                        self.log.exception(
                            "Failed to send matrix message!", exc_info=exc)

    def build_message_content(self, server: str, message) -> str:
        topic = message["topic"]
        body = message["message"]
        title = message.get("title", None)
        tags = message.get("tags", None)
        click = message.get("click", None)
        attachment = message.get("attachment", None)

        if tags:
            (emoji, non_emoji) = parse_tags(self.log, tags)
            emoji = "".join(emoji) + " "
            tags = ", ".join(non_emoji)
        else:
            emoji = tags = ""

        html_content = "<span>Ntfy message in topic <code>%s/%s</code></span><blockquote>" % (
            html.escape(server), html.escape(topic))
        # build title
        if title and click:
            html_content += "<h4>%s<a href=\"%s\">%s</a></h4>" % (
                emoji, html.escape(click), html.escape(title))
            emoji = ""
        elif title:
            html_content += "<h4>%s%s</h4>" % (emoji, html.escape(title))
            emoji = ""

        # build body
        if click and not title:
            html_content += "%s<a href=\"%s\">%s</a>" % (
                emoji, html.escape(click), html.escape(body).replace("\n", "<br />"))
        else:
            html_content += emoji + html.escape(body).replace("\n", "<br />")

        # add non-emoji tags
        if tags:
            html_content += "<br/><small>Tags: <code>%s</code></small>" % html.escape(
                tags)

        # build attachment
        if attachment:
            html_content += "<br/><a href=\"%s\">View %s</a>" % (html.escape(
                attachment["url"]), html.escape(attachment["name"]))
        html_content += "</blockquote>"

        return html_content

    @classmethod
    def get_config_class(cls) -> type[BaseProxyConfig]:
        return Config

    @classmethod
    def get_db_upgrade_table(cls) -> UpgradeTable | None:
        return upgrade_table
