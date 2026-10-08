import asyncio
import logging
import multiprocessing
import time

from driver import connect

logger = logging.getLogger(__name__)

DEFAULT_TUNNEL_TIMEOUT = 90


def tunnel_proc(queue: multiprocessing.Queue):
    try:
        server_rsd = connect.get_serverrsd()
        print(f"[tunnel] RSD 就绪, 建隧道 (QUIC优先, 失败回落TCP)…", flush=True)
        asyncio.run(connect.open_tunnel(server_rsd, queue=queue))
    except Exception as e:
        hint = getattr(e, "hint", "")
        msg = str(e) or type(e).__name__
        try:
            queue.put({"ok": False, "error": msg,
                       "hint": hint, "exc": type(e).__name__})
        except Exception:
            pass
        print(f"[tunnel] 失败: {msg}" + (f" ➜ {hint}" if hint else ""), flush=True)


def tunnel(timeout=DEFAULT_TUNNEL_TIMEOUT):
    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=tunnel_proc, args=(queue,))
    process.start()
    deadline = time.time() + max(5, timeout)
    try:
        while time.time() < deadline:
            if not queue.empty():
                msg = queue.get()
                if isinstance(msg, dict) and msg.get("ok"):
                    print(f"[tunnel] 隧道就绪 ({msg.get('protocol', '?')}) "
                          f"{msg['address']}:{msg['port']}", flush=True)
                    return process, msg["address"], msg["port"]
                if isinstance(msg, dict):
                    raise connect.TunnelError(
                        f"隧道失败: {msg.get('error', '未知错误')}",
                        msg.get("hint") or "手机解锁亮屏、重插线后重试; 必须 root; 只连一台.")
                try:
                    address, port = msg
                    return process, address, port
                except Exception:
                    raise connect.TunnelError(f"隧道返回异常: {msg!r}",
                                              "重插线解锁后重试.")
            if not process.is_alive():
                raise connect.TunnelError(
                    f"隧道子进程异常退出 (exitcode={process.exitcode})",
                    "多半是没 root / 没设备 / 没信任. 用 sudo 跑, 手机解锁点信任, 只连一台.")
            time.sleep(0.2)
    except Exception:
        if process.is_alive():
            process.terminate()
        raise
    try:
        if process.is_alive():
            process.terminate()
    finally:
        pass
    raise connect.TunnelError(
        f"建隧道超时 ({timeout}s 内没就绪, 一直卡在发现设备/握手)",
        "①必须 root (sudo / ./start-ui.sh); ②线直连+解锁+已信任; ③只连一台; "
        "④重插线等 5 秒; ⑤重启手机+电脑; ⑥换线/口.")


def stop_tunnel(process):
    if process is None:
        return
    try:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
            if process.is_alive():
                process.kill()
    except Exception as e:
        logger.debug(f"stop_tunnel: {e}")
