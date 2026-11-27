// The script of index.html: fetches the published plugins.json and builds the page.
// A classic deferred script rather than a module, so the page also works opened from disk
// (browsers refuse module scripts from file:// URLs).
"use strict";

// Every value comes from plugins.json, so the page only sets textContent and checked
// URLs: nothing from the index is ever parsed as HTML.

// The index to list: the plugins.json next to the page when it's served over HTTP (on
// GitHub Pages, the official index the app reads; with make serve, the working tree's),
// the published one when the page is opened from disk.
const PUBLISHED_INDEX = "https://bzhmaddog.github.io/artwork-creator-plugins/plugins.json";
const DEFAULT_INDEX = location.protocol === "file:" ? PUBLISHED_INDEX : new URL("plugins.json", location.href).href;
const DEFAULT_TITLE = document.title;

const KINDS = { python: "Python", library: "Native library" };
const KIND_BADGES = { python: "text-bg-primary", library: "text-bg-warning" };
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

// A link only for http(s) URLs; anything else is shown as text.
function link(url, text) {
  try {
    const parsed = new URL(url, location.href);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") {
      return el("a", { href: parsed.href, rel: "noopener" }, text);
    }
  } catch (e) {
    // Not a URL: falls through to text.
  }
  return document.createTextNode(text);
}

const PLATFORMS = {
  any: "any platform",
  "linux-x86_64": "Linux x86-64",
  "linux-aarch64": "Linux ARM64",
  "windows-x86_64": "Windows x86-64",
  "windows-aarch64": "Windows ARM64",
  "macos-x86_64": "macOS x86-64",
  "macos-aarch64": "macOS ARM64",
};

// What a version needs: app and SDK requirements (engines, or the older min_app and sdk
// fields), the library ABI, and the platforms it has files for.
function requirementsText(v) {
  const parts = [];
  const app = v.engines?.app || (v.min_app ? ">=" + v.min_app : null);
  if (app) parts.push("App " + app);
  const sdk = v.engines?.sdk || v.sdk;
  if (sdk) parts.push("SDK " + sdk);
  if (v.abi !== undefined) parts.push("ABI " + v.abi);
  const platforms = Object.keys(v.files || {});
  if (platforms.length) parts.push(platforms.map((p) => PLATFORMS[p] || p).join(", "));
  return parts.join(" · ");
}

// Whether a version reads the saved settings and documents of earlier ones.
// isOldest: no earlier version, so there's nothing to break.
function settingsCompatibility(v, isOldest) {
  if (!v.compatible_from || isOldest) return null;
  if (v.compatible_from === v.version) {
    return el("span", { class: "badge text-bg-danger" }, "Breaks settings of earlier versions");
  }
  return el("span", { class: "text-body-secondary" }, "Reads settings from v" + v.compatible_from + " on");
}

function versionItem(v, isLatest, isOldest) {
  const requirements = requirementsText(v);
  const settings = settingsCompatibility(v, isOldest);
  let compatibility = null;
  if (requirements || settings) {
    compatibility = el("div", { class: "d-flex flex-wrap align-items-center gap-2 small mt-1" },
      requirements ? el("span", { class: "text-body-secondary" }, requirements) : null,
      settings);
  }
  return el("div", { class: "version py-2" },
    el("div", { class: "d-flex justify-content-between align-items-baseline gap-2" },
      el("div", {},
        el("strong", {}, v.version),
        isLatest ? el("span", { class: "badge text-bg-success ms-2" }, "latest") : null),
      v.released ? el("small", { class: "text-body-secondary" }, v.released) : null),
    v.changes ? el("p", { class: "mb-0" }, v.changes) : null,
    compatibility);
}

// Versions newest first, whatever their order in the file.
function compareVersions(a, b) {
  const pa = String(a.version).split(/[.+-]/).map(Number);
  const pb = String(b.version).split(/[.+-]/).map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pb[i] || 0) - (pa[i] || 0);
    if (d) return d;
  }
  return 0;
}

// The effects and generators of the latest version, as a table: one row each, with the
// version since which every version has it (versions: newest first).
function providesTable(latest, versions) {
  const rows = [];
  for (const [key, type] of [["effects", "Effect"], ["generators", "Generator"]]) {
    for (const name of latest?.[key] || []) {
      const start = versions.indexOf(latest);
      let since = null;
      for (const v of versions.slice(start < 0 ? 0 : start)) {
        if (!(v[key] || []).includes(name)) break;
        since = v;
      }
      rows.push(el("tr", {},
        el("td", {}, name),
        el("td", {}, el("span", { class: "badge " + (key === "effects" ? "text-bg-info" : "text-bg-light") }, type)),
        el("td", { class: "text-body-secondary text-end" }, since ? "since v" + since.version : "")));
    }
  }
  if (!rows.length) return null;
  return el("table", { class: "table table-sm align-middle small mb-2 provides" },
    el("thead", {}, el("tr", {},
      el("th", { scope: "col" }, "Name"),
      el("th", { scope: "col" }, "Type"),
      el("th", { scope: "col", class: "text-end" }, "Added in"))),
    el("tbody", {}, ...rows));
}

// Kind, author and license badges, then the link to the source.
function badges(p) {
  const nodes = [el("span", { class: "badge " + (KIND_BADGES[p.kind] || "text-bg-secondary") }, KINDS[p.kind] || p.kind)];
  if (p.author) nodes.push(el("span", { class: "badge text-bg-secondary" }, "by " + p.author));
  if (p.license) nodes.push(el("span", { class: "badge text-bg-secondary" }, p.license));
  if (p.homepage) {
    const source = link(p.homepage, "Source");
    if (source.nodeType === Node.ELEMENT_NODE) source.className = "small";
    nodes.push(source);
  }
  return nodes;
}

function card(p) {
  const versions = [...(p.versions || [])].sort(compareVersions);
  const latest = versions.find((v) => v.version === p.latest) || versions[0];
  const others = versions.filter((v) => v !== latest);
  const oldest = versions.at(-1);

  const provides = providesTable(latest, versions);
  const node = el("article", { class: "card mb-3 plugin", id: p.id },
    el("div", { class: "card-body" },
      el("div", { class: "d-flex justify-content-between align-items-baseline gap-2" },
        el("h2", { class: "card-title h5 mb-1" }, p.name || p.id),
        latest ? el("span", { class: "text-body-secondary" }, "v" + latest.version) : null),
      p.description ? el("p", { class: "card-text mb-2" }, p.description) : null,
      el("div", { class: "d-flex flex-wrap align-items-center gap-2 mb-2" }, ...badges(p)),
      provides,
      latest ? versionItem(latest, true, latest === oldest) : null),
    others.length
      ? el("details", { class: "card-footer previous" },
          el("summary", { class: "text-uppercase text-body-secondary small fw-semibold py-1" },
            "Previous versions (" + others.length + ")"),
          ...others.map((v) => versionItem(v, false, v === oldest)))
      : null);

  // Text the filter searches.
  node.dataset.search = [p.id, p.name, p.description, p.author, p.kind, ...(latest?.effects || []), ...(latest?.generators || [])]
    .filter(Boolean).join(" ").toLowerCase();
  return node;
}

function applyFilter() {
  const query = document.getElementById("filter").value.trim().toLowerCase();
  const cards = document.querySelectorAll("#plugins .plugin");
  let shown = 0;
  for (const c of cards) {
    const match = !query || c.dataset.search.includes(query);
    c.classList.toggle("d-none", !match);
    if (match) shown++;
  }
  document.getElementById("count").textContent =
    shown === cards.length ? cards.length + " plugins" : shown + " of " + cards.length + " plugins";
}

// Bumped by each load(), so that a load which a newer one replaced drops its results.
let currentLoad = 0;

// Lists and shows the plugins of the index at url.
async function load(url) {
  const id = ++currentLoad;
  const status = document.getElementById("status");
  const list = document.getElementById("plugins");
  list.replaceChildren();
  document.getElementById("count").textContent = "";
  document.getElementById("title").textContent = DEFAULT_TITLE;
  document.title = DEFAULT_TITLE;
  document.getElementById("index-link").href = url;
  status.className = "text-body-secondary py-5";
  status.textContent = "Loading plugins.json…";
  status.hidden = false;
  try {
    const response = await fetch(url, { cache: "no-cache" });
    if (id !== currentLoad) return;
    if (!response.ok) throw new Error("HTTP " + response.status);
    const index = await response.json();
    if (id !== currentLoad) return;
    if (!index || !Array.isArray(index.plugins)) throw new Error("no plugins list in the file");

    const title = index.name || DEFAULT_TITLE;
    document.getElementById("title").textContent = title;
    document.title = title;
    const plugins = [...index.plugins].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));
    list.append(...plugins.map(card));
    status.hidden = true;
    applyFilter();
  } catch (e) {
    if (id !== currentLoad) return;
    status.className = "alert alert-danger";
    status.textContent = "Couldn't load " + url + ": " + e.message;
  }
}

// The indexes to choose from, only when the page names a list of them: make serve
// (scripts/serve.py) adds <meta name="index-sources" content="sources.json"> to the page
// it serves, so the published page never shows the select. Each source is
// {id, label, url}; null when there's no list or it can't be read.
async function indexSources() {
  const meta = document.querySelector('meta[name="index-sources"]');
  if (!meta) return null;
  try {
    const response = await fetch(new URL(meta.content, location.href), { cache: "no-store" });
    if (!response.ok) return null;
    const sources = (await response.json())?.sources;
    return Array.isArray(sources) && sources.length ? sources : null;
  } catch (e) {
    console.warn("index sources:", e);
    return null;
  }
}

// The select of the sources; the choice is kept in the address (?index=<id>), so a reload
// shows the same index. Returns the URL of the chosen index.
function sourceSelect(sources) {
  const select = document.getElementById("source");
  const params = new URLSearchParams(location.search);
  const chosen = sources.find((s) => s.id === params.get("index")) || sources[0];
  select.replaceChildren(...sources.map((s) => el("option", { value: s.id }, s.label || s.id)));
  select.value = chosen.id;
  select.hidden = false;
  const urlOf = (s) => new URL(s.url, location.href).href;
  select.addEventListener("change", () => {
    const source = sources.find((s) => s.id === select.value);
    params.set("index", source.id);
    history.replaceState(null, "", "?" + params);
    void load(urlOf(source));
  });
  return urlOf(chosen);
}

async function main() {
  document.getElementById("filter").addEventListener("input", applyFilter);
  const sources = await indexSources();
  await load(sources ? sourceSelect(sources) : DEFAULT_INDEX);
}

// A classic script can't use top-level await (see the top); main() reports its own errors.
void main();
