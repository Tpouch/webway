#!/usr/bin/env python3
"""Client de chat TCP : TUI curses animée (60 fps de bonheur, particules, pluie Matrix, toasts...)."""
import curses
import json
import locale
import math
import random
import socket
import sys
import threading
import time
from collections import deque

MAX_HISTORY = 800
FPS = 30
FRAME_MS = max(10, int(1000 / FPS))

# --- paires de couleurs -------------------------------------------------
HEADER_PAIR = 1
BORDER_PAIR = 2
SYSTEM_PAIR = 3
INFO_PAIR = 4
OK_PAIR = 5
ERR_PAIR = 6
SELF_PAIR = 7
ACCENT_PAIR = 8
DIM_PAIR = 9
USER_COLOR_BASE = 10
NUM_HUES = 7
RAINBOW_BASE = 20
MATRIX_PAIR = 56
MATRIX_HEAD_PAIR = 57

RAINBOW_N = 0
BG = -1

RAMP_256 = [196, 202, 208, 214, 220, 226, 190, 154, 118, 82, 46, 47, 48, 49, 50,
            51, 45, 39, 33, 27, 21, 57, 93, 129, 165, 201, 200, 199, 198, 197]

THEMES = [
    {"name": "Néon", "header": curses.COLOR_CYAN, "border": curses.COLOR_BLUE, "accent": curses.COLOR_MAGENTA},
    {"name": "Braise", "header": curses.COLOR_YELLOW, "border": curses.COLOR_RED, "accent": curses.COLOR_YELLOW},
    {"name": "Forêt", "header": curses.COLOR_GREEN, "border": curses.COLOR_GREEN, "accent": curses.COLOR_CYAN},
    {"name": "Rétro", "header": curses.COLOR_WHITE, "border": curses.COLOR_WHITE, "accent": curses.COLOR_YELLOW},
    {"name": "Bonbon", "header": curses.COLOR_MAGENTA, "border": curses.COLOR_MAGENTA, "accent": curses.COLOR_CYAN},
]

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
PULSE = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"
SPARKS = "▁▂▃▄▅▆▇█"
FADE_BLOCKS = "█▉▊▋▌▍▎▏"
CONFETTI_CHARS = "▛▜▟▙░▒▓◆◇★✦✧•"
FIREWORK_CHARS = "*✦✧·+×•"
MATRIX_CHARS = "01234567890ABCDEFGHJKLMNPQRSTUVWXYZ<>*+=-$#%&@"
REACTIONS = ["★", "♥", "☺", "⚡"]

LOGO = [
    " ██████ ██   ██  █████  ████████",
    "██      ██   ██ ██   ██    ██   ",
    "██      ███████ ███████    ██   ",
    "██      ██   ██ ██   ██    ██   ",
    " ██████ ██   ██ ██   ██    ██   ",
]

HELP_LINES = [
    ("Entrée", "Envoyer le message"),
    ("Tab", "Compléter un pseudo"),
    ("↑ / ↓", "Rappeler un message envoyé"),
    ("← / → / Home / End", "Déplacer le curseur"),
    ("Ctrl+W / Ctrl+U", "Effacer un mot / la ligne"),
    ("PgUp / PgDn", "Défiler l'historique"),
    ("Ctrl+K", "Changer de couleur"),
    ("Ctrl+T", "Changer de thème"),
    ("F2", "Pluie Matrix"),
    ("F3", "Mode arc-en-ciel"),
    ("F4", "Confettis"),
    ("F5..F8", "Réagir au dernier message (★ ♥ ☺ ⚡)"),
    ("F1", "Afficher/masquer cette aide"),
    ("/help", "Liste des commandes"),
    ("Ctrl+C", "Quitter"),
]

COMMAND_LINES = [
    "/me <texte>      action à la troisième personne",
    "/confetti        lâcher de confettis",
    "/fireworks       feu d'artifice",
    "/matrix          pluie Matrix on/off",
    "/rainbow         tes messages en arc-en-ciel",
    "/theme           thème de couleurs suivant",
    "/roll [NdM]      lancer de dés (défaut 1d6)",
    "/flip            pile ou face",
    "/shrug           ¯\\_(ツ)_/¯",
    "/users           qui est connecté",
    "/stats           statistiques du serveur",
    "/clear           vider l'affichage local",
    "/quit            quitter",
]


def default_hue(name):
    return sum(ord(c) for c in name) % NUM_HUES


# --- helpers curses -----------------------------------------------------
def _init_pair(idx, fg, bg):
    if idx >= curses.COLOR_PAIRS or fg >= curses.COLORS:
        return False
    try:
        curses.init_pair(idx, fg, bg)
        return True
    except curses.error:
        return False


def apply_theme(index):
    theme = THEMES[index % len(THEMES)]
    _init_pair(HEADER_PAIR, theme["header"], BG)
    _init_pair(BORDER_PAIR, theme["border"], BG)
    _init_pair(ACCENT_PAIR, theme["accent"], BG)
    return theme


def setup_colors(theme_index):
    global RAINBOW_N, BG
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        BG = -1
    except curses.error:
        BG = curses.COLOR_BLACK

    _init_pair(SYSTEM_PAIR, curses.COLOR_YELLOW, BG)
    _init_pair(INFO_PAIR, curses.COLOR_CYAN, BG)
    _init_pair(OK_PAIR, curses.COLOR_GREEN, BG)
    _init_pair(ERR_PAIR, curses.COLOR_RED, BG)
    _init_pair(SELF_PAIR, curses.COLOR_GREEN, BG)
    _init_pair(DIM_PAIR, curses.COLOR_BLUE, BG)
    apply_theme(theme_index)

    hues = [curses.COLOR_RED, curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_BLUE,
            curses.COLOR_MAGENTA, curses.COLOR_CYAN, curses.COLOR_WHITE]
    for i, hue in enumerate(hues):
        _init_pair(USER_COLOR_BASE + i, hue, BG)

    ramp = RAMP_256 if curses.COLORS >= 256 else [curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_GREEN,
                                                  curses.COLOR_CYAN, curses.COLOR_BLUE, curses.COLOR_MAGENTA]
    ok = 0
    for i, color in enumerate(ramp):
        if _init_pair(RAINBOW_BASE + i, color, BG):
            ok = i + 1
        else:
            break
    RAINBOW_N = ok

    _init_pair(MATRIX_PAIR, 28 if curses.COLORS >= 256 else curses.COLOR_GREEN, BG)
    _init_pair(MATRIX_HEAD_PAIR, 231 if curses.COLORS >= 256 else curses.COLOR_WHITE, BG)


def rainbow_attr(i):
    if RAINBOW_N <= 0:
        return curses.A_BOLD
    return curses.color_pair(RAINBOW_BASE + int(i) % RAINBOW_N)


def color_for_hue(hue):
    if not curses.has_colors():
        return curses.A_NORMAL
    return curses.color_pair(USER_COLOR_BASE + hue % NUM_HUES)


def put(win, y, x, text, attr=0):
    if y < 0 or x < 0 or not text:
        return
    h, w = win.getmaxyx()
    if y >= h or x >= w:
        return
    text = text[: w - x]
    if y == h - 1 and x + len(text) >= w:
        text = text[: w - x - 1]
    if not text:
        return
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def put_ch(win, y, x, ch, attr=0):
    h, w = win.getmaxyx()
    if not (0 <= y < h and 0 <= x < w) or (y == h - 1 and x == w - 1):
        return
    try:
        win.addstr(y, x, ch, attr)
    except curses.error:
        pass


def put_rainbow(win, y, x, text, offset=0.0, bold=True):
    extra = curses.A_BOLD if bold else 0
    for i, ch in enumerate(text):
        put_ch(win, y, x + i, ch, rainbow_attr(offset + i) | extra)


# --- animations ---------------------------------------------------------
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "char", "hue", "gravity")

    def __init__(self, x, y, vx, vy, life, char, hue, gravity=0.02):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max_life = life
        self.char, self.hue, self.gravity = char, hue, gravity

    def step(self, dt):
        self.x += self.vx * dt * 60
        self.y += self.vy * dt * 60
        self.vy += self.gravity * dt * 60
        self.life -= dt
        return self.life > 0


class MatrixColumn:
    __slots__ = ("x", "y", "speed", "length", "chars")

    def __init__(self, x, height):
        self.x = x
        self.y = random.uniform(-height, 0)
        self.speed = random.uniform(6.0, 22.0)
        self.length = random.randint(4, max(5, height - 2))
        self.chars = [random.choice(MATRIX_CHARS) for _ in range(self.length)]

    def step(self, dt, height):
        self.y += self.speed * dt
        if random.random() < 0.3:
            self.chars[random.randrange(self.length)] = random.choice(MATRIX_CHARS)
        if self.y - self.length > height:
            self.__init__(self.x, height)


# --- état ---------------------------------------------------------------
class ChatState:
    def __init__(self, username, host, port):
        self.lock = threading.RLock()
        self.username = username
        self.host = host
        self.port = port
        self.messages = deque(maxlen=MAX_HISTORY)
        self.users = []
        self.user_hues = {}
        self.user_seen = {}
        self.typing = {}          # pseudo -> timestamp du dernier "je tape"
        self.connected = False
        self.fatal = None
        self.status = "Connexion..."
        self.scroll_target = 0
        self.scroll_pos = 0.0
        self.show_help = False
        self.last_content_h = 0
        self.particles = []
        self.matrix = []
        self.matrix_on = False
        self.rainbow = False
        self.theme = 0
        self.toasts = []
        self.flash_until = 0.0
        self.latency = None
        self.activity = deque(maxlen=400)
        self.sock = None

    # -- messages
    def add(self, kind, user, text, ts=None, mid=None, animate=True):
        entry = {
            "id": mid, "kind": kind, "user": user, "text": text,
            "ts": time.strftime("%H:%M:%S", time.localtime(ts or time.time())),
            "born": time.time() if animate else 0.0, "reactions": {},
        }
        with self.lock:
            self.messages.append(entry)
            self.activity.append(time.time())
        return entry

    def add_reaction(self, mid, emoji):
        with self.lock:
            for entry in reversed(self.messages):
                if entry["id"] == mid:
                    entry["reactions"][emoji] = entry["reactions"].get(emoji, 0) + 1
                    entry["born"] = time.time()  # rejoue l'animation d'arrivée
                    return True
        return False

    def last_message_id(self):
        with self.lock:
            for entry in reversed(self.messages):
                if entry["id"] is not None:
                    return entry["id"]
        return None

    # -- users
    def set_users(self, users):
        now = time.time()
        with self.lock:
            self.users = [u["name"] for u in users]
            self.user_hues = {u["name"]: u["hue"] for u in users}
            for name in self.users:
                self.user_seen.setdefault(name, now)
            for name in list(self.user_seen):
                if name not in self.users:
                    self.user_seen.pop(name, None)

    def hue_for(self, name):
        with self.lock:
            return self.user_hues.get(name, default_hue(name))

    def set_own_hue(self, hue):
        with self.lock:
            self.user_hues[self.username] = hue

    # -- effets
    def toast(self, text, pair=ACCENT_PAIR):
        with self.lock:
            self.toasts.append({"text": text, "pair": pair, "born": time.time()})
            self.toasts = self.toasts[-5:]

    def confetti(self, w, h, n=110):
        with self.lock:
            for _ in range(n):
                self.particles.append(Particle(
                    random.uniform(0, w), random.uniform(-8, 1),
                    random.uniform(-0.3, 0.3), random.uniform(0.15, 0.7),
                    random.uniform(2.5, 6.0), random.choice(CONFETTI_CHARS),
                    random.randrange(max(1, RAINBOW_N or 6)), gravity=0.012))

    def firework(self, w, h, count=3):
        with self.lock:
            for _ in range(count):
                cx, cy = random.uniform(w * 0.2, w * 0.8), random.uniform(h * 0.15, h * 0.55)
                hue = random.randrange(max(1, RAINBOW_N or 6))
                for i in range(46):
                    angle = (i / 46) * math.tau + random.uniform(-0.05, 0.05)
                    speed = random.uniform(0.25, 0.75)
                    self.particles.append(Particle(
                        cx, cy, math.cos(angle) * speed * 1.9, math.sin(angle) * speed,
                        random.uniform(0.8, 1.8), random.choice(FIREWORK_CHARS),
                        hue + random.randint(0, 2), gravity=0.03))

    def flash(self, seconds=0.9):
        with self.lock:
            self.flash_until = time.time() + seconds

    def step_effects(self, dt, w, h):
        now = time.time()
        with self.lock:
            self.particles = [p for p in self.particles if p.step(dt) and p.y < h + 2]
            if len(self.particles) > 900:
                self.particles = self.particles[-900:]
            if self.matrix_on:
                if not self.matrix or len(self.matrix) != w:
                    self.matrix = [MatrixColumn(x, h) for x in range(w)]
                for col in self.matrix:
                    col.step(dt, h)
            self.toasts = [t for t in self.toasts if now - t["born"] < 3.4]
            self.typing = {n: t for n, t in self.typing.items() if now - t < 3.0}
            # défilement fluide
            delta = self.scroll_target - self.scroll_pos
            if abs(delta) < 0.35:
                self.scroll_pos = float(self.scroll_target)
            else:
                self.scroll_pos += delta * min(1.0, dt * 14)


# --- réseau -------------------------------------------------------------
def send(state, payload):
    sock = state.sock
    if sock is None:
        return
    try:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        state.connected = False
        state.status = "Connexion perdue. Appuie sur une touche pour quitter."


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
        state.connected = False
        state.status = "Connexion perdue. Appuie sur une touche pour quitter."


def handle_server_message(msg, state, replay=False):
    mtype = msg.get("type")
    ts = msg.get("ts")

    if mtype == "msg":
        state.add("msg", msg["username"], msg["text"], ts, msg.get("id"), animate=not replay)
        if not replay and msg["username"] != state.username:
            if state.username.lower() in msg["text"].lower():
                state.flash()
                state.toast(f"{msg['username']} t'a mentionné !", ERR_PAIR)
                try:
                    curses.beep()
                except curses.error:
                    pass
    elif mtype == "action":
        state.add("action", msg["username"], msg["text"], ts, msg.get("id"), animate=not replay)
    elif mtype == "join":
        state.add("system", msg["username"], "a rejoint le chat", ts, animate=not replay)
        if not replay:
            state.toast(f"→ {msg['username']} arrive", OK_PAIR)
    elif mtype == "leave":
        state.add("system", msg["username"], "a quitté le chat", ts, animate=not replay)
        if not replay:
            state.toast(f"← {msg['username']} part", SYSTEM_PAIR)
    elif mtype == "userlist":
        state.set_users(msg.get("users", []))
    elif mtype == "typing":
        with state.lock:
            if msg.get("state"):
                state.typing[msg["username"]] = time.time()
            else:
                state.typing.pop(msg["username"], None)
    elif mtype == "reaction":
        state.add_reaction(msg.get("id"), msg.get("emoji", "★"))
    elif mtype == "welcome":
        state.username = msg["username"]
        if isinstance(msg.get("hue"), int):
            state.set_own_hue(msg["hue"])
        state.add("info", msg["username"], "connecté", ts)
    elif mtype == "history":
        for item in msg.get("items", []):
            handle_server_message(item, state, replay=True)
    elif mtype == "pong":
        t = msg.get("t")
        if isinstance(t, (int, float)):
            state.latency = (time.time() - t) * 1000
    elif mtype == "stats":
        up = int(msg.get("uptime", 0))
        state.add("info", "serveur",
                  f"{msg.get('online', 0)} en ligne · {msg.get('messages', 0)} messages · "
                  f"{msg.get('reactions', 0)} réactions · uptime {up // 3600}h{(up % 3600) // 60:02d}")


# --- rendu --------------------------------------------------------------
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


def draw_box(win, y, x, h, w, attr=0, title=None, title_attr=None):
    if h < 2 or w < 2:
        return
    try:
        win.attron(attr)
        win.hline(y, x + 1, curses.ACS_HLINE, max(0, w - 2))
        win.hline(y + h - 1, x + 1, curses.ACS_HLINE, max(0, w - 2))
        win.vline(y + 1, x, curses.ACS_VLINE, max(0, h - 2))
        win.vline(y + 1, x + w - 1, curses.ACS_VLINE, max(0, h - 2))
        win.addch(y, x, curses.ACS_ULCORNER)
        win.addch(y, x + w - 1, curses.ACS_URCORNER)
        win.addch(y + h - 1, x, curses.ACS_LLCORNER)
        win.attroff(attr)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
    except curses.error:
        pass
    if title:
        label = f" {title} "[: max(0, w - 4)]
        put(win, y, x + 2, label, (title_attr if title_attr is not None else attr) | curses.A_BOLD)


def format_message(entry, width, state):
    kind, ts, user, text = entry["kind"], entry["ts"], entry["user"], entry["text"]
    if kind == "system":
        full, pair = f"[{ts}] ✦ {user} {text}", curses.color_pair(SYSTEM_PAIR)
    elif kind == "info":
        full, pair = f"[{ts}] ⓘ {user} {text}", curses.color_pair(INFO_PAIR)
    elif kind == "action":
        full = f"[{ts}] ✱ {user} {text}"
        pair = curses.color_pair(ACCENT_PAIR) | getattr(curses, "A_ITALIC", 0)
    else:
        full, pair = f"[{ts}] {user}: {text}", color_for_hue(state.hue_for(user))

    if entry["reactions"]:
        full += "  " + " ".join(f"{e}{n}" for e, n in entry["reactions"].items())

    lines = wrap_line(full, width)
    out = []
    for i, line in enumerate(lines):
        extra = curses.A_BOLD if (kind in ("msg", "action") and i == 0) else 0
        out.append((line, pair | extra))
    return out


def draw_matrix(win, state, y0, x0, h, w, now):
    with state.lock:
        columns = list(state.matrix)
    for col in columns:
        if not (0 <= col.x < w):
            continue
        for i, ch in enumerate(col.chars):
            y = int(col.y) - i
            if 0 <= y < h:
                if i == 0:
                    attr = curses.color_pair(MATRIX_HEAD_PAIR) | curses.A_BOLD
                elif i < 3:
                    attr = curses.color_pair(MATRIX_PAIR) | curses.A_BOLD
                else:
                    attr = curses.color_pair(MATRIX_PAIR) | curses.A_DIM
                put_ch(win, y0 + y, x0 + col.x, ch, attr)


def draw_particles(win, state, h, w):
    with state.lock:
        particles = list(state.particles)
    for p in particles:
        x, y = int(p.x), int(p.y)
        if 0 <= x < w and 1 <= y < h:
            attr = rainbow_attr(p.hue) | (curses.A_BOLD if p.life > p.max_life * 0.4 else curses.A_DIM)
            put_ch(win, y, x, p.char, attr)


def draw_toasts(win, state, w, now):
    with state.lock:
        toasts = list(state.toasts)
    for i, toast in enumerate(toasts[-4:]):
        age = now - toast["born"]
        slide = int(max(0.0, (0.22 - age) / 0.22) * 14)
        text = f"  {toast['text']}  "
        x = max(0, w - len(text) - 1 + slide)
        attr = curses.color_pair(toast["pair"]) | (curses.A_DIM if age > 2.6 else curses.A_BOLD | curses.A_REVERSE)
        put(win, 1 + i, x, text, attr)


def draw_sparkline(win, state, y, x, width, now):
    with state.lock:
        stamps = list(state.activity)
    if width <= 0:
        return
    buckets = [0] * width
    for t in stamps:
        age = now - t
        idx = width - 1 - int(age)
        if 0 <= idx < width:
            buckets[idx] += 1
    peak = max(buckets) or 1
    for i, value in enumerate(buckets):
        level = int(value / peak * (len(SPARKS) - 1)) if value else 0
        ch = SPARKS[level] if value else "·"
        attr = rainbow_attr(i + int(now * 6)) if value else curses.color_pair(DIM_PAIR) | curses.A_DIM
        put_ch(win, y, x + i, ch, attr)


def draw_help(win, y0, x0, h, w, border_attr, lines, title):
    body = [f"{k:<18} {v}" for k, v in lines] if isinstance(lines[0], tuple) else list(lines)
    box_w = min(w - 2, max(len(l) for l in body) + 4)
    box_h = min(h, len(body) + 2)
    if box_w < 6 or box_h < 3:
        return
    y = y0 + max(0, (h - box_h) // 2)
    x = x0 + max(0, (w - box_w) // 2)
    for row in range(y, y + box_h):
        put(win, row, x, " " * box_w)
    draw_box(win, y, x, box_h, box_w, border_attr | curses.A_BOLD, title)
    for i, line in enumerate(body[: box_h - 2]):
        put(win, y + 1 + i, x + 2, line[: box_w - 4], curses.A_BOLD if i % 2 == 0 else 0)


def draw(stdscr, state, input_buf, cursor, now, frame):
    h, w = stdscr.getmaxyx()
    stdscr.erase()

    left_w = max(20, min(30, w // 4))
    input_h = 3
    top = 1
    main_h = max(3, h - top - input_h)

    with state.lock:
        users = list(state.users)
        messages = list(state.messages)
        status = state.status
        connected = state.connected
        username = state.username
        host, port = state.host, state.port
        show_help = state.show_help
        typing = dict(state.typing)
        scroll = int(round(state.scroll_pos))
        rainbow = state.rainbow
        theme_name = THEMES[state.theme % len(THEMES)]["name"]
        latency = state.latency
        seen = dict(state.user_seen)

    border_attr = curses.color_pair(BORDER_PAIR)
    chat_x = left_w
    chat_w = max(4, w - chat_x)

    # --- fond animé (pluie Matrix sous le texte)
    if state.matrix_on:
        draw_matrix(stdscr, state, top + 1, chat_x + 1, main_h - 2, chat_w - 2, now)

    # --- en-tête animé
    title = "webway"
    put_rainbow(stdscr, 0, 1, title, offset=frame * 0.35)
    info = f" ▸ {username}@{host}:{port} "
    put(stdscr, 0, 1 + len(title), info, curses.color_pair(HEADER_PAIR) | curses.A_BOLD)
    spin = SPINNER[frame % len(SPINNER)]
    clock = time.strftime("%H:%M:%S")
    ping = f"{latency:.0f}ms" if latency is not None else "--"
    right = f"{spin} {theme_name} · {len(users)} co · {ping} · {clock} "
    put(stdscr, 0, max(0, w - len(right) - 2), right, curses.color_pair(ACCENT_PAIR) | curses.A_BOLD)
    dot_attr = curses.color_pair(OK_PAIR if connected else ERR_PAIR) | curses.A_BOLD
    pulse = PULSE[frame % len(PULSE)] if connected else "○"
    put_ch(stdscr, 0, max(0, w - 2), pulse, dot_attr)

    # --- panneau participants
    draw_box(stdscr, top, 0, main_h, left_w, border_attr, "Participants",
             curses.color_pair(ACCENT_PAIR))
    row = top + 1
    for user in users:
        if row >= top + main_h - 3:
            break
        is_self = user == username
        is_typing = user in typing
        fresh = now - seen.get(user, 0) < 2.5
        bullet = "✎" if is_typing else ("★" if is_self else "•")
        label = f" {bullet} {user}" + (" (vous)" if is_self else "")
        if is_self:
            attr = curses.color_pair(SELF_PAIR) | curses.A_BOLD
        else:
            attr = color_for_hue(state.hue_for(user))
        if is_typing:
            attr |= curses.A_BOLD if frame % 10 < 5 else curses.A_DIM
        if fresh and frame % 8 < 4:
            attr |= curses.A_REVERSE
        put(stdscr, row, 1, label[: left_w - 2], attr)
        row += 1

    spark_y = top + main_h - 2
    put(stdscr, spark_y - 1, 1, "activité"[: left_w - 2], curses.color_pair(DIM_PAIR) | curses.A_DIM)
    draw_sparkline(stdscr, state, spark_y, 1, left_w - 2, now)

    # --- panneau chat
    content_x = chat_x + 2
    content_w = max(1, chat_w - 4)
    content_h = max(0, main_h - 2)
    with state.lock:
        state.last_content_h = content_h

    rendered = []  # (texte, attr, âge, rainbow?)
    for entry in messages:
        age = now - entry["born"] if entry["born"] else 99.0
        is_mine_rainbow = rainbow and entry["user"] == username and entry["kind"] in ("msg", "action")
        for line, attr in format_message(entry, content_w, state):
            rendered.append((line, attr, age, is_mine_rainbow))

    max_offset = max(0, len(rendered) - content_h)
    scroll = max(0, min(scroll, max_offset))
    with state.lock:
        if state.scroll_target > max_offset:
            state.scroll_target = max_offset

    newest_age = rendered[-1][2] if rendered else 99.0
    box_attr = border_attr | (curses.A_BOLD if newest_age < 0.6 else 0)
    chat_title = "Chat" if scroll == 0 else f"Chat ▲{scroll}"
    draw_box(stdscr, top, chat_x, main_h, chat_w, box_attr, chat_title, curses.color_pair(ACCENT_PAIR))

    end = len(rendered) - scroll
    start = max(0, end - content_h)
    visible = rendered[start:end] if content_h > 0 else []

    for i, (line, attr, age, is_rainbow) in enumerate(visible):
        y = top + 1 + i
        # animation d'arrivée : glissement + flash + liseré qui s'estompe
        if age < 0.45:
            indent = int((1 - age / 0.45) * 5)
            if age < 0.1:
                attr |= curses.A_REVERSE
            gutter = FADE_BLOCKS[min(len(FADE_BLOCKS) - 1, int(age / 0.45 * len(FADE_BLOCKS)))]
            put_ch(stdscr, y, chat_x + 1, gutter, rainbow_attr(frame * 0.5) | curses.A_BOLD)
        else:
            indent = 0
        if is_rainbow:
            put_rainbow(stdscr, y, content_x + indent, line[: content_w - indent], offset=frame * 0.6 + i)
        else:
            put(stdscr, y, content_x + indent, line[: content_w - indent], attr)

    # --- indicateur de frappe animé, posé sur la bordure basse du chat
    if typing:
        names = sorted(typing)
        label = (", ".join(names[:2]) + (" et d'autres" if len(names) > 2 else ""))
        verb = "tapent" if len(names) > 1 else "tape"
        dots = "." * (1 + (frame // 5) % 3)
        text = f" {label} {verb}{dots} "
        put(stdscr, top + main_h - 1, chat_x + 3, text[: chat_w - 6],
            curses.color_pair(ACCENT_PAIR) | curses.A_BOLD)

    # --- panneaux flottants
    if show_help:
        draw_help(stdscr, top, chat_x, main_h, chat_w, border_attr, HELP_LINES, "Aide — F1")

    # --- barre de saisie
    bar_y = top + main_h
    bar_attr = curses.color_pair(OK_PAIR if connected else ERR_PAIR)
    if connected and newest_age < 0.6:
        bar_attr |= curses.A_BOLD
    draw_box(stdscr, bar_y, 0, input_h, w, bar_attr,
             "Message" if connected else "Déconnecté", curses.color_pair(ACCENT_PAIR))

    if connected:
        prompt = "❯ "
        put_rainbow(stdscr, bar_y + 1, 2, prompt, offset=frame * 0.8)
        field_x = 2 + len(prompt)
        field_w = max(1, w - field_x - 3)
        view_start = max(0, cursor - field_w + 1)
        visible_text = input_buf[view_start:view_start + field_w]
        put(stdscr, bar_y + 1, field_x, visible_text, curses.A_BOLD)
        cx = field_x + (cursor - view_start)
        blink = (frame // 8) % 2 == 0
        char_under = input_buf[cursor] if cursor < len(input_buf) else " "
        put_ch(stdscr, bar_y + 1, cx, char_under,
               (curses.A_REVERSE | curses.A_BOLD) if blink else curses.A_BOLD)
        counter = f"{len(input_buf)}"
        put(stdscr, bar_y + 1, max(0, w - len(counter) - 2), counter,
            curses.color_pair(DIM_PAIR) | curses.A_DIM)
    else:
        put(stdscr, bar_y + 1, 2, status[: w - 4], curses.color_pair(ERR_PAIR) | curses.A_BOLD)

    # --- particules par-dessus tout
    draw_particles(stdscr, state, h, w)
    draw_toasts(stdscr, state, w, now)

    # --- flash de mention : cadre qui clignote
    if now < state.flash_until:
        flash_attr = (curses.color_pair(ERR_PAIR) if (frame // 3) % 2 else
                      curses.color_pair(SYSTEM_PAIR)) | curses.A_BOLD
        for x in range(w):
            put_ch(stdscr, 0, x, "─", flash_attr)
            put_ch(stdscr, h - 1, x, "─", flash_attr)
        for y in range(h):
            put_ch(stdscr, y, 0, "│", flash_attr)
            put_ch(stdscr, y, w - 1, "│", flash_attr)

    stdscr.refresh()


def draw_splash(stdscr, state, start, now, frame):
    h, w = stdscr.getmaxyx()
    stdscr.erase()
    age = now - start
    logo_w = max(len(l) for l in LOGO)
    y0 = max(0, h // 2 - len(LOGO) // 2 - 2)
    x0 = max(0, (w - logo_w) // 2)

    revealed = int(age * 60)
    for row, line in enumerate(LOGO):
        for col, ch in enumerate(line):
            if ch == " " or row * logo_w + col > revealed:
                continue
            put_ch(stdscr, y0 + row, x0 + col, ch, rainbow_attr(col * 0.6 + row + frame * 0.7) | curses.A_BOLD)

    sub = "T  U  I"
    put(stdscr, y0 + len(LOGO), max(0, (w - len(sub)) // 2), sub,
        curses.color_pair(ACCENT_PAIR) | curses.A_BOLD)

    spin = SPINNER[frame % len(SPINNER)]
    msg = f"{spin}  {state.status}"
    put(stdscr, y0 + len(LOGO) + 2, max(0, (w - len(msg)) // 2), msg,
        curses.color_pair(HEADER_PAIR) | curses.A_BOLD)

    bar_w = min(40, max(10, w - 10))
    bx = max(0, (w - bar_w) // 2)
    for i in range(bar_w):
        phase = math.sin(frame * 0.25 + i * 0.4)
        ch = SPARKS[max(0, min(len(SPARKS) - 1, int((phase + 1) / 2 * (len(SPARKS) - 1))))]
        put_ch(stdscr, y0 + len(LOGO) + 4, bx + i, ch, rainbow_attr(i + frame * 0.6))

    hint = "[une touche pour passer]"
    put(stdscr, h - 2, max(0, (w - len(hint)) // 2), hint, curses.color_pair(DIM_PAIR) | curses.A_DIM)

    draw_particles(stdscr, state, h, w)
    stdscr.refresh()


# --- commandes ----------------------------------------------------------
def handle_command(text, state, stdscr):
    h, w = stdscr.getmaxyx()
    parts = text[1:].split(" ", 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("help", "aide", "?"):
        state.add("info", "aide", "commandes disponibles ↓")
        for line in COMMAND_LINES:
            state.add("info", "·", line)
    elif cmd == "me" and arg:
        send(state, {"type": "action", "text": arg})
    elif cmd in ("confetti", "confettis"):
        state.confetti(w, h)
        send(state, {"type": "action", "text": "lâche des confettis *"})
    elif cmd in ("fireworks", "feu"):
        state.firework(w, h)
        send(state, {"type": "action", "text": "tire un feu d'artifice"})
    elif cmd == "matrix":
        state.matrix_on = not state.matrix_on
        state.matrix = []
        state.toast(f"Matrix {'ON' if state.matrix_on else 'OFF'}")
    elif cmd in ("rainbow", "arc"):
        state.rainbow = not state.rainbow
        state.toast(f"Arc-en-ciel {'ON' if state.rainbow else 'OFF'}")
    elif cmd == "theme":
        state.theme = (state.theme + 1) % len(THEMES)
        state.toast(f"Thème : {apply_theme(state.theme)['name']}")
    elif cmd == "roll":
        n, sides = 1, 6
        if "d" in arg:
            try:
                left, right = arg.lower().split("d", 1)
                n = max(1, min(10, int(left or 1)))
                sides = max(2, min(1000, int(right)))
            except ValueError:
                pass
        rolls = [random.randint(1, sides) for _ in range(n)]
        send(state, {"type": "action", "text": f"lance {n}d{sides} → {rolls} = {sum(rolls)}"})
    elif cmd == "flip":
        send(state, {"type": "action", "text": f"lance une pièce → {random.choice(['pile', 'face'])}"})
    elif cmd == "shrug":
        send(state, {"type": "msg", "text": "¯\\_(ツ)_/¯"})
    elif cmd == "users":
        with state.lock:
            names = ", ".join(state.users) or "(personne)"
        state.add("info", "salon", names)
    elif cmd == "stats":
        send(state, {"type": "stats"})
    elif cmd == "clear":
        with state.lock:
            state.messages.clear()
    elif cmd in ("quit", "q", "exit"):
        return False
    else:
        state.add("info", "?", f"commande inconnue : /{cmd} (essaie /help)")
    return True


# --- boucle principale --------------------------------------------------
def connect_thread(state, host, port, username):
    try:
        sock = socket.create_connection((host, port), timeout=10)
        sock.settimeout(None)
        sock.sendall((json.dumps({"type": "join", "username": username}) + "\n").encode("utf-8"))
        state.sock = sock
        state.connected = True
        state.status = "Connecté !"
        threading.Thread(target=network_thread, args=(sock, state), daemon=True).start()
    except OSError as e:
        state.fatal = f"Connexion impossible à {host}:{port} — {e}"


def main(stdscr, host, port, username):
    locale.setlocale(locale.LC_ALL, "")
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(FRAME_MS)
    state = ChatState(username, host, port)
    setup_colors(state.theme)

    threading.Thread(target=connect_thread, args=(state, host, port, username), daemon=True).start()

    frame = 0
    last = time.time()
    splash_start = last
    splash_h, splash_w = stdscr.getmaxyx()
    state.confetti(splash_w, splash_h, n=60)

    # --- écran d'accueil animé
    while True:
        now = time.time()
        dt = min(0.2, now - last)
        last = now
        h, w = stdscr.getmaxyx()
        state.step_effects(dt, w, h)
        draw_splash(stdscr, state, splash_start, now, frame)
        frame += 1
        if state.fatal:
            return state.fatal
        try:
            ch = stdscr.get_wch()
            if ch is not None and now - splash_start > 0.35:
                break
        except curses.error:
            pass
        if state.connected and now - splash_start > 1.6:
            break

    input_buf = ""
    cursor = 0
    history = []
    hist_idx = None
    typing_sent = 0.0
    last_key = 0.0
    last_ping = 0.0
    running = True

    while running:
        now = time.time()
        dt = min(0.2, now - last)
        last = now
        h, w = stdscr.getmaxyx()
        state.step_effects(dt, w, h)
        draw(stdscr, state, input_buf, cursor, now, frame)
        frame += 1

        if state.connected:
            if now - last_ping > 3.0:
                last_ping = now
                send(state, {"type": "ping", "t": now})
            if typing_sent and now - last_key > 1.8:
                typing_sent = 0.0
                send(state, {"type": "typing", "state": False})

        try:
            ch = stdscr.get_wch()
        except curses.error:
            continue
        if ch is None:
            continue
        if not state.connected and state.sock is not None:
            break

        code = ord(ch) if isinstance(ch, str) and len(ch) == 1 else ch
        is_text = isinstance(ch, str) and len(ch) == 1 and (ch.isprintable() or ch == " ")

        if code in (curses.KEY_ENTER, 10, 13):
            text = input_buf.strip()
            input_buf, cursor, hist_idx = "", 0, None
            if typing_sent:
                typing_sent = 0.0
                send(state, {"type": "typing", "state": False})
            if text:
                history.append(text)
                with state.lock:
                    state.scroll_target = 0
                if text.startswith("/"):
                    running = handle_command(text, state, stdscr)
                else:
                    send(state, {"type": "msg", "text": text})
        elif code in (curses.KEY_BACKSPACE, 127, 8):
            if cursor > 0:
                input_buf = input_buf[:cursor - 1] + input_buf[cursor:]
                cursor -= 1
        elif code == curses.KEY_DC:
            input_buf = input_buf[:cursor] + input_buf[cursor + 1:]
        elif code == curses.KEY_LEFT:
            cursor = max(0, cursor - 1)
        elif code == curses.KEY_RIGHT:
            cursor = min(len(input_buf), cursor + 1)
        elif code in (curses.KEY_HOME, 1):  # Ctrl+A
            cursor = 0
        elif code in (curses.KEY_END, 5):   # Ctrl+E
            cursor = len(input_buf)
        elif code == 21:  # Ctrl+U
            input_buf, cursor = "", 0
        elif code == 23:  # Ctrl+W : effacer le mot précédent
            head = input_buf[:cursor].rstrip()
            cut = head.rfind(" ") + 1
            input_buf = input_buf[:cut] + input_buf[cursor:]
            cursor = cut
        elif code == 9:  # Tab : complétion de pseudo
            head = input_buf[:cursor]
            prefix = head.split(" ")[-1].lower()
            if prefix:
                with state.lock:
                    matches = [u for u in state.users if u.lower().startswith(prefix)]
                if matches:
                    pick = matches[0]
                    start = cursor - len(prefix)
                    suffix = ": " if start == 0 else " "
                    input_buf = input_buf[:start] + pick + suffix + input_buf[cursor:]
                    cursor = start + len(pick) + len(suffix)
                    state.toast(f"→ {pick}")
        elif code == curses.KEY_UP:
            if history:
                hist_idx = len(history) - 1 if hist_idx is None else max(0, hist_idx - 1)
                input_buf = history[hist_idx]
                cursor = len(input_buf)
        elif code == curses.KEY_DOWN:
            if hist_idx is not None:
                hist_idx += 1
                if hist_idx >= len(history):
                    hist_idx, input_buf = None, ""
                else:
                    input_buf = history[hist_idx]
                cursor = len(input_buf)
        elif code == curses.KEY_PPAGE:
            with state.lock:
                state.scroll_target += max(1, state.last_content_h - 1)
        elif code == curses.KEY_NPAGE:
            with state.lock:
                state.scroll_target = max(0, state.scroll_target - max(1, state.last_content_h - 1))
        elif code == 11:  # Ctrl+K : couleur suivante
            new_hue = (state.hue_for(state.username) + 1) % NUM_HUES
            state.set_own_hue(new_hue)
            send(state, {"type": "color", "hue": new_hue})
            state.toast("Nouvelle couleur !")
            state.firework(w, h, count=1)
        elif code == 20:  # Ctrl+T : thème suivant
            state.theme = (state.theme + 1) % len(THEMES)
            state.toast(f"Thème : {apply_theme(state.theme)['name']}")
        elif code == curses.KEY_F1:
            with state.lock:
                state.show_help = not state.show_help
        elif code == curses.KEY_F2:
            state.matrix_on = not state.matrix_on
            state.matrix = []
            state.toast(f"Matrix {'ON' if state.matrix_on else 'OFF'}")
        elif code == curses.KEY_F3:
            state.rainbow = not state.rainbow
            state.toast(f"Arc-en-ciel {'ON' if state.rainbow else 'OFF'}")
        elif code == curses.KEY_F4:
            state.confetti(w, h)
        elif code in (curses.KEY_F5, curses.KEY_F6, curses.KEY_F7, curses.KEY_F8):
            emoji = REACTIONS[code - curses.KEY_F5]
            mid = state.last_message_id()
            if mid is not None:
                send(state, {"type": "reaction", "id": mid, "emoji": emoji})
                state.add_reaction(mid, emoji)
                state.firework(w, h, count=1)
        elif code == curses.KEY_RESIZE:
            state.matrix = []
        elif is_text:
            input_buf = input_buf[:cursor] + ch + input_buf[cursor:]
            cursor += 1
            last_key = now
            if state.connected and now - typing_sent > 1.2:
                typing_sent = now
                send(state, {"type": "typing", "state": True})

    if state.sock:
        try:
            state.sock.close()
        except OSError:
            pass
    return None


def run():
    if len(sys.argv) != 4:
        print("Usage: python3 client.py <ip> <port> <pseudo>")
        sys.exit(1)
    host = sys.argv[1]
    port = int(sys.argv[2])
    username = sys.argv[3]
    error = curses.wrapper(main, host, port, username)
    if error:
        print(error)
        sys.exit(1)


if __name__ == "__main__":
    run()
