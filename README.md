# Karo X2 Python SDK

第三方开发者用的 Karo X2 机器人 Python SDK. 与 C++ SDK 共享同一 wire protocol 和
行为契约 (见 `docs/spec/connection_lifecycle.md`).

## 安装

```bash
pip install karo-x2-sdk
```

国内网络若 PyPI 慢, 可走镜像源:

```bash
pip install -i https://mirrors.aliyun.com/pypi/simple/ karo-x2-sdk
# 或清华: pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ karo-x2-sdk
```

> PyPI 分发名 `karo-x2-sdk`, import 路径 `karo_x2_sdk` (下划线) — dist 名和 import 名 v3.2.7 起完全对齐, 多机型 SDK 共存不冲突.

依赖: Python ≥ 3.10, `websockets`, `protobuf`, `cryptography`.

## 获取 SDK 凭据

联系机器人服务商索取一份"开发者凭据 zip", 内含 X.509 证书 (`cert.pem` /
`key.pem` / `ca.pem`) + 该证书绑定的能力授权 (telemetry_read + chassis_control 等).
**客户没有自助下发权限**, 凭据由服务商按客户身份 + 用途集中签发.

## 机器人 IP

`ConnectOptions(host=...)` 默认 `192.168.10.10` (有线 USB-RNDIS / 直连 LAN 出厂
固定地址), 大多数客户直接用默认值就行.

**无线局域网场景** (机器人通过 WiFi 接入家用/办公网络): IP 由路由器 DHCP 分配,
从机器人显示屏 / 路由器后台拿到实际 IP 后传:

```python
opts = ConnectOptions(host="10.0.5.27", ...)  # 不含端口 (固定 4434)
```

## 快速开始

```python
import asyncio
from karo_x2_sdk import Robot, ConnectOptions, CertCredentials, ConnectionState

async def main():
    opts = ConnectOptions(
        host="192.168.10.10",
        cert=CertCredentials(
            cert_pem=open("creds/cert.pem").read(),
            key_pem=open("creds/key.pem").read(),
            ca_pem=open("creds/ca.pem").read(),
            insecure_skip_verify=True,  # LAN 直连测试
        ),
        client_id="my-app/1.0",
    )
    # 状态回调必须在 connect() 前注册才能捕获 Idle → Connecting (spec §2.4)
    robot = Robot(opts)
    robot.on_connection_state(
        lambda old, new, info: print(f"[state] {old} -> {new}")
    )
    await robot.connect()                # 异步立即返回
    if not await robot.wait_until_ready(timeout=30):
        print("failed to reach Ready")
        await robot.close()
        return

    # 订阅 robot.state (5 Hz)
    async def on_data(s):
        print(f"battery={s.battery_percent}% estop={s.is_estop}")
    sub = await robot.subscribe_robot_status(5.0, on_data, on_status=None)

    # 发 cmd_vel
    result = await robot.cmd_vel(0.2, 0.0, 0.0)
    print(f"cmd_vel: accepted={result.accepted} rtt={result.rtt_ms}ms")

    await asyncio.sleep(5)
    await sub.unsubscribe()
    await robot.close()

asyncio.run(main())
```

## API 概览

行为契约与 C++ SDK 一致 (跨语言, spec §11):

- **两阶段连接**: `Robot(opts)` 构造 (state=Idle) + `await robot.connect()` 异步握手
- **状态机** (`ConnectionState`): Idle / Connecting / Ready / TransientFailure /
  Reconnecting / Shutdown / Fatal
- **自动重连**: 指数退避 + jitter (默认 floor 0.05 防 thundering herd)
- **心跳**: 10s 间隔 + 3 次未响应 = 19s 死链检测
- **订阅**: `Subscription` handle, async context manager, 析构 fire-and-forget unsubscribe
- **EVENT vs TELEMETRY**: 服务端按 topic 投递语义区分, SDK 自动做 gap 检测 (仅 EVENT)
- **错码三类**: Transient (重连) / Application (单次失败) / Fatal (终态)
- **EmergencyStop 重放**: 重连后自动重发 engage=True 意图; engage=False 不重放
- **CmdVel 永不重试**: 断连状态立即返 Disconnected, 不入队

## Examples

`examples/` 目录:

- `teleop.py` — 10 Hz cmd_vel 演示 + 状态回调
- `emergency_stop.py` — 触发软急停 + 释放
- `subscribe_status.py` — 订阅 robot.state + 流状态回调
- `estop_cmdvel_e2e.py` — 4 步端到端 probe (engage/cmdvel/release/cmdvel)

运行:

```bash
python examples/teleop.py 192.168.10.10 ./creds
```

## 开发

```bash
# 生成 _pb2.py (本仓 vendor 同步 proto/ 后)
./scripts/gen_proto.sh

# 跑单元测试
pip install -e .[dev]
pytest tests/
```

## 故障排查

**连不上 (state 卡 Connecting / 进 TransientFailure)**

1. `ping <host>` 通不通: 不通先查物理连接 (有线网线 / WiFi SSID); 默认
   `192.168.10.10` 是有线直连地址, 无线请用路由器分配的实际 IP.
2. `nc -zv <host> 4434` 端口 4434 通不通: 不通可能机器人 SDK 服务未启动或被
   防火墙拦, 联系厂商.
3. 凭据是否过期: `openssl x509 -noout -dates -in creds/cert.pem` 查证书有效期;
   过期联系服务商换发.
4. ca.pem / cert.pem / key.pem 必须是同一份凭据 zip 解出来的, 跨机器人混用会
   mTLS handshake fail.

**Ready 后业务命令被拒**

- `CmdVelResult.code == CapabilityDenied`: 凭据没授 `chassis_control`, 联系
  服务商换发带遥控能力的凭据.
- `code == ControlRejectedEstop`: 机器人当前急停态 (硬急停按下 / 充电中等),
  这是 server 主动拒绝, 不是 SDK 故障. 先 `await robot.emergency_stop(False)`
  解除或物理释放硬急停后重试.

**`pip install karo-x2-sdk` 失败**

- 国内网络 PyPI 直连慢 → 用阿里云 / 清华镜像 (见上面"安装"节).
- `ModuleNotFoundError: No module named 'karo_x2_sdk'` (v3.2.6 升级到 v3.2.7+
  后客户代码没改): 把 `from karo_sdk import X` 改 `from karo_x2_sdk import X`.

详细架构见 C++ SDK 实现 (`cpp/README.md` + `docs/spec/connection_lifecycle.md`).
