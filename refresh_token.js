/**
 * Uses Replit's connectors SDK to generate fresh proxy headers for Google Drive,
 * then writes them to .connector_tokens.json so the Python app can make
 * authenticated Drive API calls via the Replit connectors proxy.
 * Call: node refresh_token.js
 */
const { ReplitConnectors } = require("@replit/connectors-sdk");
const fs = require("fs");

const TOKENS_FILE = ".connector_tokens.json";

async function main() {
  try {
    const connectors = new ReplitConnectors();
    const headers = await connectors.getProxyHeaders("google-drive");
    const proxyUrl = await connectors.getProxyUrl("google-drive");

    const tokens = {};
    if (fs.existsSync(TOKENS_FILE)) {
      try {
        Object.assign(tokens, JSON.parse(fs.readFileSync(TOKENS_FILE, "utf8")));
      } catch (_) {}
    }

    tokens["google-drive"] = {
      proxy_url: proxyUrl,
      proxy_headers: headers,
      written_at: Date.now() / 1000,
    };
    tokens["google-sheet"] = tokens["google-drive"];

    fs.writeFileSync(TOKENS_FILE, JSON.stringify(tokens, null, 2));
    console.log("OK proxy_url=" + proxyUrl + " headers=" + Object.keys(headers).join(","));
  } catch (err) {
    console.error("ERROR:", err.message);
    process.exit(1);
  }
}

main();
