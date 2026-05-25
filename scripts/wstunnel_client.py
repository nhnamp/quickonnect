import asyncio
import websockets
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wstunnel_client")

async def tcp_to_ws(tcp_reader, ws):
    try:
        while True:
            data = await tcp_reader.read(4096)
            if not data:
                break
            await ws.send(data)
    except Exception as e:
        logger.debug(f"tcp_to_ws error: {e}")
    finally:
        await ws.close()

async def ws_to_tcp(ws, tcp_writer):
    try:
        async for message in ws:
            tcp_writer.write(message)
            await tcp_writer.drain()
    except Exception as e:
        logger.debug(f"ws_to_tcp error: {e}")
    finally:
        tcp_writer.close()

async def handle_local_client(reader, writer, ngrok_url, path):
    ws_url = f"{ngrok_url}{path}"
    logger.info(f"Proxying local connection to {ws_url}")
    try:
        async with websockets.connect(ws_url) as ws:
            await asyncio.gather(
                tcp_to_ws(reader, ws),
                ws_to_tcp(ws, writer)
            )
    except Exception as e:
        logger.error(f"Failed to connect to {ws_url}: {e}")
    finally:
        writer.close()
        logger.info(f"Closed proxy for {path}")

async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.wstunnel_client <ngrok-url>")
        print("Example: python -m scripts.wstunnel_client https://causing-take.ngrok-free.dev")
        sys.exit(1)

    ngrok_url = sys.argv[1].rstrip("/")
    # Ensure it uses WSS/WS
    if ngrok_url.startswith("https://"):
        ngrok_url = ngrok_url.replace("https://", "wss://")
    elif ngrok_url.startswith("http://"):
        ngrok_url = ngrok_url.replace("http://", "ws://")
    elif not ngrok_url.startswith("ws"):
        ngrok_url = f"wss://{ngrok_url}"

    # Handle client connections to local 9000 by tunneling them to Ngrok /lb
    server_lb = await asyncio.start_server(
        lambda r, w: handle_local_client(r, w, ngrok_url, "/lb"), "127.0.0.1", 9000
    )
    
    # Handle client connections to local 9001 by tunneling them to Ngrok /chat
    server_chat = await asyncio.start_server(
        lambda r, w: handle_local_client(r, w, ngrok_url, "/chat"), "127.0.0.1", 9001
    )

    logger.info("Local tunnel client running:")
    logger.info("  - App Load Balancer Port: 127.0.0.1:9000 -> tunneled to /lb")
    logger.info("  - App Chat Server Port:   127.0.0.1:9001 -> tunneled to /chat")
    logger.info("Waiting for local QuicKonNect desktop app to connect...")

    async with server_lb, server_chat:
        await asyncio.gather(server_lb.serve_forever(), server_chat.serve_forever())

if __name__ == "__main__":
    asyncio.run(main())
