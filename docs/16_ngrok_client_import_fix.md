# Ngrok Client Import Fix

## What Was Done
Fixed `scripts/run_ngrok_client.py` so it can be launched directly with `python3 scripts/run_ngrok_client.py` from the project root.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `scripts/run_ngrok_client.py` | Modified | Adds the project root to `sys.path` before importing `client.main`, so the `client` package can be resolved when the script is executed from inside `scripts/`. |
| `client/main.py` | Modified | Uses module aliases in direct-server mode so Python does not treat `client` as an unbound local variable while patching request routing. |
| `docs/16_ngrok_client_import_fix.md` | Created | Documents this startup fix. |

## Why It Matters
Python uses the script's directory as the first import path when a file is executed directly. Because this launcher lives in `scripts/`, the root-level `client` package was not visible, causing `ModuleNotFoundError`. Adding the project root makes the launcher behave consistently with the other project scripts.

The direct-server startup path also needs to patch the load-balancer request helper in several UI modules. Importing those modules as aliases avoids Python's local variable binding rule that previously caused `UnboundLocalError` for the `client` package name.
