# Restore Load Balancer Routing

## What Was Done
Restored the client load-balancer request path so multi-server testing uses the load balancer again. The temporary direct-server bypass in `client/network/lb_client.py` was removed, so clients now send `CONNECT_REQUEST` to the load balancer and receive the selected chat server address.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/network/lb_client.py` | Modified | Removed the temporary direct-server return used for ngrok single-server testing. |
| `docs/25_restore_load_balancer_routing.md` | Created | Documents this change for multi-server testing. |

## Why It Matters
Multi-server behavior is demonstrated through the custom load balancer and multiple chat servers. The client must contact the load balancer first for least-connections routing and room-aware server selection to be visible during testing.
