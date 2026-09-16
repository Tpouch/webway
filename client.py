#!/usr/bin/env python3
"""Client de chat TCP avec interface TUI curses : participants à gauche, chat à droite, saisie en bas."""
import curses
import json
import socket
import sys
import threading
import time
from collections import deque

MAX_HISTORY = 500


class ChatState:
    def __init__(self):
        self.lock = threading.Lock()
        self.messages = deque(maxlen=MAX_HISTORY)
        self.users = []
        self.dirty = True
        self.connected = True
        self.status = ""

    def add_message(self, line):
        with self.lock:
            self.messages.append(line)
            self.dirty = True

    def set_users(self, users):
        with self.lock:
            self.users = users
            self.dirty = True

    def set_status(self, status, connected=True):
        with self.lock:
            self.status = status
            self.connected = connected
            self.dirty = True


def network_thread(sock, state):
    conn_file = sock.makefile("r", encoding="utf-8")
    try:
        for line in conn_file:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            handle_server_message(msg, state)
    except OSError:
        pass
    finally:
        state.set_status("Connexion perdue. Appuie sur une touche pour quitter.", connected=False)


def handle_server_message(msg, state):
    mtype = msg.get("type")
    ts = time.strftime("%H:%M:%S", time.localtime(msg.get("ts", time.time())))
    if mtype == "msg":
        state.add_message(f"[{ts}] {msg['username']}: {msg['text']}")
    elif mtype == "join":
        state.add_message(f"[{ts}] * {msg['username']} a rejoint le chat")
    elif mtype == "leave":
        state.add_message(f"[{ts}] * {msg['username']} a quitté le chat")
    elif mtype == "userlist":
        state.set_users(msg.get("users", []))
    elif mtype == "welcome":
        state.add_message(f"[{ts}] Connecté en tant que {msg['username']}")


def wrap_line(text, width):
    if width <= 0:
        return [text]
    lines = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width)
        if cut <= 0:
            cut = width
        lines.append(text[:cut])
        text = text[cut:].lstrip()
    lines.append(text)
    return lines


def draw(stdscr, state, input_buf):
    height, width = stdscr.getmaxyx()
    left_width = max(18, width // 4)
    input_height = 3

    stdscr.erase()

    for y in range(height - input_height):
        try:
            stdscr.addch(y, left_width, curses.ACS_VLINE)
        except curses.error:
            pass

    with state.lock:
        users = list(state.users)
        messages = list(state.messages)
        status = state.status
        connected = state.connected

    stdscr.addstr(0, 0, " Participants".ljust(left_width)[:left_width], curses.A_BOLD)
    for i, user in enumerate(users):
        row = 1 + i
        if row >= height - input_height:
            break
        try:
            stdscr.addstr(row, 0, f" {user}"[:left_width])
        except curses.error:
            pass

    chat_x = left_width + 1
    chat_width = max(1, width - chat_x)
    chat_height = height - input_height
    wrapped = []
    for line in messages:
        wrapped.extend(wrap_line(line, chat_width))
    visible = wrapped[-chat_height:] if chat_height > 0 else []
    for i, line in enumerate(visible):
        try:
            stdscr.addstr(i, chat_x, line[:chat_width])
        except curses.error:
            pass

    bar_y = height - input_height
    try:
        stdscr.hline(bar_y, chat_x, curses.ACS_HLINE, chat_width)
    except curses.error:
        pass
    prompt = "> "
    label = status if not connected else prompt + input_buf
    try:
        stdscr.addstr(bar_y + 1, chat_x, label[:chat_width])
    except curses.error:
        pass

    stdscr.refresh()


def main(stdscr, host, port, username):
    curses.curs_set(1)
    stdscr.timeout(100)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.sendall((json.dumps({"type": "join", "username": username}) + "\n").encode("utf-8"))

    state = ChatState()
    threading.Thread(target=network_thread, args=(sock, state), daemon=True).start()

    input_buf = ""
    while True:
        with state.lock:
            dirty = state.dirty
            state.dirty = False
            connected = state.connected
        if dirty:
            draw(stdscr, state, input_buf)

        ch = stdscr.getch()
        if ch == -1:
            continue
        if not connected:
            break

        if ch in (curses.KEY_ENTER, 10, 13):
            text = input_buf.strip()
            input_buf = ""
            if text:
                try:
                    sock.sendall((json.dumps({"type": "msg", "text": text}) + "\n").encode("utf-8"))
                except OSError:
                    state.set_status("Connexion perdue. Appuie sur une touche pour quitter.", connected=False)
            draw(stdscr, state, input_buf)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            input_buf = input_buf[:-1]
            draw(stdscr, state, input_buf)
        elif ch == curses.KEY_RESIZE:
            draw(stdscr, state, input_buf)
        elif 32 <= ch < 256:
            input_buf += chr(ch)
            draw(stdscr, state, input_buf)

    sock.close()


def run():
    if len(sys.argv) != 4:
        print("Usage: python3 client.py <ip> <port> <pseudo>")
        sys.exit(1)
    host = sys.argv[1]
    port = int(sys.argv[2])
    username = sys.argv[3]
    curses.wrapper(main, host, port, username)


if __name__ == "__main__":
    run()
