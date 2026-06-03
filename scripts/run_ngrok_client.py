import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.main import run_client

logger = logging.getLogger("ngrok_client")

if __name__ == "__main__":
    os.environ["QUICKONNECT_DIRECT_SERVER"] = "1"
    logger.info("Starting QuicKonNect in Direct Ngrok Mode...")
    run_client()
