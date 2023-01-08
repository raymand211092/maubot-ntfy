# maubot-ntfy

This is a [maubot](https://maubot.xyz/) plugin to subscribe to [ntfy](https://ntfy.sh/) topics and send messages to a matrix room.

## Usage

Install as a maubot plugin and configure an instance. Until maubot supports installing python dependencies, you should install the `emoji` python package for full functionality. Alternatively, `@ntfy:catgirl.cloud` is available as well.

Use `!ntfy subscribe server/topic` (for example `!ntfy subscribe ntfy.sh/my_topic`) to subscribe the current room to the ntfy topic. Future messages will be sent to the room.

To unsubscribe, use `!ntfy unsubscribe server/topic`.
