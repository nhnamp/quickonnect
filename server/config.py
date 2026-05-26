import os


class ServerConfig:
    def __init__(self):
        self.host = os.environ.get("SERVER_HOST", "0.0.0.0")
        self.port = int(os.environ.get("SERVER_PORT", "9001"))
        self.server_id = os.environ.get("SERVER_ID", f"server-{self.port}")

        self.db_host = os.environ.get("DB_HOST", "127.0.0.1")
        self.db_port = int(os.environ.get("DB_PORT", "5432"))
        self.db_name = os.environ.get("DB_NAME", "quickonnect")
        self.db_user = os.environ.get("DB_USER", "quickonnect")
        self.db_password = os.environ.get("DB_PASSWORD", "quickonnect")

        self.redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
        self.redis_port = int(os.environ.get("REDIS_PORT", "6379"))

        self.jwt_secret = os.environ.get("JWT_SECRET", "quickonnect-dev-secret-change-in-production")

        self.lb_host = os.environ.get("LB_HOST", "127.0.0.1")
        self.lb_port = int(os.environ.get("LB_PORT", "9000"))

    @property
    def dsn(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} "
            f"dbname={self.db_name} user={self.db_user} password={self.db_password}"
        )
