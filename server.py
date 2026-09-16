#!/usr/bin/env python3
"""Serveur de chat TCP : messages, actions, réactions, frappe en direct, historique et bot."""
import itertools
import json
import random
import socket
import sys
import threading
import time
from collections import deque

HOST = "0.0.0.0"
LOCK = threading.Lock()
CLIENTS = {}  # socket -> {"name": pseudo, "hue": int 0-6}
HISTORY = deque(maxlen=200)  # derniers évènements rejoués aux nouveaux venus
NUM_HUES = 7
SEQ = itertools.count(1)
START_TIME = time.time()
STATS = {"messages": 0, "connexions": 0, "reactions": 0}

BOT_NAME = "bot"
BOT_QUIPS = [
    "je suis là, je surveille les octets.",
    "42. La question, je l'ai oubliée.",
    "quelqu'un a dit paquet TCP ? j'accours.",
    "toujours en ligne, contrairement à ton wifi.",
    "j'ai compté les messages : beaucoup.",
    "ping ? pong.",
    "je ne dors jamais, je suis un thread daemon.",
]


def default_hue(name):
    return sum(ord(c) for c in name) % NUM_HUES


def send_json(sock, payload):
    try:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        pass


def broadcast(payload, exclude=None, remember=False):
    if remember:
        HISTORY.append(payload)
    with LOCK:
        targets = [s for s in CLIENTS if s is not exclude]
    for s in targets:
        send_json(s, payload)


def unique_username(name):
    with LOCK:
        taken = {info["name"] for info in CLIENTS.values()}
    if name not in taken:
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    return f"{name}_{i}"


def userlist_payload():
    with LOCK:
        users = sorted(CLIENTS.values(), key=lambda info: info["name"])
    return {"type": "userlist", "users": users}


def bot_reply(text):
    """Le bot répond avec un petit délai pour faire vivre le salon."""
    quip = random.choice(BOT_QUIPS)
    if "?" in text:
        quip = random.choice(["bonne question.", "aucune idée, mais avec assurance : oui.", quip])

    def _say():
        broadcast(
            {"type": "msg", "id": next(SEQ), "username": BOT_NAME, "text": quip, "ts": time.time()},
            remember=True,
        )

    threading.Timer(0.6, _say).start()


def handle_client(conn, addr):
    conn_file = conn.makefile("r", encoding="utf-8")
    username = None
    try:
        first_line = conn_file.readline()
        if not first_line:
            return
        join_msg = json.loads(first_line)
        requested = (join_msg.get("username") or "anonyme").strip() or "anonyme"
        username = unique_username(requested)
        hue = default_hue(username)

        with LOCK:
            CLIENTS[conn] = {"name": username, "hue": hue}
            STATS["connexions"] += 1

        send_json(conn, {"type": "welcome", "username": username, "hue": hue, "ts": time.time()})
        send_json(conn, {"type": "history", "items": list(HISTORY)})
        broadcast({"type": "join", "username": username, "ts": time.time()}, remember=True)
        broadcast(userlist_payload())

        for line in conn_file:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")

            if mtype in ("msg", "action"):
                text = str(msg.get("text", ""))[:1000]
                if not text:
                    continue
                with LOCK:
                    STATS["messages"] += 1
                broadcast(
                    {"type": mtype, "id": next(SEQ), "username": username, "text": text, "ts": time.time()},
                    remember=True,
                )
                if mtype == "msg" and "@bot" in text.lower():
                    bot_reply(text)

            elif mtype == "typing":
                broadcast(
                    {"type": "typing", "username": username, "state": bool(msg.get("state"))},
                    exclude=conn,
                )

            elif mtype == "reaction":
                mid = msg.get("id")
                emoji = str(msg.get("emoji", ""))[:2]
                if isinstance(mid, int) and emoji:
                    with LOCK:
                        STATS["reactions"] += 1
                    broadcast(
                        {"type": "reaction", "id": mid, "emoji": emoji, "username": username},
                        remember=True,
                    )

            elif mtype == "color":
                new_hue = msg.get("hue")
                if isinstance(new_hue, int) and 0 <= new_hue < NUM_HUES:
                    with LOCK:
                        if conn in CLIENTS:
                            CLIENTS[conn]["hue"] = new_hue
                    broadcast(userlist_payload())

            elif mtype == "ping":
                send_json(conn, {"type": "pong", "t": msg.get("t")})

            elif mtype == "stats":
                with LOCK:
                    snapshot = dict(STATS)
                    online = len(CLIENTS)
                snapshot.update({"type": "stats", "uptime": time.time() - START_TIME, "online": online})
                send_json(conn, snapshot)
    except (ConnectionResetError, OSError, json.JSONDecodeError):
        pass
    finally:
        with LOCK:
            CLIENTS.pop(conn, None)
        if username:
            broadcast({"type": "typing", "username": username, "state": False})
            broadcast({"type": "leave", "username": username, "ts": time.time()}, remember=True)
            broadcast(userlist_payload())
        conn.close()


DEFAULT_PORT = 5555  # 5000/7000 sont pris par ControlCenter (AirPlay Receiver) sur macOS


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, port))
    except OSError as e:
        print(f"Impossible d'utiliser le port {port} ({e}). Choisis un autre port : python3 server.py <port>")
        sys.exit(1)
    server.listen()
    print(f"Serveur en écoute sur {HOST}:{port} (Ctrl+C pour arrêter)")

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
