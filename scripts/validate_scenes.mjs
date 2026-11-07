// Render every raw answer in headless Chromium and decide if it is a working scene.
// Thresholds are tuned by eye: look at the shots folder after the first pilot.
// --mode glb scores the asset by the GLB it exports instead of by motion.
import { chromium } from "playwright";
import { PNG } from "pngjs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseGlb } from "./glb_check.mjs";

const BLANK_MIN_COLORS = 12;      // fewer distinct colours (after quantising) than this = blank
const STATIC_MIN_DIFF = 0.002;    // share of pixels that must change between two frames
const WAIT_MS = 2500;
const CONCURRENCY = 4;
const EXPORT_TIMEOUT_MS = 20000;
const THREE_VERSION = "0.160.0";
const CDN = "https://cdnjs.cloudflare.com/ajax/libs/three.js/0.160.0/three.module.min.js";
const ALLOWED_HOSTS = new Set(["cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com"]);
const SCENE_URL = "http://scene.local/";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const LOCAL_THREE = path.join(ROOT, "node_modules/three/build/three.module.min.js");

const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > -1 ? process.argv[i + 1] : d; };
const mode = arg("mode", "scene");
if (mode !== "scene" && mode !== "glb") {
  console.error("--mode must be scene or glb");
  process.exit(2);
}
const rawDir = arg("raw", "data/raw"), scenesDir = arg("scenes", "data/scenes");
const shotsDir = arg("shots", "data/shots"), reportPath = arg("report", "data/validation.jsonl");
const glbDir = arg("glb-dir", "data/glb");
// GLB mode: accept any Three.js add-on (OrbitControls, RoundedBoxGeometry, ...) from the allowed hosts, served locally.
// The benchmark asks whether the exported GLB works, so a model is not failed for using add-ons its own prompt allows.
const allowAddons = process.argv.includes("--allow-addons");
// GLB mode: serve a page the Three.js version it asked for when it is cached (scripts/fetch_three.mjs fills the cache);
// otherwise fall back to the local 0.160.0 and flag version_rewritten.
const threeVersionsDir = path.resolve(arg("three-versions-dir", path.join(ROOT, ".cache/three")));
const loadTimeout = Number(arg("load-timeout", "15000"));
for (const d of [scenesDir, shotsDir, path.dirname(reportPath)]) fs.mkdirSync(d, { recursive: true });
if (mode === "glb") fs.mkdirSync(glbDir, { recursive: true });

// Set VALIDATE_REQUEST_LOG to a file path to record every request that was not served locally.
// The offline tests use it to prove that no page reaches the network.
const requestLogPath = process.env.VALIDATE_REQUEST_LOG || null;
const outsideRequests = [];

function extractHtml(text) {
  const fence = text.match(/```html\s*\n([\s\S]*?)```/i);
  if (fence) return fence[1].trim();
  const doc = text.match(/<!doctype html[\s\S]*<\/html>/i);
  if (doc) return doc[0];
  // GLB mode only: a reply that starts straight with <html> is still a page (scene mode keeps its old rule)
  if (mode === "glb") { const bare = text.match(/<html[\s\S]*<\/html>/i); if (bare) return bare[0]; }
  return null;
}

function staticChecks(html) {
  const r = [];
  // an import map may alias a bare name (e.g. "three") to the pinned CDN URL; resolve it before judging
  const map = {};
  for (const m of html.matchAll(/<script[^>]+type=["']importmap["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    try { Object.assign(map, JSON.parse(m[1]).imports || {}); } catch { r.push("bad_importmap"); }
  }
  const imports = [...html.matchAll(/from\s+["']([^"']+)["']|import\s+["']([^"']+)["']/g)].map(m => map[m[1] || m[2]] || m[1] || m[2]);
  if (Object.values(map).some(u => u !== CDN)) r.push("external_dep");
  if (imports.some(u => /examples\/(jsm|js)|OrbitControls/i.test(u))) r.push("bad_import");
  if (imports.some(u => u !== CDN)) r.push("external_dep");
  if (/<script[^>]+src=/i.test(html)) r.push("external_dep");
  if (/\beval\s*\(/.test(html)) r.push("eval");
  if (!/requestAnimationFrame|setAnimationLoop/.test(html)) r.push("no_loop");
  return [...new Set(r)];
}

// GLB mode keeps Three.js core and the GLTFExporter addon, from any of the three hosts and any version.
function classifyGlbUrl(raw) {
  if (typeof raw !== "string") return "external_dep";
  let url;
  try { url = new URL(raw); } catch { return "external_dep"; }
  if (url.protocol === "data:" || url.protocol === "about:" || url.protocol === "blob:") return "local";
  if (!ALLOWED_HOSTS.has(url.hostname)) return "external_dep";
  const p = decodeURIComponent(url.pathname);
  if (/\/build\/three\.module(?:\.min)?\.js$/.test(p)) return "core";
  if (/\/three\.js\/[\d.]+\/three\.module(?:\.min)?\.js$/.test(p)) return "core";
  if (/\/build\/three\.core(?:\.min)?\.js$/.test(p)) return "core_part"; // three.module.js re-exports it from r171 on
  if (/\/examples\/jsm\/$/.test(p)) return "addons";
  if (/\/examples\/jsm\/exporters\/GLTFExporter\.js$/.test(p)) return "exporter";
  // GLTFExporter imports this helper itself; it is served but not directly allowed in an answer.
  if (/\/examples\/jsm\/utils\/TextureUtils\.js$/.test(p)) return "exporter_dep";
  if (allowAddons && /\/examples\/jsm\/.+\.js$/.test(p)) return "addon";
  return "bad_import";
}

function versionRoot(raw) {
  // folder holding build/ and examples/jsm/ for the version the URL asks for (cached copy, else the local 0.160.0)
  const v = requestedThreeVersion(raw);
  if (v && v !== THREE_VERSION) {
    const dir = path.join(threeVersionsDir, v);
    if (fs.existsSync(path.join(dir, "build", "three.module.js"))) return { root: dir, version: v };
  }
  return { root: path.join(ROOT, "node_modules/three"), version: THREE_VERSION };
}

function jsmFile(raw) {
  const sub = decodeURIComponent(new URL(raw).pathname).split("/examples/jsm/")[1] || "";
  const base = path.join(versionRoot(raw).root, "examples/jsm");
  const file = path.resolve(base, sub);
  return file.startsWith(base + path.sep) && fs.existsSync(file) ? file : null;
}

function requestedThreeVersion(raw) {
  if (typeof raw !== "string") return null;
  const m = raw.match(/three@(\d+\.\d+\.\d+)/) || raw.match(/three\.js\/(\d+\.\d+\.\d+)\//);
  return m ? m[1] : null;
}

function resolveGlbSpecifier(spec, map) {
  if (typeof spec !== "string") return spec;
  if (/^(?:https?:|data:|blob:)/i.test(spec)) return spec;
  if (Object.prototype.hasOwnProperty.call(map, spec)) return map[spec];
  const prefixes = Object.keys(map).filter(k => k.endsWith("/") && spec.startsWith(k)).sort((a, b) => b.length - a.length);
  if (prefixes.length) return String(map[prefixes[0]]) + spec.slice(prefixes[0].length);
  return spec;
}

function staticChecksGlb(html, stats) {
  const r = [];
  const map = {};
  for (const m of html.matchAll(/<script[^>]+type=["']importmap["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    try { Object.assign(map, JSON.parse(m[1]).imports || {}); } catch { r.push("bad_importmap"); }
  }
  const specs = [...html.matchAll(/from\s+["']([^"']+)["']|import\s+["']([^"']+)["']/g)].map(m => m[1] || m[2]);
  const srcs = [...html.matchAll(/<script[^>]+src\s*=\s*["']([^"']+)["']/gi)].map(m => m[1]);
  const versions = [];
  const addons = new Set();
  for (const spec of [...specs, ...srcs]) {
    const resolved = resolveGlbSpecifier(spec, map);
    const kind = classifyGlbUrl(resolved);
    if (kind === "bad_import" || kind === "exporter_dep") r.push("bad_import");
    else if (kind === "external_dep") r.push("external_dep");
    else if (kind === "core" || kind === "exporter" || kind === "addon") {
      if (kind === "addon") addons.add(resolved.split("/examples/jsm/")[1]);
      const v = requestedThreeVersion(resolved);
      if (v) versions.push(v);
    }
  }
  for (const value of Object.values(map)) {
    if (typeof value !== "string") continue;
    const kind = classifyGlbUrl(value);
    if (kind === "bad_import" || kind === "exporter_dep") r.push("bad_import");
    else if (kind === "external_dep") r.push("external_dep");
    else if (kind === "core" || kind === "exporter" || kind === "addon") {
      const v = requestedThreeVersion(value);
      if (v) versions.push(v);
    }
  }
  if (addons.size) stats.addons = [...addons].sort();
  const other = versions.find(v => v !== THREE_VERSION);
  if (other) {
    stats.three_requested = other;
    const cached = fs.existsSync(path.join(threeVersionsDir, other, "build", "three.module.js"));
    stats.three_served = cached ? other : THREE_VERSION;
    if (!cached) stats.version_rewritten = true;
  }
  return [...new Set(r)];
}

function stats(buf) {
  const png = PNG.sync.read(buf);
  const colors = new Set();
  for (let i = 0; i < png.data.length; i += 4 * 7)
    colors.add((png.data[i] >> 4) << 8 | (png.data[i + 1] >> 4) << 4 | png.data[i + 2] >> 4);
  return { png, colors: colors.size };
}

function diffShare(a, b) {
  let n = 0, total = a.data.length / 4;
  for (let i = 0; i < a.data.length; i += 4)
    if (Math.abs(a.data[i] - b.data[i]) + Math.abs(a.data[i + 1] - b.data[i + 1]) + Math.abs(a.data[i + 2] - b.data[i + 2]) > 24) n++;
  return n / total;
}

function isServedLocally(url) {
  if (url.startsWith(SCENE_URL) || /^(?:data|blob|about):/.test(url)) return true;
  if (mode === "scene") return url === CDN;
  const kind = classifyGlbUrl(url);
  return kind === "core" || kind === "core_part" || kind === "exporter" || kind === "exporter_dep" || kind === "addons" || kind === "addon";
}

async function findExportTarget(page) {
  const candidates = page.locator('button, a, [role="button"]');
  const count = await candidates.count();
  for (let i = 0; i < count; i++) {
    const el = candidates.nth(i);
    if (!(await el.isVisible().catch(() => false))) continue;
    const text = await el.innerText().catch(() => "");
    if (/export|download|glb/i.test(text)) return el;
  }
  return null;
}

async function exportGlb(page, res, id, errors) {
  const target = await findExportTarget(page);
  if (!target) { res.reasons.push("no_export_button"); return; }

  const before = errors.length;
  const started = Date.now();
  const downloadPromise = page.waitForEvent("download", { timeout: EXPORT_TIMEOUT_MS }).catch(() => null);
  try {
    await target.click({ timeout: 5000 });
  } catch {
    // The download wait and page-error check below decide the reason.
  }
  const download = await Promise.race([
    downloadPromise,
    (async () => {
      while (Date.now() - started < EXPORT_TIMEOUT_MS) {
        if (errors.length > before) return null;
        await new Promise(r => setTimeout(r, 100));
      }
      return null;
    })(),
  ]);
  res.stats.export_ms = Date.now() - started;

  const raised = errors.length > before;
  if (raised) {
    res.reasons.push("export_error");
    res.stats.error = errors[before].slice(0, 300);
  }
  if (!download) {
    if (!raised) res.reasons.push("no_download");
    return;
  }
  const out = path.join(glbDir, id + ".glb");
  try {
    await download.saveAs(out);
  } catch (e) {
    res.reasons.push("no_download");
    res.stats.error = String(e.message || e).slice(0, 300);
    return;
  }
  const parsed = parseGlb(fs.readFileSync(out));
  res.stats.glb = parsed;
  if (!parsed.ok) res.reasons.push(parsed.reason);
}

async function validate(browser, file) {
  const id = path.basename(file, ".json");
  const raw = JSON.parse(fs.readFileSync(path.join(rawDir, file), "utf8"));
  const res = { id, ok: false, reasons: [], stats: {} };
  if (raw.finish_reason === "length") { res.reasons.push("truncated"); return res; }
  const html = extractHtml(raw.content || "");
  if (!html) { res.reasons.push("no_html"); return res; }
  fs.writeFileSync(path.join(scenesDir, id + ".html"), html);
  res.reasons.push(...(mode === "glb" ? staticChecksGlb(html, res.stats) : staticChecks(html)));
  if (res.reasons.length) return res;

  const ctx = await browser.newContext({ viewport: { width: 800, height: 600 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(String(e.message || e)));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  if (requestLogPath) {
    page.on("request", req => { if (!isServedLocally(req.url())) outsideRequests.push(req.url()); });
  }
  if (mode === "glb") {
    await page.route("**/*", route => {
      const url = route.request().url();
      if (/^(?:data|blob|about):/.test(url)) return route.continue();
      if (url === SCENE_URL) return route.fulfill({ body: html, contentType: "text/html" });
      const kind = classifyGlbUrl(url);
      const vr = versionRoot(url).root;
      const serve = (f) => (f && fs.existsSync(f) ? route.fulfill({ path: f, contentType: "text/javascript" }) : route.abort());
      if (kind === "core") return serve(path.join(vr, "build/three.module.js"));
      if (kind === "core_part") return serve(path.join(vr, "build/three.core.js"));
      if (kind === "exporter") return serve(path.join(vr, "examples/jsm/exporters/GLTFExporter.js"));
      if (kind === "exporter_dep") return serve(jsmFile(url));
      if (kind === "addon") return serve(jsmFile(url));
      return route.abort();
    });
  } else {
    await page.route(CDN, r => r.fulfill({ path: LOCAL_THREE, contentType: "text/javascript" }));
    await page.route(u => !u.href.startsWith("data:") && !u.href.startsWith("about:") && u.href !== CDN && !u.href.startsWith(SCENE_URL), r => r.abort());
    await page.route(SCENE_URL, r => r.fulfill({ body: html, contentType: "text/html" }));
  }
  try {
    await page.goto(SCENE_URL, { waitUntil: "load", timeout: loadTimeout });
    await page.waitForTimeout(WAIT_MS);
    const s1 = await page.screenshot();
    await page.waitForTimeout(600);
    const s2 = await page.screenshot();
    fs.writeFileSync(path.join(shotsDir, id + ".png"), s2);
    const a = stats(s1), b = stats(s2);
    res.stats = { ...res.stats, colors: b.colors, diff: diffShare(a.png, b.png) };
    if (errors.length) { res.reasons.push("js_error"); res.stats.error = errors[0].slice(0, 300); }
    if (b.colors < BLANK_MIN_COLORS) res.reasons.push("blank");
    if (mode !== "glb" && res.stats.diff < STATIC_MIN_DIFF) res.reasons.push("static");
    if (mode === "glb") await exportGlb(page, res, id, errors);
  } catch (e) {
    res.reasons.push("load_fail"); res.stats.error = String(e.message).slice(0, 300);
  } finally { await ctx.close(); }
  res.ok = res.reasons.length === 0;
  return res;
}

const files = fs.readdirSync(rawDir).filter(f => f.endsWith(".json")).sort();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const results = [];
let next = 0;
await Promise.all(Array.from({ length: CONCURRENCY }, async () => {
  while (next < files.length) {
    const f = files[next++];
    const r = await validate(browser, f);
    results.push(r);
    process.stdout.write(`${results.length}/${files.length} ${r.ok ? "ok" : r.reasons.join(",")}\n`);
  }
}));
await browser.close();
results.sort((a, b) => a.id.localeCompare(b.id));
fs.writeFileSync(reportPath, results.map(r => JSON.stringify(r)).join("\n") + "\n");
if (requestLogPath) fs.writeFileSync(requestLogPath, JSON.stringify(outsideRequests, null, 2) + "\n");
const counts = {};
for (const r of results) for (const x of r.ok ? ["ok"] : r.reasons) counts[x] = (counts[x] || 0) + 1;
console.log("\npass rate", (results.filter(r => r.ok).length / Math.max(1, results.length) * 100).toFixed(1) + "%", counts);
