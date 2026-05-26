#!/usr/bin/env python3
"""Start the QuicKonNect load balancer."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loadbalancer.config import LBConfig
from loadbalancer.main import run_lb

if __name__ == "__main__":
    run_lb()
