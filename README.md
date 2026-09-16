# chat-tui

A simple terminal chat over TCP/IP, with a curses TUI: participant list on the left, chat on the right, input bar at the bottom.

No external dependencies — pure Python standard library.

## Usage

Start the server (on the host machine):

```
./run_server.sh [port]
```

Default port is `5555` if none is given.

Connect as a client (on each participant's machine):

```
./run_client.sh <server-ip> <port> <your-name>
```

Example:

```
./run_client.sh 192.168.1.42 5555 Alice
```

Both scripts create a `.venv`, install dependencies from `requirements.txt`, and launch the app.

## Controls

- Type to write a message, `Enter` to send.
- `Ctrl+K` to cycle your display color (visible to everyone).
- `Page Up` / `Page Down` to scroll through chat history.
- `F1` to toggle the shortcuts help panel.
- `Ctrl+C` to quit.
