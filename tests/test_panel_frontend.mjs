// Tests for the Media Mgmt sidebar app (custom_components/media_mgmt/frontend).
//
// The panel is a plain web component, so it runs in Node with a small stand-in
// for the DOM. Home Assistant is replaced by a fake `hass` whose websocket
// answers come from tests/fixtures/panel_ws.json: real answers recorded from
// the backend, kept in step with it by tests/ha/test_panel_fixture.py.
//
// Run with: node --test tests/*.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const FIXTURE = JSON.parse(readFileSync(new URL("./fixtures/panel_ws.json", import.meta.url), "utf8"));

// ---- a small DOM ------------------------------------------------------------------

class FakeNode {
  constructor() {
    this.innerHTML = "";
    this.children = [];
    this.classList = { toggle() {}, add() {}, remove() {}, contains: () => false };
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }
}

class FakeShadowRoot extends FakeNode {
  constructor() {
    super();
    this.nodes = new Map();
    this.listeners = {};
  }

  // #main and #menu live as long as the shell, as in a browser.
  getElementById(id) {
    if (!this.innerHTML.includes(`id="${id}"`)) return null;
    if (!this.nodes.has(id)) this.nodes.set(id, new FakeNode());
    return this.nodes.get(id);
  }

  querySelector() {
    return null;
  }

  querySelectorAll() {
    return [];
  }

  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
}

class FakeElement {
  attachShadow() {
    this.shadowRoot = new FakeShadowRoot();
    return this.shadowRoot;
  }
}

const defined = new Map();
globalThis.HTMLElement = FakeElement;
globalThis.customElements = {
  define(name, cls) {
    defined.set(name, cls);
  },
  get(name) {
    return defined.get(name);
  },
};
const storage = new Map();
globalThis.localStorage = {
  getItem: (key) => (storage.has(key) ? storage.get(key) : null),
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: (key) => storage.delete(key),
};
globalThis.document = {
  hidden: false,
  createElement: () => new FakeNode(),
  addEventListener() {},
  removeEventListener() {},
};
globalThis.window = { confirm: () => true };

await import("../custom_components/media_mgmt/frontend/media-mgmt-panel.js");
const Panel = defined.get("media-mgmt-panel");

// ---- a fake Home Assistant --------------------------------------------------------

function fakeHass(overrides = {}) {
  const answers = { ...structuredClone(FIXTURE), ...overrides };
  const sent = [];
  return {
    sent,
    user: { id: answers["access/me"].user_id, is_admin: answers["access/me"].is_admin },
    language: "en",
    states: {},
    async callWS(msg) {
      sent.push(msg);
      let key = msg.type.replace("media_mgmt/", "");
      if (key === "history") key = `history/${msg.view || "songs"}`;
      if (!(key in answers)) throw { code: "unknown_command", message: `No answer for ${msg.type}` };
      const answer = answers[key];
      if (answer instanceof Error) throw answer;
      return structuredClone(answer);
    },
    async callService() {},
    connection: {
      subscribeMessage: async () => () => {},
    },
  };
}

// Let the panel's websocket calls (promises) finish.
const settle = async () => {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setImmediate(resolve));
};

async function openPanel(overrides) {
  const panel = new Panel();
  const hass = fakeHass(overrides);
  panel.narrow = false;
  panel.hass = hass;
  await settle();
  return { panel, hass, main: () => panel.shadowRoot.getElementById("main").innerHTML };
}

function clickTab(panel, tab) {
  panel._onClick({ target: { closest: () => ({ dataset: { tab } }) } });
}

// Rendering mistakes that show up as text on the page.
function assertClean(html, where) {
  for (const bad of ["undefined", "NaN", "[object Object]", "null</"]) {
    assert.ok(!html.includes(bad), `${where} shows "${bad}"`);
  }
}

const TABS = ["dashboard", "activity", "analytics", "library", "artists", "schedules", "rules", "speakers", "access"];

// ---- tests ------------------------------------------------------------------------

test("the dashboard shows the speaker and what it's playing", async () => {
  const { panel, main } = await openPanel();
  const html = main();
  assert.match(html, /Kids Room/);
  assert.match(html, /Clair de Lune/);
  assert.match(html, /Debussy/);
  assertClean(html, "dashboard");
  // Admins get the Speakers and Access tabs.
  assert.match(panel.shadowRoot.innerHTML, /data-tab="speakers"/);
  assert.match(panel.shadowRoot.innerHTML, /data-tab="access"/);
  panel.disconnectedCallback();
});

test("every tab renders from the backend's answers", async () => {
  const { panel, hass, main } = await openPanel();
  for (const tab of TABS) {
    clickTab(panel, tab);
    await settle();
    // Tabs that load on first show (activity, analytics...) render again then.
    if (tab === "activity") await panel._loadActivity();
    if (tab === "analytics") await panel._loadAnalytics();
    if (tab === "library") await panel._loadLibrary();
    if (tab === "artists") await panel._loadArtists();
    if (tab === "rules") await panel._loadSettings();
    await settle();
    const html = main();
    assert.ok(html.length > 0, `${tab} is empty`);
    assert.ok(!html.includes('class="error"'), `${tab} shows an error: ${html.slice(0, 300)}`);
    assertClean(html, tab);
  }
  const types = new Set(hass.sent.map((m) => m.type));
  for (const type of ["media_mgmt/profiles", "media_mgmt/activity", "media_mgmt/analytics", "media_mgmt/history", "media_mgmt/artists/list", "media_mgmt/settings/get", "media_mgmt/access/get", "media_mgmt/speakers/candidates"]) {
    assert.ok(types.has(type), `never asked for ${type}`);
  }
  panel.disconnectedCallback();
});

test("the Rules tab edits a copy of the settings", async () => {
  const { panel, main } = await openPanel();
  clickTab(panel, "rules");
  await panel._loadSettings();
  const draft = panel._draft;
  assert.deepEqual(draft.windows, [{ start: "20:30", end: "07:00", label: "Bedtime" }]);
  assert.deepEqual(draft.filter.artist, ["Baby Shark"]);
  // Editing the draft leaves what was loaded alone until it's saved.
  draft.filter.artist.push("Someone");
  assert.deepEqual(panel._settings.filter.artist, ["Baby Shark"]);
  const html = main();
  assert.match(html, /Bedtime/);
  assert.match(html, /Baby Shark/);
  panel.disconnectedCallback();
});

test("the Schedules tab lists the saved schedule", async () => {
  const { panel, main } = await openPanel();
  clickTab(panel, "schedules");
  await settle();
  assert.match(main(), /Bedtime music/);
  panel.disconnectedCallback();
});

test("someone without access is turned away", async () => {
  const me = { ...FIXTURE["access/me"], allowed: false, is_admin: false };
  const { panel, hass, main } = await openPanel({ "access/me": me });
  assert.match(main(), /You don't have access to Media Mgmt/);
  // Nothing else is asked for, and there are no tabs.
  assert.deepEqual(hass.sent.map((m) => m.type), ["media_mgmt/access/me"]);
  assert.ok(!panel.shadowRoot.innerHTML.includes("data-tab="));
  panel.disconnectedCallback();
});

test("no speakers yet: admins are offered to add one, others to ask", async () => {
  const empty = { ...FIXTURE.profiles, profiles: [] };
  const admin = await openPanel({ profiles: empty });
  assert.match(admin.main(), /No speakers yet/);
  assert.match(admin.main(), /Add a speaker/);
  admin.panel.disconnectedCallback();

  const me = { ...FIXTURE["access/me"], is_admin: false };
  const parent = await openPanel({ profiles: empty, "access/me": me });
  assert.match(parent.main(), /Ask an admin to add a speaker/);
  // Parents who aren't admins don't get Speakers or Access.
  assert.ok(!parent.panel.shadowRoot.innerHTML.includes('data-tab="access"'));
  parent.panel.disconnectedCallback();
});

test("a failed load says why instead of showing nothing", async () => {
  const { panel, main } = await openPanel({ profiles: new Error("Media Mgmt is starting") });
  assert.match(main(), /Media Mgmt is starting/);
  assert.match(main(), /class="error"/);
  panel.disconnectedCallback();
});

test("names from the backend are escaped", async () => {
  const profiles = structuredClone(FIXTURE.profiles);
  profiles.profiles[0].name = '<img src=x onerror="alert(1)">';
  const { panel, main } = await openPanel({ profiles });
  assert.ok(!main().includes("<img src=x"), "a speaker name was inserted as HTML");
  assert.match(main(), /&lt;img src=x/);
  panel.disconnectedCallback();
});

test("leaving the page stops the timers and the subscription", async () => {
  const { panel } = await openPanel();
  assert.ok(panel._timer, "refreshes while open");
  panel.disconnectedCallback();
  assert.equal(panel._timer, null);
  assert.equal(panel._progressTimer, null);
  assert.equal(panel._unsub, null);
});
