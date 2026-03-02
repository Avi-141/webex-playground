#!/usr/bin/env node
import Database from "better-sqlite3";
import { config } from "dotenv";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

config();

const require = createRequire(import.meta.url);
const request = require("request");

const WEBEX_API = "https://webexapis.com/v1";
const TOKEN = process.env.WEBEX_TOKEN;
const ROOM_IDS = (process.env.WEBEX_ROOM_IDS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const DB_PATH = process.env.DB_PATH || "./webex.db";

if (!TOKEN) {
  console.error("Set WEBEX_TOKEN in .env");
  process.exit(1);
}
if (ROOM_IDS.length === 0) {
  console.error(
    "Set WEBEX_ROOM_IDS in .env (comma-separated). Run `npm run list-spaces` to find IDs."
  );
  process.exit(1);
}

const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");
db.exec(readFileSync("./schema.sql", "utf8"));

const upsertSpace = db.prepare(`
  INSERT INTO spaces (id, title, fetched_at)
  VALUES (@id, @title, @fetched_at)
  ON CONFLICT(id) DO UPDATE SET title = excluded.title, fetched_at = excluded.fetched_at
`);

const upsertMessage = db.prepare(`
  INSERT INTO messages (id, space_id, parent_id, person_id, person_email,
                        created_at, text, html, markdown, mentioned_people, links, day)
  VALUES (@id, @space_id, @parent_id, @person_id, @person_email,
          @created_at, @text, @html, @markdown, @mentioned_people, @links, @day)
  ON CONFLICT(id) DO NOTHING
`);

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function webexRequest(url) {
  return new Promise((resolve, reject) => {
    request(
      {
        method: "GET",
        url,
        headers: {
          Authorization: `Bearer ${TOKEN}`,
          Accept: "application/json",
        },
        timeout: 30000,
      },
      (error, response) => {
        if (error) return reject(error);
        resolve(response);
      }
    );
  });
}

function getNextLink(linkHeader) {
  if (!linkHeader) return null;
  for (const part of linkHeader.split(",")) {
    const match = part.trim().match(/<([^>]+)>\s*;\s*rel="next"/);
    if (match) return match[1];
  }
  return null;
}

async function webexGet(url) {
  const response = await webexRequest(url);

  if (response.statusCode === 429) {
    const retryAfter = Number(response.headers["retry-after"] || "5");
    console.log(`  Rate limited. Retrying in ${retryAfter}s...`);
    await sleep(Math.max(1, retryAfter) * 1000);
    return webexGet(url);
  }

  if (response.statusCode >= 400) {
    throw new Error(`Webex API ${response.statusCode}: ${response.body}`);
  }

  const json =
    typeof response.body === "string"
      ? JSON.parse(response.body)
      : response.body;
  const nextUrl = getNextLink(response.headers["link"]);
  return { json, nextUrl };
}

function getDay(isoDate) {
  return new Date(isoDate).toLocaleDateString("en-CA", {
    timeZone: "Asia/Kolkata",
  });
}

function extractLinks(text) {
  if (!text) return [];
  const matches = text.match(/https?:\/\/[^\s<>)"'\]]+/g);
  return matches ? [...new Set(matches)] : [];
}

async function fetchSpaceInfo(roomId) {
  const { json } = await webexGet(
    `${WEBEX_API}/rooms/${encodeURIComponent(roomId)}`
  );
  return json;
}

async function fetchAllMessages(roomId) {
  let url = `${WEBEX_API}/messages?roomId=${encodeURIComponent(roomId)}&max=100`;
  let page = 0;
  let total = 0;

  while (url) {
    const { json, nextUrl } = await webexGet(url);
    const items = json.items || [];

    const insertBatch = db.transaction((msgs) => {
      for (const m of msgs) {
        upsertMessage.run({
          id: m.id,
          space_id: m.roomId,
          parent_id: m.parentId || null,
          person_id: m.personId || null,
          person_email: m.personEmail || null,
          created_at: m.created,
          text: m.text || null,
          html: m.html || null,
          markdown: m.markdown || null,
          mentioned_people: m.mentionedPeople
            ? JSON.stringify(m.mentionedPeople)
            : null,
          links: JSON.stringify(extractLinks(m.text || m.html || "")),
          day: getDay(m.created),
        });
      }
    });

    insertBatch(items);
    total += items.length;
    page++;
    console.log(
      `  Page ${page}: ${items.length} messages (running total: ${total})`
    );

    url = nextUrl;
  }

  return total;
}

async function run() {
  console.log(`Fetching messages for ${ROOM_IDS.length} space(s)...\n`);

  for (const roomId of ROOM_IDS) {
    console.log(`Space: ${roomId}`);

    try {
      const space = await fetchSpaceInfo(roomId);
      upsertSpace.run({
        id: space.id,
        title: space.title,
        fetched_at: new Date().toISOString(),
      });
      console.log(`  Title: ${space.title}`);
    } catch (err) {
      console.warn(`  Could not fetch space info: ${err.message}`);
      upsertSpace.run({
        id: roomId,
        title: null,
        fetched_at: new Date().toISOString(),
      });
    }

    const count = await fetchAllMessages(roomId);
    console.log(`  Done: ${count} messages.\n`);
  }

  const stats = db
    .prepare(
      `SELECT
         (SELECT COUNT(*) FROM spaces) AS spaces,
         (SELECT COUNT(*) FROM messages) AS messages`
    )
    .get();
  console.log(
    `\nDatabase: ${stats.spaces} spaces, ${stats.messages} messages`
  );
  console.log(`Saved to ${DB_PATH}`);

  db.close();
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
