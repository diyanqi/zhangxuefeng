
export const $ = id => document.getElementById(id);

export async function jget(u) {
  const r = await fetch(u);
  return r.json();
}

export async function jpost(u, b) {
  const r = await fetch(u, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(b || {}),
  });
  return r.json();
}

export async function jput(u, b) {
  const r = await fetch(u, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(b),
  });
  return r.json();
}

export function toast(t) {
  const e = $("toast");
  e.textContent = t;
  e.classList.add("show");
  clearTimeout(e._t);
  e._t = setTimeout(() => e.classList.remove("show"), 3200);
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

export function ago(ts) {
  if (!ts) return "尚未同步";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 2 ? "刚刚更新" : s + " 秒前更新";
}

export const CFG_KEYS = ["pace", "dt", "fit_curve", "fit_samples",
  "wander_m", "wander_step_m", "wander_step_hz", "pace_var_s", "lap_jitter_s"];
