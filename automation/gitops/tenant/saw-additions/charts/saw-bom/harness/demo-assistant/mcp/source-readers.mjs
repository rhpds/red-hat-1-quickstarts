import { readFileSync } from "node:fs";
import { serve } from "./briefing-lib.mjs";
import { createSourceTools } from "./source-tools.mjs";

const config = JSON.parse(readFileSync(new URL("../config.json", import.meta.url), "utf8"));
const scope = {
  "mailpit_reader": ["saw_read_email"],
  "mattermost_reader": ["saw_read_chat"],
  "calendar_reader": ["saw_read_calendar"],
  "demo_notes": ["saw_save_report", "saw_upload_summary"],
};
const name = process.argv[2];
if (!scope[name]) throw new Error("Unknown demo MCP server");
serve(name, createSourceTools(config).filter(tool => scope[name].includes(tool.name)));
