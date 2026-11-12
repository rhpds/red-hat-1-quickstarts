import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createSourceTools, registerSourceReaders } from "../tenant/saw/charts/openshell-saw/files/installer/source-readers.mjs";

const config = { enabled: true, clusterDomain: "test.example", demoId: "rh1", channelId: "a".repeat(26) };
function tools(read, env = {}) {
  return createSourceTools(config, { read, env });
}
const result = async (tool, args = {}) => JSON.parse((await tool.execute("test", args)).content[0].text);

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

test("chat uses only the configured channel and a provider placeholder", async () => {
  const list = tools(async (url, options) => {
    assert.equal(new URL(url).pathname, `/api/v4/channels/${config.channelId}/posts`);
    assert.equal(options.headers.Authorization, "Bearer placeholder");
    return { order: ["post-1"], posts: { "post-1": { id: "post-1", message: "Launch is Friday", create_at: 1 } } };
  }, { MATTERMOST_TOKEN: "placeholder" });
  const data = await result(list[1]);
  assert.equal(data.messages[0].text, "Launch is Friday");
  assert.ok(!JSON.stringify(data).includes("placeholder"));
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
  for (const patch of [{ clusterDomain: "test.example/collect" }, { demoId: "../other" }, { channelId: "../other" }]) {
    assert.throws(() => createSourceTools({ ...config, ...patch }), /source-reader configuration/);
  }
});

test("registration exposes only the five named assistant tools and briefing context only when enabled", async () => {
  const registered = [], hooks = [];
  const api = { registerTool: tool => registered.push(tool), on: (...args) => hooks.push(args) };
  registerSourceReaders(api, { enabled: false });
  assert.equal(registered.length, 0);
  registerSourceReaders(api, config);
  assert.deepEqual(registered.map(t => t.name), ["saw_read_email", "saw_read_chat", "saw_read_calendar", "saw_save_report", "saw_upload_summary"]);
  assert.equal(hooks[0][0], "before_prompt_build");
  assert.match(hooks[0][1]().prependSystemContext, /daily briefing/i);
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


test("tenant readers authenticate fixed sources and resolve only the assigned private team", async () => {
  const tenant = { ...config, demoId: "user-test", tenantUser: "user-test", channelId: undefined };
  const calls = [];
  // A migrated provider may retain its old alias alongside the canonical key.
  const list = createSourceTools(tenant, { env: { MM_TOKEN: "chat-marker", MATTERMOST_TOKEN: "stale-chat-marker", MAILPIT_AUTHORIZATION: "mail-marker", CALENDAR_AUTHORIZATION: "cal-marker" },
    read: async (url, options) => {
      calls.push(url);
      const u = new URL(url);
      if (u.hostname.startsWith("mailpit")) {
        assert.equal(options.headers.Authorization, "mail-marker");
        return { messages: [], total: 0 };
      }
      if (u.hostname.startsWith("radicale")) {
        assert.equal(u.pathname, "/user-test/user-test/");
        assert.equal(options.headers.Authorization, "cal-marker");
        return "BEGIN:VCALENDAR\r\nEND:VCALENDAR";
      }
      assert.equal(options.headers.Authorization, "Bearer chat-marker");
      if (u.pathname === "/api/v4/users/me/teams") return [{ id: "team-id", name: "user-test", type: "I" }, { id: "other", name: "other", type: "I" }];
      if (u.pathname === "/api/v4/teams/team-id/channels/name/ai-platform") return { id: "a".repeat(26) };
      assert.equal(u.pathname, `/api/v4/channels/${"a".repeat(26)}/posts`);
      return { order: [], posts: {} };
    } });
  for (const t of list.slice(0,3)) await result(t);
  assert.equal(calls.length, 5);
  const denied = createSourceTools(tenant, { env: {} });
  await assert.rejects(() => result(denied[0]), /provider placeholder/);
  await assert.rejects(() => result(denied[2]), /provider placeholder/);
  const wrongTeam = createSourceTools(tenant, { env: { MATTERMOST_TOKEN: "marker" }, read: async () => [{id: "other", name:"other", type:"I"}] });
  await assert.rejects(() => result(wrongTeam[1]), /assigned private team/);
});

test("parallel source tools serialize requests to avoid overlapping Keycloak password grants", async () => {
  let active = false;
  const list = createSourceTools({ ...config, demoId: "user-test", tenantUser: "user-test" }, {
    env: { MAILPIT_AUTHORIZATION: "mail-marker", CALENDAR_AUTHORIZATION: "cal-marker" },
    read: async url => {
      assert.equal(active, false, "The identity server rejects concurrent password grants for one user");
      active = true;
      await new Promise(resolve => setImmediate(resolve));
      active = false;
      return new URL(url).hostname.startsWith("mailpit")
        ? { messages: [], total: 0 } : "BEGIN:VCALENDAR\r\nEND:VCALENDAR";
    },
  });
  const data = await Promise.all([result(list[0]), result(list[2])]);
  assert.deepEqual(data.map(item => item.source), ["email", "calendar"]);
});

test("a rejected source request does not prevent the next queued source from running", async () => {
  const list = tools(async url => {
    if (new URL(url).hostname.startsWith("mailpit")) throw new Error("identity unavailable");
    return "BEGIN:VCALENDAR\r\nEND:VCALENDAR";
  });
  const data = await Promise.allSettled([result(list[0]), result(list[2])]);
  assert.equal(data[0].status, "rejected");
  assert.equal(data[1].status, "fulfilled");
  assert.equal(data[1].value.source, "calendar");
});
