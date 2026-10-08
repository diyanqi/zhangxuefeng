#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

PORT="${PORT:-8123}"
NO_BROWSER="${NO_BROWSER:-}"
SKIP_INSTALL="${SKIP_INSTALL:-0}"
REINSTALL="${REINSTALL:-0}"
SETUP_ONLY="${SETUP_ONLY:-0}"
KILL_ONLY="${KILL:-0}"
FORCE_RESTART="${FORCE:-0}"

usage() {
  echo "用法: ./start-ui.sh [--port 8123] [--no-browser] [--reinstall] [--skip-install] [--setup] [--kill] [--force]"
  echo "  环境变量同样有效: PORT / NO_BROWSER=1 / SKIP_INSTALL=1 / REINSTALL=1 / SETUP_ONLY=1 / KILL=1 / FORCE=1"
  echo "  --setup: 只建 .venv 并装依赖, 不启动 (一键装依赖)"
  echo "  --kill: 检测端口占用, 若是同类服务 (上次 WebUI 没退) 则一键 kill 后退出"
  echo "  --force: 一键 kill 同类服务后继续启动 (非同类占用则拒绝, 请换端口)"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:?--port 需要值}"; shift 2 ;;
    --no-browser) NO_BROWSER=1; shift ;;
    --reinstall) REINSTALL=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --setup) SETUP_ONLY=1; shift ;;
    --kill) KILL_ONLY=1; shift ;;
    --force|-f) FORCE_RESTART=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[start-ui] 未知参数: $1"; usage; exit 2 ;;
  esac
done

URL="http://127.0.0.1:${PORT}"
VENV_PY="$ROOT/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "[start-ui] 建 .venv ..."
  python3 -m venv .venv
fi

need_install=0
if [ "$SKIP_INSTALL" = "1" ]; then
  echo "[start-ui] 跳过依赖安装 (SKIP_INSTALL=1)"
elif [ "$REINSTALL" = "1" ]; then
  need_install=1
elif ! "$VENV_PY" -c "import pymobiledevice3, yaml, geopy, coloredlogs, qh3" 2>/dev/null; then
  need_install=1
fi
if [ "$need_install" = "1" ]; then
  for _ossl in /opt/homebrew/opt/openssl@3 /usr/local/opt/openssl@3; do
    if [ -d "$_ossl" ]; then
      export LDFLAGS="-L$_ossl/lib"
      export CPPFLAGS="-I$_ossl/include"
      export PKG_CONFIG_PATH="$_ossl/lib/pkgconfig"
      break
    fi
  done
  echo "[start-ui] 装依赖 (pip install -r requirements.txt) ..."
  if ! "$ROOT/.venv/bin/pip" install -r requirements.txt; then
    echo "[start-ui] 依赖安装失败, 见上. Mac 报 openssl/ssl.h 缺失先 brew install openssl@3 (见 README 第 2 节)." >&2
    exit 1
  fi
else
  echo "[start-ui] 依赖已就绪, 跳过安装 (--reinstall 可强制重装)"
fi

if [ "$SETUP_ONLY" = "1" ]; then
  echo "[start-ui] 依赖就绪 (venv: .venv). 启动: ./start-ui.sh"
  exit 0
fi

port_in_use() {
  (command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1) \
  || (command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT ") \
  || "$VENV_PY" -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1',$PORT))==0 else 1)"
}
port_report() {
  "$VENV_PY" -c "
import json,sys
sys.path.insert(0,'$ROOT')
try:
    from util import ports
    print(json.dumps(ports.check_port($PORT)))
except Exception as e:
    print(json.dumps({'open':True,'pids':[],'same':False,'detail':'检测脚本异常: %s' % e,'cmds':{}}))
" 2>/dev/null
}
kill_same_service() {
  local rep="$1"
  local pids
  pids=$(printf '%s' "$rep" | "$VENV_PY" -c "import json,sys; d=json.load(sys.stdin); print(' '.join(map(str,d.get('pids',[]))))" 2>/dev/null)
  if [ -z "$pids" ]; then echo "[start-ui] 找不到可杀的进程 (可能已退出)."; return 0; fi
  echo "[start-ui] 一键 kill 同类服务: kill -INT $pids ..."
  kill -INT $pids 2>/dev/null || true
  for _ in $(seq 1 20); do
    alive=""
    for p in $pids; do kill -0 "$p" 2>/dev/null && alive="$alive $p"; done
    [ -z "$alive" ] && break
    sleep 0.5
  done
  for p in $pids; do kill -0 "$p" 2>/dev/null && kill "$p" 2>/dev/null || true; done
  sleep 0.5
  for p in $pids; do kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true; done
  if port_in_use; then echo "[start-ui] kill 后端口 $PORT 仍被占用, 请手动 lsof -i :$PORT 查看." >&2; return 1; fi
  echo "[start-ui] 端口 $PORT 已释放."
}
if port_in_use; then
  REP=$(port_report)
  SAME=$(printf '%s' "$REP" | "$VENV_PY" -c "import json,sys; print('yes' if json.load(sys.stdin).get('same') else 'no')" 2>/dev/null || echo "no")
  DETAIL=$(printf '%s' "$REP" | "$VENV_PY" -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail','') + (' | pid ' + ','.join(map(str,d.get('pids',[]))) if d.get('pids') else ''))" 2>/dev/null || echo "")
  PIDS=$(printf '%s' "$REP" | "$VENV_PY" -c "import json,sys; print(' '.join(map(str,json.load(sys.stdin).get('pids',[]))))" 2>/dev/null || echo "")
  if [ -n "$PIDS" ]; then
    echo "[start-ui] 端口 $PORT 已被占用 (pid $PIDS)." >&2
    for p in $PIDS; do
      cmd=$(ps -p "$p" -o command= 2>/dev/null || echo "?")
      echo "  pid $p: $cmd" >&2
    done
  else
    echo "[start-ui] 端口 $PORT 已被占用." >&2
  fi
  echo "  判断: $DETAIL" >&2
  if [ "$SAME" = "yes" ]; then
    echo "  这是上次没退出的同类服务 (本项目 WebUI), 可以一键 kill." >&2
  else
    echo "  这不是本项目 WebUI, 不要 kill (可能是别的服务)." >&2
  fi
  if [ "$KILL_ONLY" = "1" ]; then
    if [ "$SAME" != "yes" ]; then echo "[start-ui] 非同类占用, 拒绝 kill. 换端口: ./start-ui.sh --port $((PORT+1))" >&2; exit 1; fi
    kill_same_service "$REP" || exit 1
    exit 0
  fi
  if [ "$FORCE_RESTART" = "1" ]; then
    if [ "$SAME" != "yes" ]; then echo "[start-ui] 非同类占用, 拒绝 --force. 换端口: ./start-ui.sh --port $((PORT+1))" >&2; exit 1; fi
    kill_same_service "$REP" || exit 1
  else
    if [ "$SAME" = "yes" ]; then
      echo "  一键清理: ./start-ui.sh --port $PORT --kill   (只杀同类)" >&2
      echo "  或覆盖重启: ./start-ui.sh --port $PORT --force" >&2
      if [ -t 0 ]; then
        printf "  现在 kill 并继续启动? [y/N] " >&2
        read -r ans < /dev/tty || ans=""
        case "$ans" in
          y|Y|yes|YES) kill_same_service "$REP" || exit 1 ;;
          *) echo "  已取消. 换端口: ./start-ui.sh --port $((PORT+1))" >&2; exit 1 ;;
        esac
      else
        echo "  换端口: ./start-ui.sh --port $((PORT+1))" >&2
        echo "  若是上次 WebUI 没退出, 关掉它再来 (Ctrl+C, 不要直接关窗口/kill -9)." >&2
        exit 1
      fi
    else
      echo "  换端口: PORT=$((PORT+1)) ./start-ui.sh  或  ./start-ui.sh --port $((PORT+1))" >&2
      echo "  查谁占着: lsof -i :$PORT" >&2
      exit 1
    fi
  fi
else
  if [ "$KILL_ONLY" = "1" ]; then echo "[start-ui] 端口 $PORT 本来就空闲, 无需 kill."; exit 0; fi
fi

SUDO=(sudo)
if [ "$(id -u)" -eq 0 ]; then
  SUDO=()
  echo "[start-ui] 已是 root, 跳过提权."
else
  echo "[start-ui] 需要管理员密码 (开机密码, 建 tun 隧道必需, 验证一次) ..."
  tries=0
  until sudo -p "[start-ui] 管理员密码 (macOS 开机密码): " -v; do
    tries=$((tries + 1))
    if [ "$tries" -ge 3 ]; then
      echo "[start-ui] 密码验证 3 次没过, 退出. 提示: 输的是电脑开机密码, 不是 Apple ID." >&2
      exit 1
    fi
    echo "[start-ui] 密码不对或已取消, 重试 ($tries/3) ..."
  done
fi

echo "[start-ui] WebUI 启动中 -> $URL (停止: Ctrl+C, 会先清虚拟定位)"
health_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -fs -o /dev/null "$URL/api/run/state" 2>/dev/null
  else
    "$VENV_PY" -c "import sys,urllib.request;urllib.request.urlopen('$URL/api/run/state',timeout=3).read()" 2>/dev/null
  fi
}
health_and_open() {
  ok=0
  for _ in $(seq 1 30); do
    if health_ok; then ok=1; break; fi
    sleep 0.5
  done
  if [ "$ok" = "1" ]; then
    echo "[start-ui] WebUI 就绪 -> $URL"
    if [ -z "$NO_BROWSER" ]; then
      if command -v open >/dev/null 2>&1; then
        open "$URL" || true
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" || true
      fi
    fi
  else
    echo "[start-ui] 提示: 15s 内健康检查还没通过, 先看上面 WebUI 自己的日志 (端口占用/没 root/依赖缺都会打出来)." >&2
  fi
}
health_and_open &
HEALTH_PID=$!
trap 'kill "$HEALTH_PID" 2>/dev/null || true' EXIT
CODE=0
"${SUDO[@]}" "$VENV_PY" webui.py --port "$PORT" || CODE=$?
kill "$HEALTH_PID" 2>/dev/null || true
wait "$HEALTH_PID" 2>/dev/null || true
trap - EXIT
exit "$CODE"
