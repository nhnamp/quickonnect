import os


class ClientConfig:
    def __init__(self):
        self.lb_host = os.environ.get("LB_HOST", "127.0.0.1")
        self.lb_port = int(os.environ.get("LB_PORT", "9000"))
        self.data_dir = os.environ.get(
            "QUICKONNECT_DATA",
            os.path.join(os.path.expanduser("~"), ".quickonnect"),
        )
