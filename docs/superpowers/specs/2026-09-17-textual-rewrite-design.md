# Webway rewrite: Textual client + channels + file sharing

Status: approved for planning
Branch: `feature/textual-rewrite`

## Context

The current app (`server.py` + `client.py`) is a proof of concept: a single
chat room over raw TCP with a JSON-lines protocol, a curses-based animated
TUI, and no persistence, no channels, no accounts, and no file transfer.

This spec covers rebuilding it into a real multi-channel terminal chat app,
Discord-flavored: multiple channels, accounts, and file/image/GIF sharing
with inline rendering, on a clean new Textual-based interface. It replaces
the two flat scripts with a proper package and a documented protocol.

## Goals

- Multiple, user-creatable text channels (not just one room).
- Persistent history, channels, users, and shared files (SQLite) — survives
  server restarts.
- Username + password accounts, created implicitly on first use.
- File/image/GIF sharing with inline rendering in the terminal where
  supported, graceful fallback otherwise.
- A clean, newly designed Textual interface (not a port of the curses UI).
- Preserve the spirit of today's live features (typing indicators, reactions,
  mentions, presence list, latency display) adapted to a multi-channel world.

## Non-goals (explicitly out of scope for this rewrite)

- Direct messages between users.
- Roles/permissions beyond "any authenticated user can create a channel".
- Voice/video.
- Multiple servers/guilds — this is one server, many channels.
- Message editing or deletion.
- Load/performance testing.

## Architecture

Single Python process per server instance, built on `aiohttp`, listening on
one port and serving:

- `GET /ws` — WebSocket endpoint carrying all realtime events: auth,
  channel management, messages, typing, reactions, presence.
- `POST /upload` — HTTP multipart endpoint for file/image/GIF uploads.
  Requires the session token issued at WebSocket auth. Validates size
  (cap ~15MB) and mime type server-side; returns `{file_id, url}`.
- `GET /files/{id}` — HTTP download endpoint serving raw bytes by
  unguessable UUID, like a minimal CDN.

Persistent state lives in SQLite (`users`, `channels`, `messages`,
`reactions`, `files`). Presence and typing state are in-memory only —
transient, rebuilt from scratch on reconnect, never persisted.

The client is a Textual app using `textual-image` for inline image/GIF
rendering (Sixel/Kitty/iTerm protocols where supported, ASCII/placeholder
fallback otherwise), talking to the server over one `aiohttp.ClientSession`
(WebSocket for events, HTTP calls for file transfer).

### Package layout

```
webway/
  server/
    app.py          # aiohttp app wiring: routes, startup/shutdown
    db.py           # SQLite schema + queries
    auth.py         # account creation/verification, session tokens
    channels.py     # channel CRUD, subscription/broadcast bookkeeping
    ws_protocol.py  # WebSocket message handling per connection
  client/
    app.py          # Textual App entrypoint
    screens/        # LoginScreen, MainScreen
    widgets/        # ChannelList, ChatLog, MessageInput, MemberList, StatusBar
    net.py          # WebSocket + HTTP client wrapper (async)
  shared/
    protocol.py     # message type constants, (de)serialization, validation
tests/
  test_protocol.py
  test_server.py
  test_client.py
```

`run_server.sh` / `run_client.sh` are updated to install the new
dependencies (`aiohttp`, `textual`, `textual-image`, `bcrypt`) and invoke the
new entrypoints (`python -m webway.server`, `python -m webway.client`).

## Data model (SQLite)

- `users(id, username UNIQUE, password_hash, created_at)`
- `channels(id, name UNIQUE, topic, created_by, created_at)`
- `messages(id, channel_id, user_id, type ['msg'|'action'|'system'], text, file_id NULL, ts)`
- `reactions(message_id, user_id, emoji, UNIQUE(message_id, user_id, emoji))`
- `files(id UUID, uploader_id, filename, mime, size, path, created_at)`

## Protocol

WebSocket messages are JSON, one object per frame, shaped like today's
protocol but namespaced by concern. Client → server:

- `auth {username, password}`
- `channel.create {name, topic}`
- `channel.join {channel_id}`
- `channel.list` (request)
- `message.send {channel_id, text, file_id?}`
- `message.action {channel_id, text}`
- `typing {channel_id, state}`
- `reaction.add {message_id, emoji}`

Server → client:

- `auth.ok {user_id, username, session_token}` / `auth.error {reason}`
- `channel.list {channels: [...]}` / `channel.created {...}` (broadcast)
- `history {channel_id, items: [...]}` (sent on join, last N messages with
  reactions/file metadata joined in)
- `message {id, channel_id, user_id, username, text, ts, type, file?}`
- `typing {channel_id, username, state}`
- `reaction {message_id, emoji, username}`
- `presence {channel_id, users: [...]}`
- `error {reason}`

### Auth flow

First message on a new WebSocket connection must be `auth`. If the username
doesn't exist yet, the account is created with that password (bcrypt-hashed)
— implicit registration, no separate signup step. If the username exists,
the password must match or the server sends `auth.error {reason:
"bad_credentials"}` and closes the connection. On success the server issues
a `session_token` which the client attaches as a header on subsequent
`POST /upload` calls, so uploads can be attributed without re-sending
credentials over HTTP.

### File flow

Client uploads a file via `POST /upload` *before* sending the chat message,
receiving `{file_id, url}`. It then sends `message.send` with `file_id` set.
The server persists the message with a reference to the file, and broadcasts
it with file metadata (filename, mime, size, url) so recipients can
`GET /files/{id}` to fetch bytes. `textual-image` renders inline when the
mime type is an image/GIF and the terminal supports it; otherwise the client
shows a file card (name, size, a keybind to save it to disk).

## Error handling

- **Reconnect:** client's WebSocket loop retries with exponential backoff,
  re-sends `auth` automatically, and re-subscribes to the last-active
  channel. Presence/typing state is discarded and rebuilt from the server's
  next broadcast rather than reconciled.
- **Auth failures:** shown inline on the Textual login screen; no automatic
  retry loop.
- **Uploads:** client pre-validates file existence/size before POSTing;
  server re-validates size/mime and responds `413`/`415` on violation,
  surfaced as a toast in the chat UI.
- **Malformed WebSocket frames:** dropped with a logged warning; the
  connection is not torn down (same posture as today's silent
  `except json.JSONDecodeError: pass`, but logged).
- **DB failures:** wrapped so a failed write sends the client an `error`
  event instead of silently losing the message.

## Testing strategy

- `shared/protocol.py`: pure unit tests for (de)serialization and
  validation (bad types, oversized text, missing fields).
- Server: `aiohttp` test utilities (`AioHTTPTestCase`/`TestClient`) driving
  real WebSocket + HTTP calls against a temp-file SQLite DB — covers auth
  (create/reuse/reject), channel create/join/history replay, message
  broadcast to multiple connected clients, upload → download round-trip,
  and reaction persistence.
- Client: Textual's `Pilot` for a small number of key flows (login screen
  submits auth; a received `message` event renders in the chat log) rather
  than exhaustive widget coverage.
- No load/performance testing.
