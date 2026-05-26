import os


class LBConfig:
    def __init__(self):
        self.host = os.environ.get("LB_HOST", "0.0.0.0")
        self.port = int(os.environ.get("LB_PORT", "9000"))

        self.redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
        self.redis_port = int(os.environ.get("REDIS_PORT", "6379"))

        servers_env = os.environ.get("CHAT_SERVERS", "")
        self.chat_servers: list[dict] = []
        if servers_env:
            for entry in servers_env.split(","):
                parts = entry.strip().split(":")
                if len(parts) == 3:
                    self.chat_servers.append({
                        "server_id": parts[0],
                        "host": parts[1],
                        "port": int(parts[2]),
                    })

        if not self.chat_servers:
            self.chat_servers = [
                {"server_id": "server-9001", "host": "127.0.0.1", "port": 9001},
                {"server_id": "server-9002", "host": "127.0.0.1", "port": 9002},
            ]
