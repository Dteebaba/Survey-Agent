/**
 * Token refresh script — called from Python via subprocess to keep
 * .connector_tokens.json fresh before each pipeline run.
 * Run with: node refresh_tokens.js
 */
const { writeFileSync } = require('fs');
const path = require('path');

async function main() {
  // Dynamic import of the connectors SDK
  let listConnections;
  try {
    // Try Replit sandbox globals first
    listConnections = global.listConnections;
  } catch (e) {}

  if (!listConnections) {
    console.error('listConnections not available — must run inside Replit code_execution sandbox');
    process.exit(1);
  }

  const driveConns = await listConnections('google-drive');
  const sheetsConns = await listConnections('google-sheet');

  const driveToken = driveConns[0]?.settings?.access_token || '';
  const sheetToken = sheetsConns[0]?.settings?.access_token || '';

  if (!driveToken || !sheetToken) {
    console.error('Could not get tokens from connector');
    process.exit(1);
  }

  const tokenData = {
    "google-drive": { "access_token": driveToken, "written_at": Date.now() / 1000 },
    "google-sheet": { "access_token": sheetToken, "written_at": Date.now() / 1000 }
  };

  const filePath = path.join(__dirname, '.connector_tokens.json');
  writeFileSync(filePath, JSON.stringify(tokenData));
  console.log('Tokens refreshed successfully');
}

main().catch(e => { console.error(e); process.exit(1); });
