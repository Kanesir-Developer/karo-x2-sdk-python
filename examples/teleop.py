import argparse
import asyncio
import signal
import sys
from pathlib import Path

from karo_x2_sdk import (
    CertCredentials,
    ConnectionState,
    ConnectOptions,
    ErrorCode,
    LogLevel,
    Robot,
    StateChangeInfo,
)

async def main(host: str, cert_dir: Path) -> int:
    opts = ConnectOptions(
        host=host,
        cert=CertCredentials(
            cert_pem=(cert_dir / "cert.pem").read_text(),
            key_pem=(cert_dir / "key.pem").read_text(),
            ca_pem=(cert_dir / "ca.pem").read_text(),
            insecure_skip_verify=True,
        ),
        client_id="teleop-example-py/2.0",
    )
    robot = Robot(opts)

    def on_state(old: ConnectionState, new: ConnectionState, info: StateChangeInfo) -> None:
        msg = f"[state] {old} -> {new}"
        if info.reason:
            msg += f" ({info.reason})"
        if info.last_error_code != ErrorCode.OK:
            msg += f" err={info.last_error_code}"
        print(msg, file=sys.stderr)

    def on_log(level: LogLevel, msg: str) -> None:
        if level.value >= LogLevel.WARN.value:
            print(f"[sdk-{level}] {msg}", file=sys.stderr)

    robot.on_connection_state(on_state)
    robot.on_log(on_log)

    await robot.connect()
    if not await robot.wait_until_ready(timeout=30):
        print("failed to reach Ready", file=sys.stderr)
        return 2

    info = robot.info
    assert info is not None
    print(f"connected: sn={info.sn} model={info.model} proto={info.protocol_version}")
    if not info.granted_capabilities.chassis_control:
        print("ERROR: application lacks chassis_control capability", file=sys.stderr)
        return 2

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, stop.set)
    loop.add_signal_handler(signal.SIGTERM, stop.set)

    total = accepted = disconnected = 0
    interval = 0.1
    while not stop.is_set():
        r = await robot.cmd_vel(0.2, 0.0, 0.0)
        total += 1
        if r.accepted:
            accepted += 1
        elif r.code == ErrorCode.DISCONNECTED:

            disconnected += 1
        else:
            print(f"cmd_vel rejected: {r.message} (code={r.code})", file=sys.stderr)
        if total % 10 == 0:
            print(f"tick {total} accepted={accepted} disc={disconnected} rtt~{r.rtt_ms}ms")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    await robot.cmd_vel(0.0, 0.0, 0.0)
    print(f"shutdown: {accepted}/{total} accepted, {disconnected} disconnected")
    await robot.close()
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("cert_dir", type=Path)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.host, args.cert_dir)))

