// One-shot ingest: pushes the Python engine export into the running app.
// Usage: node app/scripts/ingest-export.mjs  (after `python3 -m scripts.export_app`)
import fs from "node:fs";
const url = process.env.APP_URL ?? "http://localhost:3000";
const token = process.env.APP_INGEST_TOKEN;
if (!token) {
  throw new Error("APP_INGEST_TOKEN is required to ingest an export");
}
const exp = JSON.parse(fs.readFileSync("../reports/app-export.json", "utf8"));
const res = await fetch(`${url}/api/recommendations`, {
  method: "POST",
  headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
  body: JSON.stringify(exp),
});
console.log(res.status, await res.text());
