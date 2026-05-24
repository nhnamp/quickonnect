#!/usr/bin/env python3
"""Start a QuicKonNect chat server instance."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.config import ServerConfig
from server.main import run_server

if __name__ == "__main__":
    if len(sys.argv) > 1:
        os.environ.setdefault("SERVER_PORT", sys.argv[1])
        os.environ.setdefault("SERVER_ID", f"server-{sys.argv[1]}")
    run_server()
