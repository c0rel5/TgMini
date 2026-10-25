# Пример плагина. Напишите в любом чате "!ping" — получите "pong #N".
META = {
    "name": "Ping",
    "version": "1.0",
    "author": "tgmini",
    "permissions": ["read_messages", "send_messages", "storage"],
}


def setup(api):
    def on_msg(m):
        if m["out"] and m["text"].strip() == "!ping":
            n = api.get("count", 0) + 1
            api.set("count", n)
            api.send(m["chat_id"], "pong #%d" % n)

    api.on_message(on_msg)
