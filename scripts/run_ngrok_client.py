import logging
import os

from client.main import run_client

logger = logging.getLogger("ngrok_client")

if __name__ == "__main__":
    os.environ["QUICKONNECT_DIRECT_SERVER"] = "1"
    logger.info("Starting QuicKonNect in Direct Ngrok Mode...")
    run_client()
