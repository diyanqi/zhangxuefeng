# AGENTS.md

给 coding agent 看的项目约定。用户手册见 README.md。

## 项目

张雪峰：iOS 17+ 真机跑步模拟 / 定点定位。`main.py` 是执行层，`webui.py` 是常驻的
本地 WebUI（只绑定 `127.0.0.1`），同一时间只允许一个 `main.py` 子进程。

## 目录

- `main.py`：命令行入口。流程固定为 预检 → 读路线 → 建隧道 → 连 RSD/DVT → 跑/定点。
  所有失败走 `die(msg, hint)`（中文原因 + 解决办法），不静默卡死。
- `run.py`：轨迹流水线 拟合 → 变速重采样 → 跑步摆动；速度唯一来源是 `pace`，
  为空或非法直接抛 `ValueError`，不做任何回退；
  路线文件是 BD-09，发给手机前必须转 WGS-84（`bd09Towgs84`）。
- `webui.py`：只用标准库 + `pyyaml`，**不要新增 pip 依赖**。前端模板在
  `templates/index.html`，JS 按 `static/js/api.js`（请求工具 + `CFG_KEYS`）、
  `app.js`（状态动作）、`map.js`、`ui.js`（渲染）分工。
- `driver/`：`connect`（配对/隧道，错误带 `hint`）、`location`（定位设置/清除）、
  `quic_compat`（qh3 兼容补丁，`ensure_patched` 必须在隧道子进程里调）。
- `init/`：预检（root/设备/配对/iOS版本/开发者模式）、路线读取、隧道子进程管理。
- `util/ports.py`：端口占用权威判断。同类服务指纹是 `SERVICE_TAG = "ZXF-WebUI"`
 （HTTP Server 头或 `/api/run/state` 含 running/pid 字段）。只杀同类，拒绝碰其他服务。
- `config.yaml` / `requirements.txt`：参数与依赖。`qh3==1.9.4` 钉死（与
  `pymobiledevice3==2.46.1` 冲突），不要升级；Mac 装 `sslpsk-pmd3` 要先 export
  OpenSSL 路径（见 README）。

## 运行

- `./start-ui.sh [--port N] [--setup] [--kill] [--force] [--no-browser]`：建 venv → 装依赖 →
  sudo 提权验证 → 端口预检 → **前台**跑 WebUI（Ctrl+C 直达服务做清理）。
  `--setup` 只装依赖不启动；WebUI 健康检查里依赖失败也有「一键安装依赖」按钮（`POST /api/deps/install`）。
  不要改回 `sudo … &` 后台模式：后台任务默认忽略 SIGINT，会留下退不出的 root 孤儿。
- 管理员/root 是硬性要求（建 tun 隧道），必须用 `.venv` 里的 python。
- 停止语义：`SIGINT` = 优雅退出（清虚拟定位），`terminate`/`kill -9`不清定位。
  `RunManager.stop/shutdown` 永远是 SIGINT → terminate → kill 逐级升级。

## 改代码时的规矩

1. `webui.py` 不引入新依赖；API 返回保持 `{ok, msg}` / `{error}` 形状，前端直接 toast。
2. 用户可见文案用中文，报错必须带解决办法（沿用 `hint` 惯例）。
3. 端口冲突不要自动 kill，先 `util.ports.check_port` 判同类，非同类只提示换端口。
4. 前端 JS 无构建步骤，改完用 `node --check`；shell 改完用 `bash -n`；
   Python 改完用 `py_compile` + 按需 `import` 烟测。
5. 注释保持精简：解释"为什么"可以留，复述代码、 war story、历史包袱不写进代码，
   知识放 README / 本文件。
