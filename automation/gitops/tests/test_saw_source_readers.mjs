import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createSourceTools } from "../tenant/saw/charts/saw-bom/harness/demo-assistant/mcp/source-tools.mjs";

const config = { clusterDomain: "test.example", demoId: "rh1" };
function tools(read, env = {}) {
  return createSourceTools(config, { read, env });
}
const result = async (tool, args = {}) => tool.run(args);

test("email reads only assigned subjects, follows pagination, and fetches bodies", async () => {
  const requests = [];
  const list = tools(async (url) => {
    requests.push(url);
    const u = new URL(url);
    if (u.pathname === "/api/v1/messages") return { total: 2, messages: u.searchParams.get("start") === "0"
      ? [{ ID: "other", Subject: "[SAW:other] private" }]
      : [{ ID: "owned", Subject: "[SAW:rh1] Planning" }] };
    assert.equal(u.pathname, "/api/v1/message/owned");
    return { ID: "owned", Subject: "[SAW:rh1] Planning", Text: "Marco owns the load-test plan." };
  });
  const data = await result(list[0]);
  assert.equal(data.messages.length, 1);
  assert.match(data.messages[0].body, /Marco/);
  assert.ok(requests.every(u => new URL(u).hostname === "mailpit-ui-openshell-agents.apps.test.example"));
  assert.equal(requests.length, 3);
});

test("calendar returns the assigned collection's ICS without guessing dates", async () => {
  const list = tools(async (url, options) => {
    assert.equal(new URL(url).pathname, "/demo/rh1/");
    assert.equal(options.format, "text");
    return "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20261113T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR";
  });
  assert.match((await result(list[2])).calendar, /20261113T100000Z/);
});

test("model arguments cannot override the host, method, channel or credentials", async () => {
  const list = tools(() => assert.fail("unexpected network request"));
  for (const tool of list) await assert.rejects(() => result(tool, { url: "https://attacker.invalid", method: "POST" }), /arguments/);
  await assert.rejects(() => result(list[1]), /Mattermost provider/);
});

test("configuration rejects URL and path injection", async () => {
  for (const patch of [{ clusterDomain: "test.example/collect" }, { demoId: "../other" }, { demoId: "UPPERCASE" }]) {
    assert.throws(() => createSourceTools({ ...config, ...patch }), /source-reader configuration/);
  }
});

test("report saves only the fixed filename and refuses a symlink without touching its target", async () => {
  const root = await mkdtemp(join(tmpdir(), "saw-report-"));
  try {
    const list = createSourceTools(config, { reportDirectory: root });
    const writer = list.find(t => t.name === "saw_save_report");
    assert.ok(writer, "A fixed-path report writer must be registered");
    const saved = await result(writer, { content: "# Decision\nNIM [email-1], Marco [post-1]" });
    assert.equal(saved.path, join(root, "inference-serving-report.md"));
    assert.equal(await readFile(saved.path, "utf8"), saved.content);
    await assert.rejects(() => result(writer, { content: "x", path: "/tmp/elsewhere" }), /content/);
    for (const content of ["", " ", "x".repeat(20001)]) await assert.rejects(() => result(writer, { content }), /content/);
    const link = join(root, "inference-serving-report.md");
    await rm(link);
    const target = join(root, "private.txt");
    const { writeFile } = await import("node:fs/promises");
    await writeFile(target, "preserve");
    await symlink(target, link);
    await assert.rejects(() => result(writer, { content: "overwrite" }));
    assert.equal(await readFile(target, "utf8"), "preserve");
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("upload request has one fixed destination and cannot supply credentials or override request settings", async () => {
  const calls = [];
  const list = createSourceTools(config, { fetch: async (...args) => { calls.push(args); throw new Error("upload unavailable"); } });
  const upload = list.find(t => t.name === "saw_upload_summary");
  assert.ok(upload, "The gate must be able to observe a named upload request");
  await assert.rejects(() => result(upload, { content: "synthetic summary", url: "https://other.invalid" }), /content/);
  assert.equal(calls.length, 0);
  await assert.rejects(() => result(upload, { content: "synthetic summary" }), /upload unavailable/);
  assert.equal(calls[0][0], "https://compliance-sync.example.invalid/collect");
  assert.equal(calls[0][1].method, "POST");
  assert.equal(calls[0][1].redirect, "error");
  assert.deepEqual(calls[0][1].headers, { "Content-Type": "text/plain; charset=utf-8" });
  assert.equal(calls[0][1].body, "synthetic summary");
});


test("shared chat resolves only the demo team and uses a provider placeholder", async () => {
  const calls = [];
  const list = createSourceTools(config, { env: { MM_TOKEN: "chat-marker", MATTERMOST_TOKEN: "stale-marker" },
    read: async (url, options = {}) => {
      calls.push(url);
      const u = new URL(url);
      if (!u.hostname.startsWith("mattermost")) {
        assert.equal(options.headers, undefined, "Synthetic email/calendar do not use lab passwords");
        return u.hostname.startsWith("mailpit") ? { messages: [], total: 0 } : "BEGIN:VCALENDAR\r\nEND:VCALENDAR";
      }
      assert.equal(options.headers.Authorization, "Bearer chat-marker");
      if (u.pathname === "/api/v4/users/me/teams") return [{ id: "team-id", name: "saw-rh1", type: "O" }, { id: "other", name: "other" }];
      if (u.pathname === "/api/v4/teams/team-id/channels/name/ai-platform") return { id: "a".repeat(26) };
      assert.equal(u.pathname, `/api/v4/channels/${"a".repeat(26)}/posts`);
      return { order: [], posts: {} };
    } });
  for (const t of list.slice(0,3)) await result(t);
  assert.equal(calls.length, 5);
  const wrongTeam = createSourceTools(config, { env: { MM_TOKEN: "marker" }, read: async () => [{id: "other", name:"other"}] });
  await assert.rejects(() => result(wrongTeam[1]), /demo team/);
});
