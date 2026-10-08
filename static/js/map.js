
import { $, toast } from "./api.js";

export const ZJU_FALLBACK = [30.304, 120.083];

let leafMap = null;
let leafLayers = [];
let runnerTimer = null;
let pickMarker = null;
let pinMarker = null;
let hooks = { isPinMode: () => false, onPick: () => {} };

export function initMap(h) {
  hooks = { ...hooks, ...(h || {}) };
}

export function ensureMap(center, zoom) {
  if (leafMap) return leafMap;
  leafMap = window.L.map("map").setView(center || ZJU_FALLBACK, zoom || 15);
  window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(leafMap);
  leafMap.on("click", e => {
    if (!hooks.isPinMode()) return;
    const lat = +e.latlng.lat.toFixed(6);
    const lng = +e.latlng.lng.toFixed(6);
    if (pickMarker) leafMap.removeLayer(pickMarker);
    pickMarker = window.L.circleMarker([lat, lng],
      { radius: 8, color: "#fff", weight: 2, fillColor: "#f59e0b", fillOpacity: 1 }).addTo(leafMap);
    pickMarker.bindTooltip("已选点，点击「设为手机定位」生效").openTooltip();
    hooks.onPick(lat, lng);
  });
  return leafMap;
}

export function invalidateMap() {
  if (window.L && leafMap) setTimeout(() => leafMap.invalidateSize(), 60);
}

export function clearMapLayers() {
  if (!window.L || !leafMap) return;
  leafLayers.forEach(l => { try { leafMap.removeLayer(l); } catch (e) {} });
  leafLayers = [];
  if (runnerTimer) { clearInterval(runnerTimer); runnerTimer = null; }
  if (pinMarker) { leafMap.removeLayer(pinMarker); pinMarker = null; }
}

export function clearPinMarker() {
  if (window.L && leafMap && pinMarker) {
    leafMap.removeLayer(pinMarker);
    pinMarker = null;
  }
}

export function drawConfirmedPin(pin) {
  if (!pin || !window.L || !leafMap) return;
  if (pinMarker) {
    const o = pinMarker.getLatLng();
    if (Math.abs(o.lat - pin.lat) < 1e-9 && Math.abs(o.lng - pin.lng) < 1e-9) return;
    leafMap.removeLayer(pinMarker);
  }
  pinMarker = window.L.circleMarker([pin.lat, pin.lng],
    { radius: 9, color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 1 }).addTo(leafMap);
  pinMarker.bindTooltip("手机定位在这里");
}

export function drawPinBase() {
  if (!window.L) { drawPinFallback(); ensureLeaflet(); return; }
  $("map_fallback").style.display = "none";
  $("map").style.display = "block";
  ensureMap(ZJU_FALLBACK, 15);
  setTimeout(() => leafMap.invalidateSize(), 50);
}

export function drawPinFallback() {
  $("map").style.display = "none";
  const cv = $("map_fallback");
  cv.style.display = "block";
  const ctx = cv.getContext("2d");
  const W = cv.clientWidth || 600;
  ctx.clearRect(0, 0, W, 340);
  ctx.fillStyle = "#64748b";
  ctx.font = "13px sans-serif";
  ctx.fillText("离线模式：地图不可用，请联网后使用自由选点", 12, 20);
}

export function drawMapFallback(raw, lap) {
  $("map").style.display = "none";
  const cv = $("map_fallback");
  cv.style.display = "block";
  const ctx = cv.getContext("2d");
  const W = cv.clientWidth;
  const H = 340;
  const dpr = window.devicePixelRatio || 1;
  cv.width = W * dpr;
  cv.height = H * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  const all = raw.concat(lap);
  if (!all.length) return;
  const mla = Math.min(...all.map(p => p.lat));
  const xla = Math.max(...all.map(p => p.lat));
  const mlo = Math.min(...all.map(p => p.lng));
  const xlo = Math.max(...all.map(p => p.lng));
  const kx = Math.cos((mla + xla) / 2 * Math.PI / 180);
  const sx = (xlo - mlo) * kx || 1e-9;
  const sy = (xla - mla) || 1e-9;
  const sc = Math.min((W - 40) / sx, (H - 40) / sy);
  const X = lng => (lng - mlo) * kx * sc + (W - sx * sc) / 2;
  const Y = lat => H - ((lat - mla) * sc + (H - sy * sc) / 2);
  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  lap.forEach((p, i) => i ? ctx.lineTo(X(p.lng), Y(p.lat)) : ctx.moveTo(X(p.lng), Y(p.lat)));
  ctx.closePath();
  ctx.stroke();
  ctx.fillStyle = "#f43f5e";
  for (const p of raw) { ctx.beginPath(); ctx.arc(X(p.lng), Y(p.lat), 2.2, 0, 7); ctx.fill(); }
  ctx.fillStyle = "#16a34a";
  ctx.beginPath();
  ctx.arc(X(raw[0].lng), Y(raw[0].lat), 4.5, 0, 7);
  ctx.fill();
  ctx.fillStyle = "#64748b";
  ctx.font = "12px sans-serif";
  ctx.fillText("离线模式：蓝线=单圈轨迹 红点=路线点 绿点=起点", 10, 16);
}

export function drawMapOSM(d) {
  $("map_fallback").style.display = "none";
  $("map").style.display = "block";
  ensureMap([d.wgs_raw[0][0], d.wgs_raw[0][1]], 15);
  clearMapLayers();
  const lapLine = window.L.polyline(d.wgs_lap, { color: "#2563eb", weight: 4 }).addTo(leafMap);
  leafLayers.push(lapLine);
  d.wgs_raw.forEach(p => {
    leafLayers.push(window.L.circleMarker(p,
      { radius: 2.5, color: "#f43f5e", weight: 1, fillOpacity: 0.85 }).addTo(leafMap));
  });
  leafLayers.push(window.L.circleMarker(d.wgs_raw[0],
    { radius: 6, color: "#16a34a", fillOpacity: 1, weight: 2, fillColor: "#16a34a" }).addTo(leafMap));
  const runner = window.L.circleMarker(d.wgs_lap[0],
    { radius: 7, color: "#ffffff", weight: 2, fillColor: "#2563eb", fillOpacity: 1 }).addTo(leafMap);
  leafLayers.push(runner);
  runner.bindTooltip("配速试算小人：按单圈用时循环跑");
  const t0 = Date.now();
  const n = d.wgs_lap.length;
  runnerTimer = setInterval(() => {
    const el = (Date.now() - t0) / 1000 % d.lap_s;
    runner.setLatLng(d.wgs_lap[Math.floor(el / d.lap_s * n) % n]);
  }, 500);
  leafMap.fitBounds(lapLine.getBounds(), { padding: [25, 25] });
}


export function ensureLeaflet(onReady) {
  if (window.L || window._lflTried) return;
  window._lflTried = true;
  const c = document.createElement("link");
  c.rel = "stylesheet";
  c.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
  document.head.appendChild(c);
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
  s.onload = function () {
    toast("在线地图库加载成功");
    if (typeof onReady === "function") onReady();
  };
  document.head.appendChild(s);
}
