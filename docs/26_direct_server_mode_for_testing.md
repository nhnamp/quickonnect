# Direct Server Mode For Testing

## What Was Done
Added an explicit direct-server testing mode to the client load-balancer helper. When `QUICKONNECT_DIRECT_SERVER=1`, the client treats the configured host and port as a chat server address directly. Otherwise, the client uses the normal load balancer flow. The testing guide was updated to distinguish multi-server testing through port `9000` from single-server/LAN/ngrok testing through port `9001`, and now enables subtitles by default in the server startup commands.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/network/lb_client.py` | Modified | Added `QUICKONNECT_DIRECT_SERVER=1` support for single-server and ngrok testing. |
| `testing.md` | Modified | Clarified which ports and environment variables to use for multi-server, single-server, LAN, and ngrok tests, with subtitle/STT enabled by default. |
| `docs/26_direct_server_mode_for_testing.md` | Created | Documents this testing-mode update. |

## Why It Matters
The client speaks different first packets depending on whether it is contacting a load balancer or a chat server. Sending a load-balancer `CONNECT_REQUEST` directly to a chat server can cause the server to close the connection. The explicit direct mode prevents confusion while preserving the normal multi-server load-balancer path.
