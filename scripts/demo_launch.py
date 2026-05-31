"""QuicKonNect demo launcher.

Starts all required services for a local demonstration:
  1. PostgreSQL check
  2. Redis check
  3. Load balancer
  4. Chat server (one or more instances)

Usage:
    python -m scripts.demo_launch [--servers N] [--port PORT]
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("demo_launch")


def check_dependency(name: str, host: str, port: int) -> bool:
    """Check if a TCP service is reachable."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception:
        return False


def wait_for_service(name: str, host: str, port: int, timeout: int = 15) -> bool:
    """Wait until a service is reachable or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        if check_dependency(name, host, port):
            return True
        time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description="QuicKonNect Demo Launcher")
    parser.add_argument("--servers", type=int, default=1, help="Number of chat servers (default: 1)")
    parser.add_argument("--lb-port", type=int, default=9000, help="Load balancer port (default: 9000)")
    parser.add_argument("--base-port", type=int, default=9001, help="Base port for chat servers (default: 9001)")
    parser.add_argument("--redis-host", default="127.0.0.1", help="Redis host (default: 127.0.0.1)")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis port (default: 6379)")
    parser.add_argument("--db-dsn", default=None, help="PostgreSQL DSN (default: from env or standard)")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Check Redis
    logger.info("Checking Redis at %s:%d...", args.redis_host, args.redis_port)
    if not check_dependency("Redis", args.redis_host, args.redis_port):
        logger.error("❌ Redis is not running at %s:%d", args.redis_host, args.redis_port)
        logger.error("   Please start Redis: redis-server")
        sys.exit(1)
    logger.info("✅ Redis is running")

    # Check PostgreSQL
    pg_port = 5432
    dsn = args.db_dsn or os.environ.get(
        "DATABASE_URL",
        "postgresql://quickonnect:quickonnect@127.0.0.1:5432/quickonnect",
    )
    logger.info("Checking PostgreSQL...")
    if not check_dependency("PostgreSQL", "127.0.0.1", pg_port):
        logger.error("❌ PostgreSQL is not running on port %d", pg_port)
        logger.error("   Please start PostgreSQL and create the database")
        sys.exit(1)
    logger.info("✅ PostgreSQL is running")

    processes: list[subprocess.Popen] = []

    def cleanup(signum=None, frame=None):
        logger.info("Shutting down all processes...")
        for p in reversed(processes):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        logger.info("All processes stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    env = os.environ.copy()
    env["DATABASE_URL"] = dsn
    env["PYTHONPATH"] = project_root

    # Start chat servers
    for i in range(args.servers):
        server_port = args.base_port + i
        server_id = f"server-{i + 1}"
        logger.info("Starting chat server %s on port %d...", server_id, server_port)
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "server.main",
            ],
            cwd=project_root,
            env={
                **env,
                "SERVER_ID": server_id,
                "SERVER_HOST": "0.0.0.0",
                "SERVER_PORT": str(server_port),
                "REDIS_HOST": args.redis_host,
                "REDIS_PORT": str(args.redis_port),
            },
        )
        processes.append(proc)
        time.sleep(1)

    # Wait for servers to be ready
    for i in range(args.servers):
        port = args.base_port + i
        if not wait_for_service(f"server-{i+1}", "127.0.0.1", port, timeout=10):
            logger.error("❌ Chat server on port %d failed to start", port)
            cleanup()
        logger.info("✅ Chat server on port %d is ready", port)

    # Start load balancer
    logger.info("Starting load balancer on port %d...", args.lb_port)
    lb_proc = subprocess.Popen(
        [sys.executable, "-m", "loadbalancer.main"],
        cwd=project_root,
        env={
            **env,
            "LB_HOST": "0.0.0.0",
            "LB_PORT": str(args.lb_port),
            "REDIS_HOST": args.redis_host,
            "REDIS_PORT": str(args.redis_port),
        },
    )
    processes.append(lb_proc)
    time.sleep(1)

    if not wait_for_service("loadbalancer", "127.0.0.1", args.lb_port, timeout=10):
        logger.error("❌ Load balancer failed to start")
        cleanup()
    logger.info("✅ Load balancer is ready on port %d", args.lb_port)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("  QuicKonNect Demo Environment Ready!")
    logger.info("=" * 60)
    logger.info("  Load Balancer: 127.0.0.1:%d", args.lb_port)
    for i in range(args.servers):
        logger.info("  Chat Server %d: 127.0.0.1:%d", i + 1, args.base_port + i)
    logger.info("")
    logger.info("  To start a client:")
    logger.info("    python -m client.main --host 127.0.0.1 --port %d", args.lb_port)
    logger.info("")
    logger.info("  Press Ctrl+C to stop all services")
    logger.info("=" * 60)

    # Wait for processes
    try:
        while True:
            for p in processes:
                if p.poll() is not None:
                    logger.warning("Process %d exited with code %d", p.pid, p.returncode)
            time.sleep(2)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
