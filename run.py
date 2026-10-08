import math
import random
import re
import time

from geopy.distance import geodesic

from driver import location

try:
    import config as _config_module

    def _cfg(key, default):
        return getattr(_config_module.config, key, default)
except Exception:
    def _cfg(key, default):
        return default


def bd09Towgs84(position):
    wgs_p = {}

    x_pi = 3.14159265358979324 * 3000.0 / 180.0
    pi = 3.141592653589793238462643383
    a = 6378245.0
    ee = 0.00669342162296594323

    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * pi) + 40.0 * math.sin(y / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * pi) + 320 * math.sin(y * pi / 30.0)) * 2.0 / 3.0
        return ret

    def transform_lon(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * pi) + 40.0 * math.sin(x / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * pi) + 300.0 * math.sin(x / 30.0 * pi)) * 2.0 / 3.0
        return ret

    x = position['lng'] - 0.0065
    y = position['lat'] - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)

    gcj_lng = z * math.cos(theta)
    gcj_lat = z * math.sin(theta)

    d_lat = transform_lat(gcj_lng - 105.0, gcj_lat - 35.0)
    d_lng = transform_lon(gcj_lng - 105.0, gcj_lat - 35.0)

    rad_lat = gcj_lat / 180.0 * pi
    magic = math.sin(rad_lat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)

    d_lng = (d_lng * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * pi)
    d_lat = (d_lat * 180.0) / (a * (1 - ee) / (magic * sqrt_magic) * pi)

    wgs_p["lat"] = gcj_lat * 2 - gcj_lat - d_lat
    wgs_p["lng"] = gcj_lng * 2 - gcj_lng - d_lng
    return wgs_p


def geodistance(p1, p2):
    return geodesic((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"])).m


def parse_pace(pace):
    if pace is None:
        return None
    if isinstance(pace, (int, float)):
        sec = float(pace)
        if sec <= 0:
            raise ValueError(f"非法 pace: {pace}")
        return sec
    s = str(pace).strip().replace("’", "'").replace("”", '"').replace("″", '"')
    if not s:
        return None
    m = re.match(r"^(\d+)\s*[:'分]\s*(\d+(?:\.\d+)?)\s*(?:\"|秒)?$", s)
    sec = int(m.group(1)) * 60 + float(m.group(2)) if m else float(s)
    if sec <= 0:
        raise ValueError(f"非法 pace: {pace}")
    return sec


def resolve_speed(pace=None):
    if pace is None:
        pace = _cfg("pace", None)
    sec = parse_pace(pace)
    if sec is None:
        raise ValueError("pace 不能为空, 如 \"4:25\"")
    return 1000.0 / sec


def speed_to_pace_str(v):
    sec = 1000.0 / v
    tot = int(round(sec))
    m, s = divmod(tot, 60)
    return f"{m}'{s:02d}\"/km"


def _catmull_rom_1d(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (2 * p1 + (-p0 + p2) * t +
                  (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                  (-p0 + 3 * p1 - 3 * p2 + p3) * t3)


def fit_closed_curve(loc, samples_per_segment=8):
    n = len(loc)
    if n < 3 or samples_per_segment < 1:
        return [p.copy() for p in loc]
    out = []
    for i in range(n):
        p0 = loc[(i - 1) % n]
        p1 = loc[i]
        p2 = loc[(i + 1) % n]
        p3 = loc[(i + 2) % n]
        for k in range(samples_per_segment):
            t = k / samples_per_segment
            out.append({
                "lat": _catmull_rom_1d(p0["lat"], p1["lat"], p2["lat"], p3["lat"], t),
                "lng": _catmull_rom_1d(p0["lng"], p1["lng"], p2["lng"], p3["lng"], t),
            })
    return out


def resample_constant_speed(loc, v, dt):
    n = len(loc)
    if n == 0:
        return []
    if n == 1:
        return [loc[0].copy()]
    step = v * dt
    if step <= 0:
        raise ValueError(f"非法 v/dt: v={v} dt={dt}")
    seg_len = [geodistance(loc[i], loc[(i + 1) % n]) for i in range(n)]
    total = sum(seg_len)
    if total <= 0:
        return [loc[0].copy()]
    count = max(1, int(round(total / step)))
    out = []
    seg_idx = 0
    seg_start = 0.0
    for k in range(count):
        target = k * total / count
        while (seg_idx < n - 1 and
               target >= seg_start + seg_len[seg_idx] and
               seg_len[seg_idx] > 0):
            seg_start += seg_len[seg_idx]
            seg_idx += 1
        a = loc[seg_idx]
        b = loc[(seg_idx + 1) % n]
        L = seg_len[seg_idx]
        f = 0.0 if L <= 0 else (target - seg_start) / L
        f = min(1.0, max(0.0, f))
        out.append({
            "lat": a["lat"] + (b["lat"] - a["lat"]) * f,
            "lng": a["lng"] + (b["lng"] - a["lng"]) * f,
        })
    return out


def _pace_components(rng, total_m):
    comps = []
    for _ in range(3):
        wavelength = rng.choice([120, 160, 200, 250, 300])
        cycles = max(2, int(round(total_m / wavelength)))
        comps.append((cycles, rng.uniform(0, 2 * math.pi), rng.uniform(0.4, 1.0)))
    wsum = sum(w for _, _, w in comps)
    return [(c, ph, w / wsum) for c, ph, w in comps]


def pace_factor_at(s, total, comps, amount=0.10):
    if total <= 0 or amount <= 0:
        return 1.0
    u = sum(w * math.sin(2 * math.pi * c * s / total + ph) for c, ph, w in comps)
    return 1.0 + u * amount


def resample_variable_speed(loc, base_v, dt, var_s=20.0, seed=None):
    n = len(loc)
    if n == 0:
        return []
    if n == 1:
        return [loc[0].copy()]
    if dt <= 0 or base_v <= 0:
        raise ValueError(f"非法 base_v/dt: {base_v}/{dt}")
    seg_len = [geodistance(loc[i], loc[(i + 1) % n]) for i in range(n)]
    total = sum(seg_len)
    if total <= 0:
        return [loc[0].copy()]
    if not var_s or var_s <= 0:
        return resample_constant_speed(loc, base_v, dt)

    base_pace = 1000.0 / base_v
    amount = min(0.30, float(var_s) / base_pace)
    rng = random.Random(seed if seed is not None else time.time_ns())
    comps = _pace_components(rng, total)

    cum = [0.0]
    for L in seg_len:
        cum.append(cum[-1] + L)

    def point_at(s):
        s = s % total
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if cum[mid + 1] < s:
                lo = mid + 1
            else:
                hi = mid
        i = min(lo, n - 1)
        L = seg_len[i]
        f = 0.0 if L <= 0 else (s - cum[i]) / L
        f = min(1.0, max(0.0, f))
        a, b = loc[i], loc[(i + 1) % n]
        return {
            "lat": a["lat"] + (b["lat"] - a["lat"]) * f,
            "lng": a["lng"] + (b["lng"] - a["lng"]) * f,
        }

    out = []
    s = 0.0
    max_steps = int(total / base_v / dt * 3) + 10
    while s < total and len(out) < max_steps:
        out.append(point_at(s))
        f = min(1.35, max(0.65, pace_factor_at(s, total, comps, amount)))
        s += base_v * f * dt
    return out


def _meters_per_deg(lat):
    return 111320.0, 111320.0 * math.cos(math.radians(lat))


def add_wander(loc, amp_m=1.0, seed=None, step_m=0.25, step_hz=1.8, dt=0.01):
    n = len(loc)
    if n == 0 or (amp_m <= 0 and step_m <= 0):
        return [p.copy() for p in loc]
    rng = random.Random(seed if seed is not None else time.time_ns())

    cum = [0.0]
    for i in range(1, n):
        cum.append(cum[-1] + geodistance(loc[i - 1], loc[i]))
    total = cum[-1] + geodistance(loc[-1], loc[0])
    if total <= 0:
        return [p.copy() for p in loc]

    comps = []
    for _ in range(3):
        comps.append((rng.choice([2, 3, 4, 5, 7, 9]),
                      rng.uniform(0, 2 * math.pi), rng.uniform(0.4, 1.0)))
    wsum = sum(w for _, _, w in comps)

    out = []
    for idx, p in enumerate(loc):
        wiggle = sum(w * math.sin(2 * math.pi * c * cum[idx] / total + ph)
                     for c, ph, w in comps) / wsum
        stride = 0.0
        if step_m > 0 and step_hz > 0:
            t = idx * dt
            stride = (math.sin(2 * math.pi * step_hz * t) * 0.6 +
                      math.sin(2 * math.pi * step_hz * 2 * t + 1.3) * 0.4)

        prev = loc[(idx - 1) % n]
        nxt = loc[(idx + 1) % n]
        mlat, mlng = _meters_per_deg(p["lat"])
        dx = (nxt["lng"] - prev["lng"]) * mlng
        dy = (nxt["lat"] - prev["lat"]) * mlat
        norm = math.hypot(dx, dy)
        if norm <= 1e-9:
            out.append(p.copy())
            continue
        nx, ny = -dy / norm, dx / norm
        tx, ty = dx / norm, dy / norm
        off_n = wiggle * amp_m + stride * step_m * 0.5
        off_t = stride * step_m * 0.5
        q = p.copy()
        q["lat"] += (ny * off_n + ty * off_t) / mlat
        q["lng"] += (nx * off_n + tx * off_t) / mlng
        out.append(q)
    return out


def build_lap(loc, v, dt=0.01, fit_curve=None, fit_samples=None,
              wander_m=None, step_m=None, step_hz=None, seed=None, pace_var_s=None):
    if fit_curve is None:
        fit_curve = _cfg("fit_curve", True)
    if fit_samples is None:
        fit_samples = int(_cfg("fit_samples", 8))
    if wander_m is None:
        wander_m = float(_cfg("wander_m", 1.0))
    if step_m is None:
        step_m = float(_cfg("wander_step_m", 0.25))
    if step_hz is None:
        step_hz = float(_cfg("wander_step_hz", 1.8))
    if pace_var_s is None:
        pace_var_s = float(_cfg("pace_var_s", 10.0))
    pts = [p.copy() for p in loc]
    if fit_curve:
        pts = fit_closed_curve(pts, samples_per_segment=max(1, fit_samples))
    pts = resample_variable_speed(pts, v, dt, var_s=pace_var_s, seed=seed)
    return add_wander(pts, amp_m=wander_m, seed=seed, step_m=step_m, step_hz=step_hz, dt=dt)


def fmt_pace(sec_per_km):
    if not sec_per_km or sec_per_km <= 0 or sec_per_km == float("inf"):
        return "--'--\"/km"
    tot = int(round(sec_per_km))
    m, s = divmod(tot, 60)
    return f"{m}'{s:02d}\"/km"


def fmt_dur(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}'{s:02d}\"" if h else f"{m}'{s:02d}\""


def fmt_dist(m):
    return f"{m / 1000:.2f}km" if m >= 1000 else f"{m:.0f}m"


def loop_length(loc):
    n = len(loc)
    if n < 2:
        return 0.0
    return sum(geodistance(loc[i], loc[(i + 1) % n]) for i in range(n))


def print_banner(loc, v):
    lap_m = loop_length(loc)
    print("=" * 46)
    print(f"  路线: {_cfg('routeConfig', '?')}  ({len(loc)}点, 环长约{lap_m:.0f}m)")
    print(f"  目标: {v:.2f} m/s ({fmt_pace(1000.0 / v)})  每圈约{fmt_dur(lap_m / v)}")
    print("  提示: 无限循环, Ctrl+C 退出 (勿直接关窗口)")
    print("=" * 46)


def run1(dvt, loc, v, dt=0.01, lap_no=1, totals=None):
    v = resolve_speed()
    dt = float(_cfg("dt", dt))
    lap = build_lap(loc, v, dt=dt, seed=random.randint(0, 2**31 - 1))
    n = len(lap)
    tick = max(1, int(5 / dt))
    win = max(1, int(5 / dt))
    hist = []
    try:
        next_t = time.perf_counter()
        for idx, p in enumerate(lap):
            location.set_location(dvt, **bd09Towgs84(p))
            hist.append(p)
            if len(hist) > win + 1:
                hist.pop(0)
            if idx % tick == 0 or idx == n - 1:
                done = sum(geodistance(hist[k], hist[k + 1]) for k in range(len(hist) - 1))
                t = (len(hist) - 1) * dt
                cur = fmt_pace(t / done * 1000 if done > 0 else 0)
                line = (f"\r第{lap_no}圈 {idx + 1}/{n}  "
                        f"本圈{fmt_dist(v * dt * idx)} {fmt_dur(idx * dt)}  当前{cur}")
                if totals is not None:
                    line += (f"  累计{fmt_dist(totals['dist'] + v * dt * idx)} "
                             f"{fmt_dur(totals['time'] + idx * dt)}")
                print(line + " " * 6, end="", flush=True)
            next_t += dt
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()
    finally:
        print()
    lap_dist = sum(geodistance(lap[i], lap[(i + 1) % n]) for i in range(n))
    return lap_dist, n * dt


def run(dvt, loc, v, lap_jitter_s=None):
    random.seed()
    if lap_jitter_s is None:
        lap_jitter_s = float(_cfg("lap_jitter_s", 15))
    v = resolve_speed()
    print_banner(loc, v)
    totals = {"dist": 0.0, "time": 0.0, "laps": 0}
    wall_start = time.time()
    while True:
        totals["laps"] += 1
        v_lap = 1000 / (1000 / v - (2 * random.random() - 1) * lap_jitter_s)
        lap_dist, lap_time = run1(dvt, loc, v_lap, lap_no=totals["laps"], totals=totals)
        totals["dist"] += lap_dist
        totals["time"] += lap_time
        avg = fmt_pace(lap_time / lap_dist * 1000 if lap_dist > 0 else 0)
        print(f"✓ 第{totals['laps']}圈: {fmt_dist(lap_dist)} {fmt_dur(lap_time)} "
              f"均速{avg} | 累计{fmt_dist(totals['dist'])} "
              f"{fmt_dur(totals['time'])} (实际{fmt_dur(time.time() - wall_start)})")
