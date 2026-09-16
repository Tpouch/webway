#!/usr/bin/env python3
"""Serveur de chat TCP : diffuse les messages et la liste des participants à tous les clients connectés."""
import json
import socket
import sys
import threading
import time

HOST = "0.0.0.0"
LOCK = threading.Lock()
CLIENTS = {}  # socket -> pseudo


def send_json(sock, payload):
    try:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        pass


def broadcast(payload, exclude=None):
    with LOCK:
        targets = [s for s in CLIENTS if s is not exclude]
    for s in targets:
        send_json(s, payload)


def unique_username(name):
    with LOCK:
        taken = set(CLIENTS.values())
    if name not in taken:
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    return f"{name}_{i}"


def userlist_payload():
    with LOCK:
        names = sorted(CLIENTS.values())
    return {"type": "userlist", "users": names}


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

        with LOCK:
            CLIENTS[conn] = username

        send_json(conn, {"type": "welcome", "username": username})
        broadcast({"type": "join", "username": username, "ts": time.time()})
        broadcast(userlist_payload())

        for line in conn_file:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "msg":
                text = msg.get("text", "")
                if text:
                    broadcast({"type": "msg", "username": username, "text": text, "ts": time.time()})
    except (ConnectionResetError, OSError):
        pass
    finally:
        with LOCK:
            CLIENTS.pop(conn, None)
        if username:
            broadcast({"type": "leave", "username": username, "ts": time.time()})
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
