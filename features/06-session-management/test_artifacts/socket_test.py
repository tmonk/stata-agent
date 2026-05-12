#!/usr/bin/env python3
"""Simple socket-based communication test."""
import socket
import os
import json
import tempfile

SOCK_PATH = tempfile.gettempdir() + "/stata_test_daemon.sock"

def server():
    if os.path.exists(SOCK_PATH):
        os.remove(SOCK_PATH)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK_PATH)
    s.listen(1)
    print(f"Server listening on {SOCK_PATH}")
    conn, addr = s.accept()
    print("Client connected")
    while True:
        data = conn.recv(4096)
        if not data:
            break
        msg = json.loads(data.decode())
        print(f"Received: {msg}")
        response = {"id": msg.get("id"), "ok": True, "result": f"Echo: {msg.get('cmd')}"}
        conn.sendall((json.dumps(response) + "\n").encode())
    conn.close()
    s.close()
    os.remove(SOCK_PATH)
    print("Server shut down")

def client():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK_PATH)
    req = {"id": "1", "cmd": "sysuse auto"}
    s.sendall((json.dumps(req) + "\n").encode())
    resp = s.recv(4096).decode()
    print(f"Response: {resp.strip()}")
    s.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        server()
    else:
        client()
