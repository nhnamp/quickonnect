"""Ngrok tunnel setup for QuicKonNect demo.

Starts an ngrok TCP tunnel so remote users can connect to a locally
running QuicKonNect load balancer.

Requirements:
    - ngrok must be installed and on PATH (or specify --ngrok-path)
    - An ngrok account with authtoken configured: ngrok config add-authtoken <TOKEN>

Usage:
    python -m scripts.ngrok_setup [--port PORT]
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ngrok_setup")


def find_ngrok() -> str | None:
    """Find ngrok binary on PATH."""
    import shutil
    return shutil.which("ngrok")


def get_tunnel_url(api_port: int = 4040, timeout: int = 15) -> str | None:
    """Query ngrok's local API for the active tunnel URL."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{api_port}/api/tunnels", timeout=3)
            data = json.loads(resp.read().decode())
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "tcp":
                    return t.get("public_url", "")
        except (urllib.error.URLError, ConnectionRefusedError, Exception):
            pass
        time.sleep(1)
    return None


def main():
    parser = argparse.ArgumentParser(description="QuicKonNect Ngrok Tunnel Setup")
    parser.add_argument("--port", type=int, default=9000, help="Local port to tunnel (default: 9000)")
    parser.add_argument("--ngrok-path", default=None, help="Path to ngrok binary")
    parser.add_argument("--region", default="us", help="Ngrok region (default: us)")
    args = parser.parse_args()

    ngrok_bin = args.ngrok_path or find_ngrok()
    if not ngrok_bin:
        logger.error("❌ ngrok not found. Install from https://ngrok.com/download")
        logger.error("   Then run: ngrok config add-authtoken <YOUR_TOKEN>")
        sys.exit(1)

    logger.info("Using ngrok at: %s", ngrok_bin)
    logger.info("Tunneling local port %d...", args.port)

    proc = subprocess.Popen(
        [ngrok_bin, "tcp", str(args.port), "--region", args.region],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def cleanup(signum=None, frame=None):
        logger.info("Stopping ngrok tunnel...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    logger.info("Waiting for ngrok tunnel to establish...")
    tunnel_url = get_tunnel_url()

    if not tunnel_url:
        logger.error("❌ Failed to establish ngrok tunnel")
        logger.error("   Check your ngrok authtoken and internet connection")
        cleanup()

    # Parse host:port from tcp://X.tcp.ngrok.io:PORT
    url_part = tunnel_url.replace("tcp://", "")
    parts = url_part.rsplit(":", 1)
    ngrok_host = parts[0]
    ngrok_port = int(parts[1]) if len(parts) > 1 else 0

    logger.info("")
    logger.info("=" * 60)
    logger.info("  Ngrok Tunnel Active!")
    logger.info("=" * 60)
    logger.info("  Public Address: %s", tunnel_url)
    logger.info("")
    logger.info("  For remote clients:")
    logger.info("    python -m client.main --host %s --port %d", ngrok_host, ngrok_port)
    logger.info("")
    logger.info("  Press Ctrl+C to stop the tunnel")
    logger.info("=" * 60)

    try:
        proc.wait()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
