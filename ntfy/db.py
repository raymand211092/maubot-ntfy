from __future__ import annotations

from typing import List, Tuple

import attr
from asyncpg import Record
from attr import dataclass
from mautrix.types import RoomID
from mautrix.util.async_db import Connection, Database, Scheme, UpgradeTable
from mautrix.util.logging import TraceLogger

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection, scheme: Scheme) -> None:
    gen = "GENERATED ALWAYS AS IDENTITY" if scheme != Scheme.SQLITE else ""
    await conn.execute(
        f"""CREATE TABLE topics (
            id INTEGER {gen},
            server TEXT NOT NULL,
            topic TEXT NOT NULL,
            last_event_id TEXT,

            PRIMARY KEY (id),
            UNIQUE (server, topic)
        )"""
    )
    await conn.execute(
        """CREATE TABLE subscriptions (
            topic_id INTEGER,
            room_id TEXT NOT NULL,

            PRIMARY KEY (topic_id, room_id),
            FOREIGN KEY (topic_id) REFERENCES topics (id)
        )"""
    )


@dataclass
class Topic:
    id: int
    server: str
    topic: str
    last_event_id: str

    subscriptions: List[Subscription] = attr.ib(factory=lambda: [])

    @classmethod
    def from_row(cls, row: Record | None) -> Topic | None:
        if not row:
            return None
        id = row["id"]
        server = row["server"]
        topic = row["topic"]
        last_event_id = row["last_event_id"]
        return cls(
            id=id,
            server=server,
            topic=topic,
            last_event_id=last_event_id,
            subscriptions=[]
        )


@dataclass
class Subscription:
    topic_id: int
    room_id: RoomID

    @classmethod
    def from_row(cls, row: Record | None) -> Topic | None:
        if not row:
            return None
        topic_id = row["topic_id"]
        room_id = row["room_id"]
        return cls(
            topic_id=topic_id,
            room_id=room_id,
        )


class DB:
    db: Database
    log: TraceLogger

    def __init__(self, db: Database, log: TraceLogger) -> None:
        self.db = db
        self.log = log

    async def get_topics(self) -> List[Topic]:
        query = """
        SELECT id, server, topic, last_event_id, topic_id, room_id
        FROM topics
        INNER JOIN
            subscriptions ON topics.id = subscriptions.topic_id
        """
        rows = await self.db.fetch(query)
        topics = {}
        for row in rows:
            try:
                topic = topics[row["id"]]
            except KeyError:
                topic = topics[row["id"]] = Topic.from_row(row)
            topic.subscriptions.append(Subscription.from_row(row))
        return list(topics.values())

    async def update_topic_id(self, topic_id: int, event_id: str) -> None:
        query = """
        UPDATE topics SET last_event_id=$2 WHERE id=$1
        """
        await self.db.execute(query, topic_id, event_id)

    async def create_topic(self, topic: Topic) -> Topic:
        query = """
        INSERT INTO topics (server, topic, last_event_id)
        VALUES ($1, $2, $3) RETURNING (id)
        """
        if self.db.scheme == Scheme.SQLITE:
            cur = await self.db.execute(
                query.replace("RETURNING (id)", ""),
                topic.server,
                topic.topic,
                topic.last_event_id,
            )
            topic.id = cur.lastrowid
        else:
            topic.id = await self.db.fetchval(
                query,
                topic.server,
                topic.topic,
                topic.last_event_id,
            )
        return topic

    async def get_topic(self, server: str, topic: str) -> Topic | None:
        query = """
        SELECT id, server, topic, last_event_id
        FROM topics
        WHERE server = $1 AND topic = $2
        """
        return Topic.from_row(await self.db.fetchrow(query, server, topic))

    async def get_subscription(self, topic_id: int, room_id: RoomID) -> Tuple[Subscription | None, Topic | None]:
        query = """
        SELECT id, server, topic, last_event_id, topic_id, room_id
        FROM topics
        INNER JOIN
            subscriptions ON topics.id = subscriptions.topic_id AND subscriptions.room_id = $2
        WHERE topics.id = $1
        """
        row = await self.db.fetchrow(query, topic_id, room_id)
        return (Subscription.from_row(row), Topic.from_row(row))

    async def get_subscriptions(self, topic_id: int) -> List[Subscription]:
        query = """
        SELECT topic_id, room_id
        FROM subscriptions
        WHERE topic_id = $1
        """
        rows = await self.db.fetch(query, topic_id)
        subscriptions = []
        for row in rows:
            subscriptions.append(Subscription.from_row(row))
        return subscriptions

    async def add_subscription(self, topic_id: int, room_id: RoomID) -> None:
        query = """
        INSERT INTO subscriptions (topic_id, room_id)
        VALUES ($1, $2)
        """
        await self.db.execute(query, topic_id, room_id)

    async def remove_subscription(self, topic_id: int, room_id: RoomID) -> None:
        query = """
        DELETE FROM subscriptions
        WHERE topic_id = $1 AND room_id = $2
        """
        await self.db.execute(query, topic_id, room_id)
