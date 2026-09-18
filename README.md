# webway

A multi-channel terminal chat application with a modern Textual TUI. Connect via TCP/IP, authenticate with username and password, join channels, share files, and view inline images on supported terminals.

## Running

**Start the server:**

```bash
./run_server.sh [port]
```

The default port is `5555`. The server creates a SQLite database and file upload directory on startup.

**Connect a client:**

```bash
./run_client.sh <server-ip> <port>
```

Example:

```bash
./run_client.sh 192.168.1.42 5555
```

Both scripts create a `.venv`, install dependencies from `requirements.txt`, and launch the application.

## Authentication

When you first launch the client, you'll be prompted for a username and password.

- **First login:** Using a new username with any password creates that account.
- **Subsequent logins:** You must use the same password that was set on first login with that username.

## Using the Client

### Switching Channels

Use the `/join` command to switch to an existing channel:

```
/join general
/join random
```

The channel list appears in the left sidebar. Click or use `/join` to switch channels.

### Sharing Files

Use the `/upload` command to share a file with the current channel:

```
/upload /path/to/file.txt
/upload ~/Pictures/screenshot.png
```

**Image handling:** Images (JPG, PNG, GIF, etc.) automatically render inline in the chat on terminals with graphics protocol support (via `textual-image`). On terminals without graphics support, images display as a text notice with a download link.

**File size limit:** 15 MB per file.

## Architecture

- **Server:** aiohttp-based WebSocket server with SQLite persistence. Handles authentication, channel management, message history, file uploads, and presence tracking.
- **Client:** Textual TUI application. Displays channels, chat messages, member list, and supports real-time typing indicators and reactions.
- **Protocol:** JSON-based WebSocket protocol for client-server communication.

## Feature Summary

- **Multi-channel chat:** Create and join multiple channels.
- **Accounts:** Username/password authentication. First login with a username creates the account.
- **Presence:** See who's online in each channel.
- **File sharing:** Upload and download files; images render inline when supported.
- **Message history:** 50 recent messages per channel are replayed when you join.
- **Typing indicators:** See when others are typing.
- **Reactions:** Add emoji reactions to messages.
