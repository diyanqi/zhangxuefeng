
import { $, jget, jpost, jput, toast, ago, CFG_KEYS } from "./api.js";
import { tplDevice, tplChecks, tplRoutes, tplPreview } from "./ui.js";
import {
  initMap, invalidateMap, clearMapLayers, clearPinMarker, drawConfirmedPin,
  drawPinBase, drawMapFallback, drawMapOSM, ensureLeaflet,
} from "./map.js";

let logCursor = 0;
let logTimer = null;
let showAll = false;
let lastTs = 0;
let previewCache = null;
let MODE = "run";


function setMode(m) {
  MODE = m;
  $("tabRun").className = "btn btn-sm " + (m === "run" ? "btn-dark" : "btn-outline-secondary");
  $("tabPin").className = "btn btn-sm " + (m === "pin" ? "btn-dark" : "btn-outline-secondary");
  $("paneRun").classList.toggle("d-none", m !== "run");
  $("panePin").classList.toggle("d-none", m !== "pin");
  $("cfgCard").classList.toggle("d-none", m !== "run");
  $("modeHint").textContent = m === "run" ? "沿路线按配速跑" : "地图选点，手机定位到该点";
  clearMapLayers();
  if (m === "run") loadPreview();
  else drawPinBase();
  invalidateMap();
}


async function refreshStatus(silent) {
  try {
    const s = await jget("/api/status");
    window._lastList = s.checks;
    const by = {};
    s.checks.forEach(c => by[c.id] = c.status);
    window._lastChecks = {
      device: by.device, unlock: by.unlock, devmode: by.devmode,
      deviceDetail: (s.checks.find(c => c.id === "device") || {}).detail,
    };
    $("deviceBody").innerHTML = tplDevice(s.device);
    $("checks").innerHTML = tplChecks(s.checks, showAll);
    lastTs = Date.now() / 1000;
    $("updAt").textContent = "● " + ago(s.ts || lastTs);
    const r = s.run;
    const dot = $("runDot");
    const txt = $("runstateTxt");
    if (r.running) {
      dot.classList.add("on");
      if (r.mode === "pin") {
        txt.textContent = `定点中 · ${r.pin ? r.pin.lat + "," + r.pin.lng : ""} · pid ${r.pid}`;
        $("pinStateBadge").textContent = `定点中 ${r.pin ? r.pin.lat + "," + r.pin.lng : ""}`;
        $("pinStateBadge").className = "badge bg-success";
        drawConfirmedPin(r.pin);
      } else {
        txt.textContent = `跑步中 · pid ${r.pid}`;
        $("runStateBadge").textContent = `跑步中 pid ${r.pid}`;
        $("runStateBadge").className = "badge bg-success";
      }
    } else {
      dot.classList.remove("on");
      txt.textContent = r.exit_code != null ? `空闲 · 上次退出码 ${r.exit_code}` : "空闲";
      $("runStateBadge").textContent = "未运行";
      $("runStateBadge").className = "badge bg-light text-dark border";
      $("pinStateBadge").textContent = "未定点";
      $("pinStateBadge").className = "badge bg-light text-dark border";
      clearPinMarker();
    }
    const busy = !!r.running;
    ["btnStart", "btnPinSet"].forEach(id => { $(id).disabled = busy; });
    ["btnStop", "btnPinClear"].forEach(id => { $(id).disabled = !busy; });
    if (r.running && !logTimer) logTimer = setInterval(pollLog, 1000);
    if (!r.running && logTimer) { clearInterval(logTimer); logTimer = null; }
  } catch (e) {
    $("runstateTxt").textContent = "连接失败 · 点刷新重试";
    ["btnStart", "btnStop", "btnPinSet", "btnPinClear"].forEach(id => { $(id).disabled = true; });
    if (!silent) toast("状态刷新失败: " + e);
  }
}

function toggleShowAll(e) {
  if (e) e.preventDefault();
  showAll = !showAll;
  $("toggleChecks").textContent = showAll ? "只看异常" : "展开全部";
  if (window._lastList) $("checks").innerHTML = tplChecks(window._lastList, showAll);
}

async function pollLog() {
  try {
    const d = await jget("/api/log?cursor=" + logCursor);
    logCursor = d.cursor;
    if (d.lines.length) {
      const el = $("log");
      for (const e of d.lines) { el.textContent += e.line.split("\r").pop() + "\n"; }
      el.scrollTop = el.scrollHeight;
      $("logCount").textContent = el.textContent.split("\n").length + " 行";
    }
  } catch (e) {}
}

function clearLog() {
  $("log").textContent = "";
  $("logCount").textContent = "0 行";
}


async function runStart() {
  toast("启动中…正在过门禁");
  const r = await jpost("/api/run/start");
  toast(r.msg);
  logCursor = 0;
  $("log").textContent = "";
  refreshStatus(true);
  pollLog();
}

async function runStop() {
  toast("停止中…等清定位（约几秒），勿关页面");
  const r = await jpost("/api/run/stop");
  toast(r.msg);
  refreshStatus(true);
  pollLog();
}


async function portCheck() {
  const p = ($("p_port").value || location.port || "8123").trim();
  const el = $("portmsg");
  el.textContent = "检测中…";
  try {
    const d = await jget("/api/port/check?port=" + encodeURIComponent(p));
    el.textContent = d.detail + (d.pids && d.pids.length ? " · pid " + d.pids.join(",") : "");
    toast(d.detail);
  } catch (e) { el.textContent = "检测失败: " + e; }
}

async function portKill() {
  const p = ($("p_port").value || location.port || "8123").trim();
  const el = $("portmsg");
  if (!confirm("只会 kill 端口 " + p + " 上的同类服务 (本项目 WebUI)，其他服务拒绝执行。继续？")) return;
  el.textContent = "kill 中…";
  const r = await jpost("/api/port/kill", { port: parseInt(p) });
  el.textContent = r.msg || r.error;
  toast(r.msg || r.error);
}


async function pinSet() {
  const lat = $("pinLat").value.trim();
  const lng = $("pinLng").value.trim();
  if (!lat || !lng) { toast("先在地图上点一下，或手动输入经纬度"); return; }
  toast("定点中…正在过门禁");
  const r = await jpost("/api/pin/start", { lat: parseFloat(lat), lng: parseFloat(lng) });
  toast(r.msg);
  $("pinMsg").textContent = r.msg;
  logCursor = 0;
  $("log").textContent = "";
  refreshStatus(true);
  pollLog();
}

async function pinClear() {
  toast("清除中…等清定位（约几秒），勿关页面");
  const r = await jpost("/api/pin/stop");
  toast(r.msg);
  $("pinMsg").textContent = r.msg;
  refreshStatus(true);
  pollLog();
}


async function loadCfg() {
  const d = await jget("/api/config");
  const c = d.config;
  for (const k of CFG_KEYS) {
    let v = c[k];
    if (v === null || v === undefined) v = "";
    $("c_" + k).value = v;
  }
}

async function saveCfg() {
  const g = id => $("c_" + id).value.trim();
  const num = v => v === "" ? null : parseFloat(v);
  if (!g("pace")) { toast("pace 不能为空, 如 4:25"); return; }
  const body = {
    pace: g("pace") || null, dt: num(g("dt")),
    fit_curve: (g("fit_curve") === "true" || g("fit_curve") === "1"),
    fit_samples: parseInt(g("fit_samples")), wander_m: num(g("wander_m")),
    wander_step_m: num(g("wander_step_m")), wander_step_hz: num(g("wander_step_hz")),
    pace_var_s: num(g("pace_var_s")), lap_jitter_s: num(g("lap_jitter_s")),
  };
  Object.keys(body).forEach(k => { if (body[k] === null && k !== "pace") delete body[k]; });
  const r = await jput("/api/config", body);
  $("cfgmsg").textContent = r.msg || r.error;
  toast(r.msg || r.error);
  refreshStatus(true);
  loadPreview();
}

async function loadRoutes() {
  try {
    const d = await jget("/api/routes");
    tplRoutes(d);
  } catch (e) {}
}

async function selectRoute(f) {
  const r = await jpost("/api/routes/select", { file: f });
  toast(r.msg);
  $("routemsg").textContent = r.msg;
  loadRoutes();
  refreshStatus(true);
  loadPreview();
}

async function createRoute() {
  const r = await jpost("/api/routes/create", { file: $("n_file").value, content: $("n_content").value });
  toast(r.msg);
  $("routemsg").textContent = r.msg;
  loadRoutes();
  refreshStatus(true);
  loadPreview();
}

async function optimizeRoute() {
  const el = $("optimsg");
  el.textContent = "优化中…";
  const r = await jpost("/api/routes/optimize", { spacing_m: parseFloat($("o_spacing").value || "5") });
  el.textContent = r.msg || r.error;
  toast(r.msg || r.error);
  loadRoutes();
  refreshStatus(true);
  loadPreview();
}


async function loadPreview() {
  if (MODE !== "run") return;
  try {
    const d = await jget("/api/preview");
    previewCache = d;
    tplPreview(d);
    if (d.error) return;
    if (window.L && d.wgs_raw && d.wgs_raw.length) drawMapOSM(d);
    else { drawMapFallback(d.raw, d.lap); ensureLeaflet(loadPreview); }
  } catch (e) {}
}

async function refreshAll(manual) {
  await refreshStatus(!manual);
  loadCfg();
  loadRoutes();
  loadPreview();
  pollLog();
  if (manual) toast("已刷新");
}


initMap({
  isPinMode: () => MODE === "pin",
  onPick: (lat, lng) => {
    $("pinLat").value = lat;
    $("pinLng").value = lng;
    $("pinMsg").textContent = `已选 ${lat},${lng}（WGS-84），点「设为手机定位」生效`;
  },
});

Object.assign(window, {
  setMode, refreshStatus, toggleShowAll, pollLog, clearLog,
  runStart, runStop, portCheck, portKill, pinSet, pinClear,
  loadCfg, saveCfg, loadRoutes, selectRoute, createRoute, optimizeRoute,
  loadPreview, refreshAll,
});

setInterval(() => {
  if ($("autoRef").checked) refreshStatus(true);
  else if (lastTs) $("updAt").textContent = "○ 已暂停自动刷新 · " + ago(lastTs);
}, 3000);
setInterval(() => {
  if ($("autoRef").checked && lastTs) $("updAt").textContent = "● " + ago(lastTs);
}, 1000);

setMode("run");
refreshAll();
setInterval(() => { if (!document.hidden) loadPreview(); }, 15000);
window.addEventListener("resize", () => invalidateMap());
