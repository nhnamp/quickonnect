import sys
import logging
from client.main import run_client
import client.network.lb_client

logger = logging.getLogger("ngrok_client")

def bypass_load_balancer(lb_host: str, lb_port: int, room_code: str | None = None) -> tuple[str, int]:
    """
    Bypass the Load Balancer entirely.
    Instead of making an HTTP request to ask for a Chat Server IP,
    we directly return the Host and Port that the user typed in the Login Window.
    """
    logger.info(f"Bypassing LB. Connecting directly to Chat Server at {lb_host}:{lb_port}")
    return lb_host, lb_port

# Patch the LB client module
client.network.lb_client.request_server = bypass_load_balancer

# Also patch the local reference inside login_window
try:
    import client.ui.login_window
    client.ui.login_window.request_server = bypass_load_balancer
except ImportError:
    pass

if __name__ == "__main__":
    logger.info("Starting QuicKonNect in Direct Ngrok Mode...")
    # Khởi động ứng dụng gốc nguyên bản, chỉ khác là Load Balancer đã bị vô hiệu hóa
    run_client()
