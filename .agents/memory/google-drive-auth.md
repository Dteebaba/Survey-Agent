---
name: Google Drive auth in Replit (dev + deployed)
description: How to get valid Google OAuth tokens for Drive API calls in both dev and deployed Replit environments.
---

# Rule
Use Replit's connectors proxy (`https://connectors.replit.com/api/v2/proxy`) via the Node.js SDK (`@replit/connectors-sdk`). Direct OAuth token exchange methods all fail in deployed environments. The proxy handles token refresh automatically.

**Why:** All of these fail in deployment:
- `GOOGLE_ACCESS_TOKEN` secret — expires in ~1 hr, static
- `.connector_tokens.json` cached tokens — also expire
- `REPL_IDENTITY`/`REPL_IDENTITY_KEY` against connectors API — wrong format (Paseto, not JWT)
- `REPLIT_TOKEN` proxy endpoint — `REPLIT_TOKEN` not injected in deployed apps

What DOES work: `ReplitConnectors().getProxyHeaders("google-drive")` from `@replit/connectors-sdk` (npm). The SDK is installed in the workspace and works via `node refresh_token.js`.

**How to apply:**
1. `node refresh_token.js` writes proxy_url + proxy_headers to `.connector_tokens.json`
2. Python reads those headers and calls `proxy_url + "/drive/v3/..."` with them
3. `token_store.py` calls `_refresh_via_node()` automatically when cache is >45 min old
4. `google_connector.py._drive_request()` routes all Drive calls through proxy, retries once on 401
