"""A client of the control API (api.md §1): one HTTP/1.1 + JSON request per connection on the daemon's Unix socket."""
import http.client, json, socket

from pr_wizard import names


class Down(Exception):
    """No daemon answers on the socket: no file (ENOENT) or a stale one (ECONNREFUSED)."""


class Failed(Exception):
    """The daemon answered with an api.md §2 error body."""

    def __init__(self, status, body):
        self.status, self.error = status, body["error"]
        super().__init__(self.error["message"])


class Connection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("pr-wizard", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def call(method, path, body=None, timeout=90):
    """The decoded body of `method path`. Raises Down when no daemon runs, Failed on a 4xx/5xx."""
    conn = Connection(names.SOCKET, timeout)
    try:
        conn.request(method, path, None if body is None else json.dumps(body),
                     {"Content-Type": "application/json"})
        reply = conn.getresponse()
        status, data = reply.status, json.loads(reply.read())
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise Down(names.SOCKET) from e
    finally:
        conn.close()
    if status >= 400:
        raise Failed(status, data)
    return data
