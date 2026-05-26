#!/usr/bin/env python3
"""Start the QuicKonNect desktop client."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.main import run_client

if __name__ == "__main__":
    run_client()
