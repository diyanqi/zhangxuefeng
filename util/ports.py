import json
import os
import signal
import socket
import subprocess
import urllib.request

SERVICE_TAG = "ZXF-WebUI"


def is_port_open(port, host="127.0.0.1", timeout=1.0):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _alive(pid):
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5).stdout
            return ('"%d"' % pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _listener_pids_netstat(port):
    import re
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        m = re.search(r"[\d\.\[\]\:a-fA-F]+:(\d+)\s+.*LISTENING\s+(\d+)\s*$",
                      line, re.IGNORECASE)
        if m and int(m.group(1)) == int(port):
            pid = int(m.group(2))
            if pid not in pids:
                pids.append(pid)
    return pids


def listener_pids(port):
    if os.name == "nt":
        return _listener_pids_netstat(port)
    pids = []
    for args in (["lsof", "-iTCP:%s" % port, "-sTCP:LISTEN", "-t"],
                 ["lsof", "-i:%s" % port, "-sTCP:LISTEN", "-t"],
                 ["lsof", "-i:%s" % port, "-t"]):
        try:
            out = subprocess.run(args, capture_output=True, text=True,
                                 timeout=5).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit() and int(line) not in pids:
                    pids.append(int(line))
            if pids:
                return pids
        except Exception:
            continue
    try:
        out = subprocess.run(["ss", "-ltnp"], capture_output=True,
                             text=True, timeout=5).stdout
        import re
        for line in out.splitlines():
            if ":%s" % port not in line:
                continue
            for m in re.finditer(r"pid=(\d+)", line):
                pid = int(m.group(1))
                if pid not in pids:
                    pids.append(pid)
        if pids:
            return pids
    except Exception:
        pass
    return pids


def proc_cmd(pid):
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "PID eq %s" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            parts = [p.strip().strip('"') for p in out.split(",")]
            if len(parts) >= 2 and parts[1] == str(pid):
                return parts[0]
            return out
        except Exception:
            return ""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=5).stdout
        return out.strip()
    except Exception:
        return ""


def _get_json(url, timeout=3):
    req = urllib.request.Request(url, headers={"Connection": "close"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        headers = {k.lower(): v for k, v in (r.headers.items() if hasattr(r, "headers") else [])}
        try:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception:
            data = {}
        return data, headers


def probe_same_service(port, host="127.0.0.1", timeout=3):
    url = f"http://{host}:{int(port)}/api/run/state"
    try:
        data, headers = _get_json(url, timeout=timeout)
    except Exception as e:
        import urllib.error as _ue
        if isinstance(e, _ue.HTTPError):
            return {"same": False,
                    "detail": f"端口有其他 HTTP 服务占用 (HTTP {e.code}, 不是本项目 WebUI)",
                    "state": None}
        return {"same": False, "detail": f"端口无本项目服务响应 ({type(e).__name__})",
                "state": None}
    server = headers.get("server", "")
    if isinstance(data, dict) and ("running" in data or "pid" in data or "log_seq" in data):
        running = "运行中" if data.get("running") else "未运行"
        pid = data.get("pid")
        return {"same": True,
                "detail": f"同类服务 ({SERVICE_TAG}, {running}"
                          + (f", pid {pid}" if pid else "") + ")",
                "state": data}
    if SERVICE_TAG.lower() in server.lower():
        return {"same": True, "detail": f"同类服务 (Server: {server})", "state": data if isinstance(data, dict) else None}
    try:
        data2, _ = _get_json(f"http://{host}:{int(port)}/api/server/info", timeout=timeout)
        if isinstance(data2, dict) and data2.get("service") == SERVICE_TAG:
            return {"same": True, "detail": "同类服务 (server/info 确认)", "state": data if isinstance(data, dict) else None}
    except Exception:
        pass
    return {"same": False, "detail": "端口有其他服务占用 (不是本项目 WebUI)", "state": None}


def check_port(port, host="127.0.0.1"):
    port = int(port)
    open_ = is_port_open(port, host)
    if not open_:
        return {"port": port, "open": False, "pids": [], "same": False,
                "detail": f"端口 {port} 空闲", "cmds": {}}
    pids = listener_pids(port)
    probe = probe_same_service(port, host)
    cmds = {str(p): proc_cmd(p) for p in pids}
    return {"port": port, "open": True, "pids": pids, "same": probe["same"],
            "detail": probe["detail"], "cmds": cmds, "state": probe.get("state")}


def kill_pids(pids, graceful_timeout=8):
    if os.name == "nt":
        return _kill_pids_windows(pids, graceful_timeout)
    _sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
    res = {}
    for pid in pids:
        pid = int(pid)
        try:
            if pid <= 1 or pid == os.getpid():
                res[pid] = "跳过 (系统/自身进程)"
                continue
            try:
                os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                res[pid] = "进程已不存在"
                continue
            except PermissionError as e:
                res[pid] = f"无权限 (需 sudo kill {pid}): {e}"
                continue
            import time
            deadline = time.time() + graceful_timeout
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.3)
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(1.0)
                except ProcessLookupError:
                    pass
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    try:
                        os.kill(pid, _sigkill)
                    except Exception as e:
                        res[pid] = f"kill 失败: {e}"
                        continue
            res[pid] = "已结束"
        except Exception as e:
            res[pid] = f"失败 ({type(e).__name__}: {e})"
    return {str(k): v for k, v in res.items()}


def _kill_pids_windows(pids, graceful_timeout=8):
    import time
    res = {}
    for pid in pids:
        pid = int(pid)
        try:
            if pid <= 1 or pid == os.getpid():
                res[pid] = "跳过 (系统/自身进程)"
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                res[pid] = "进程已不存在"
                continue
            except PermissionError as e:
                res[pid] = f"无权限 (请以管理员运行): {e}"
                continue
            deadline = time.time() + graceful_timeout
            while time.time() < deadline:
                if not _alive(pid):
                    break
                time.sleep(0.3)
            else:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=10)
                time.sleep(0.5)
            res[pid] = "已结束" if not _alive(pid) else "结束失败 (请手动 taskkill /F)"
        except Exception as e:
            res[pid] = f"失败 ({type(e).__name__}: {e})"
    return {str(k): v for k, v in res.items()}


def _cli(argv):
    if len(argv) < 2 or argv[1] not in ("check", "kill"):
        print(json.dumps({"error": "用法: python -m util.ports check PORT | kill PID..."},
                         ensure_ascii=False))
        return 2
    if argv[1] == "check":
        if len(argv) < 3:
            print(json.dumps({"error": "缺少 PORT"}, ensure_ascii=False))
            return 2
        print(json.dumps(check_port(int(argv[2])), ensure_ascii=False))
        return 0
    print(json.dumps(kill_pids([int(x) for x in argv[2:]]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv))
