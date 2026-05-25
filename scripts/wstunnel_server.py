import asyncio
import websockets
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wstunnel_server")

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

async def handle_client(ws):
    path = ws.path if hasattr(ws, 'path') else getattr(ws, 'request', getattr(ws, 'path', '/'))
    # Extract path string
    if hasattr(path, 'path'):
        path_str = path.path
    else:
        path_str = str(path)
        
    if "/lb" in path_str:
        target_host = "127.0.0.1"
        target_port = 9000
    elif "/chat" in path_str:
        target_host = "127.0.0.1"
        target_port = 9001
    else:
        logger.warning(f"Unknown path requested: {path_str}")
        return

    logger.info(f"Incoming WS connection for {path_str}, proxying to {target_host}:{target_port}")
    try:
        reader, writer = await asyncio.open_connection(target_host, target_port)
    except Exception as e:
        logger.error(f"Failed to connect to backend {target_host}:{target_port} - {e}")
        return

    await asyncio.gather(
        tcp_to_ws(reader, ws),
        ws_to_tcp(ws, writer)
    )
    logger.info(f"Connection for {path_str} closed")

async def main():
    logger.info("Starting WS tunnel server on 0.0.0.0:8000")
    async with websockets.serve(handle_client, "0.0.0.0", 8000):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
