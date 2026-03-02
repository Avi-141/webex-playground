#!/usr/bin/env node
import { config } from "dotenv";
import https from "node:https";

config();

const WEBEX_API = "https://webexapis.com/v1";
const TOKEN = process.env.WEBEX_TOKEN;

if (!TOKEN) {
  console.error("Set WEBEX_TOKEN in .env first.");
  process.exit(1);
}

function httpsGet(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { Authorization: `Bearer ${TOKEN}` } }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        if (res.statusCode >= 400) {
          reject(new Error(`Webex API ${res.statusCode}: ${body}`));
          return;
        }
        const linkHeader = res.headers["link"] || "";
        let nextUrl = null;
        const match = linkHeader.match(/<([^>]+)>\s*;\s*rel="next"/);
        if (match) nextUrl = match[1];
        resolve({ json: JSON.parse(body), nextUrl });
      });
    });
    req.on("error", reject);
    req.setTimeout(15000, () => {
      req.destroy(new Error("Request timed out after 15s"));
    });
  });
}

async function run() {
  let url = `${WEBEX_API}/rooms?max=50&sortBy=lastactivity`;
  const allRooms = [];

  while (url) {
    const { json, nextUrl } = await httpsGet(url);
    allRooms.push(...(json.items || []));
    url = nextUrl;
  }

  if (allRooms.length === 0) {
    console.log("No spaces found.");
    return;
  }

  console.log(`Found ${allRooms.length} space(s):\n`);

  const maxTitle = Math.min(
    60,
    Math.max(...allRooms.map((r) => r.title?.length || 0))
  );

  for (const room of allRooms) {
    const title = (room.title || "(untitled)").padEnd(maxTitle);
    const type = (room.type || "?").padEnd(6);
    const last = room.lastActivity?.slice(0, 10) || "?";
    console.log(`  ${title}  ${type}  ${last}  ${room.id}`);
  }

  console.log(
    "\nCopy the IDs you want into .env as:\n  WEBEX_ROOM_IDS=id1,id2,id3"
  );
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
