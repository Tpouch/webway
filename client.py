#!/usr/bin/env python3
"""Client de chat TCP avec interface TUI curses : participants à gauche, chat à droite, saisie en bas."""
import curses
import json
import locale
import socket
import sys
import threading
import time
from collections import deque

MAX_HISTORY = 500

HEADER_PAIR = 1
BORDER_PAIR = 2
SYSTEM_PAIR = 3
INFO_PAIR = 4
INPUT_OK_PAIR = 5
INPUT_ERR_PAIR = 6
SELF_PAIR = 7
USER_COLOR_BASE = 10


class ChatState:
    def __init__(self, username, host, port):
        self.lock = threading.Lock()
        self.username = username
        self.host = host
        self.port = port
        self.messages = deque(maxlen=MAX_HISTORY)
        self.users = []
        self.dirty = True
        self.connected = True
        self.status = ""

    def add_message(self, entry):
        with self.lock:
            self.messages.append(entry)
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
        state.add_message(("msg", ts, msg["username"], msg["text"]))
    elif mtype == "join":
        state.add_message(("system", ts, msg["username"], "a rejoint le chat"))
    elif mtype == "leave":
        state.add_message(("system", ts, msg["username"], "a quitté le chat"))
    elif mtype == "userlist":
        state.set_users(msg.get("users", []))
    elif mtype == "welcome":
        state.add_message(("info", ts, msg["username"], "connecté"))


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


def setup_colors():
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK

    curses.init_pair(HEADER_PAIR, curses.COLOR_CYAN, bg)
    curses.init_pair(BORDER_PAIR, curses.COLOR_BLUE, bg)
    curses.init_pair(SYSTEM_PAIR, curses.COLOR_YELLOW, bg)
    curses.init_pair(INFO_PAIR, curses.COLOR_CYAN, bg)
    curses.init_pair(INPUT_OK_PAIR, curses.COLOR_GREEN, bg)
    curses.init_pair(INPUT_ERR_PAIR, curses.COLOR_RED, bg)
    curses.init_pair(SELF_PAIR, curses.COLOR_GREEN, bg)

    hues = [
        curses.COLOR_RED, curses.COLOR_GREEN, curses.COLOR_YELLOW,
        curses.COLOR_BLUE, curses.COLOR_MAGENTA, curses.COLOR_CYAN,
        curses.COLOR_WHITE,
    ]
    for i, hue in enumerate(hues):
        curses.init_pair(USER_COLOR_BASE + i, hue, bg)


def color_for_username(name):
    if not curses.has_colors():
        return curses.A_NORMAL
    idx = sum(ord(c) for c in name) % 7
    return curses.color_pair(USER_COLOR_BASE + idx)


def draw_box(stdscr, y, x, h, w, attr=0, title=None):
    if h < 2 or w < 2:
        return
    try:
        stdscr.attron(attr)
        stdscr.hline(y, x + 1, curses.ACS_HLINE, w - 2)
        stdscr.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2)
        stdscr.vline(y + 1, x, curses.ACS_VLINE, h - 2)
        stdscr.vline(y + 1, x + w - 1, curses.ACS_VLINE, h - 2)
        stdscr.addch(y, x, curses.ACS_ULCORNER)
        stdscr.addch(y, x + w - 1, curses.ACS_URCORNER)
        stdscr.addch(y + h - 1, x, curses.ACS_LLCORNER)
        stdscr.attroff(attr)
        stdscr.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
    except curses.error:
        pass
    if title:
        label = f" {title} "[: max(0, w - 4)]
        try:
            stdscr.addstr(y, x + 2, label, attr | curses.A_BOLD)
        except curses.error:
            pass


def format_message(entry, width, own_username):
    kind, ts, username, text = entry
    if kind == "system":
        full = f"[{ts}] * {username} {text}"
        pair = curses.color_pair(SYSTEM_PAIR)
    elif kind == "info":
        full = f"[{ts}] {text} en tant que {username}"
        pair = curses.color_pair(INFO_PAIR)
    else:
        full = f"[{ts}] {username}: {text}"
        pair = color_for_username(username)

    lines = wrap_line(full, width)
    result = []
    for i, line in enumerate(lines):
        extra = curses.A_BOLD if (kind == "msg" and i == 0) else 0
        result.append((line, pair | extra))
    return result


def draw(stdscr, state, input_buf):
    height, width = stdscr.getmaxyx()
    left_width = max(18, width // 4)
    input_h = 3
    main_top = 1
    main_h = max(3, height - main_top - input_h)

    stdscr.erase()

    with state.lock:
        users = list(state.users)
        messages = list(state.messages)
        status = state.status
        connected = state.connected
        username = state.username
        host, port = state.host, state.port

    # Header
    dot = "●" if connected else "○"
    dot_pair = curses.color_pair(INPUT_OK_PAIR) if connected else curses.color_pair(INPUT_ERR_PAIR)
    header = f" chat-tui — {username}@{host}:{port} "
    try:
        stdscr.addstr(0, 0, header[:width], curses.color_pair(HEADER_PAIR) | curses.A_BOLD)
        stdscr.addstr(0, max(0, width - 2), dot, dot_pair | curses.A_BOLD)
    except curses.error:
        pass

    border_attr = curses.color_pair(BORDER_PAIR)

    # Participants panel
    draw_box(stdscr, main_top, 0, main_h, left_width, border_attr, "Participants")
    for i, user in enumerate(users):
        row = main_top + 1 + i
        if row >= main_top + main_h - 1:
            break
        is_self = user == username
        label = f" ★ {user} (vous)" if is_self else f" • {user}"
        attr = (curses.color_pair(SELF_PAIR) | curses.A_BOLD) if is_self else color_for_username(user)
        try:
            stdscr.addstr(row, 1, label[: left_width - 2], attr)
        except curses.error:
            pass

    # Chat panel
    chat_x = left_width
    chat_w = max(1, width - chat_x)
    draw_box(stdscr, main_top, chat_x, main_h, chat_w, border_attr, "Chat")
    content_x = chat_x + 2
    content_w = max(1, chat_w - 3)
    content_h = max(0, main_h - 2)

    rendered = []
    for entry in messages:
        rendered.extend(format_message(entry, content_w, username))
    visible = rendered[-content_h:] if content_h > 0 else []
    for i, (line, attr) in enumerate(visible):
        try:
            stdscr.addstr(main_top + 1 + i, content_x, line[:content_w], attr)
        except curses.error:
            pass

    # Input bar
    bar_y = main_top + main_h
    bar_attr = curses.color_pair(INPUT_OK_PAIR) if connected else curses.color_pair(INPUT_ERR_PAIR)
    draw_box(stdscr, bar_y, 0, input_h, width, bar_attr, "Message" if connected else "Déconnecté")
    label = status if not connected else f"> {input_buf}"
    try:
        stdscr.addstr(bar_y + 1, 2, label[: width - 4], curses.A_NORMAL if connected else curses.color_pair(INPUT_ERR_PAIR))
    except curses.error:
        pass

    stdscr.refresh()


def main(stdscr, host, port, username):
    locale.setlocale(locale.LC_ALL, "")
    curses.curs_set(1)
    stdscr.timeout(100)
    setup_colors()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.sendall((json.dumps({"type": "join", "username": username}) + "\n").encode("utf-8"))

    state = ChatState(username, host, port)
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
