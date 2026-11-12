import { readFileSync } from "node:fs";
import { serve } from "./briefing-lib.mjs";
import { createSourceTools } from "./source-tools.mjs";

const config = JSON.parse(readFileSync(new URL("../config.json", import.meta.url), "utf8"));
serve("demo-assistant", createSourceTools(config));
