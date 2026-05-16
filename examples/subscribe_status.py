import argparse
import asyncio
import signal
import sys
from pathlib import Path

from karo_x2_sdk import (
    CertCredentials,
    ConnectOptions,
    DeliverySemantics,
    ErrorCode,
    Robot,
    RobotStatus,
    StreamStatus,
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
        client_id="subscribe-status-example-py/2.0",
    )
    robot = Robot(opts)
    await robot.connect()
    if not await robot.wait_until_ready(timeout=30):
        print("not ready", file=sys.stderr)
        return 2

    info = robot.info
    assert info is not None
    print(f"connected: sn={info.sn} model={info.model}")
    print("available topics:")
    for t in info.available_topics:
        sem = "EVENT" if t.delivery_semantics == DeliverySemantics.EVENT else "TELEMETRY"
        print(f"  - {t.name} (default={t.default_hz}Hz max={t.max_hz}Hz, {sem}): {t.description}")
    if not info.granted_capabilities.telemetry_read:
        print("ERROR: application lacks telemetry_read capability", file=sys.stderr)
        return 2

    def on_data(s: RobotStatus) -> None:
        print(f"[{s.timestamp_ms}] battery={s.battery_percent}% "
              f"state={s.service_state.name} "
              f"estop={'Y' if s.is_estop else 'N'} "
              f"(hw={'Y' if s.is_hw_estop else 'N'} sw={'Y' if s.is_sw_estop else 'N'}) "
              f"errors={len(s.error_codes)}")

    def on_status(st: StreamStatus) -> None:
        msg = f"[stream] {st.kind}"
        if st.gap_count is not None:
            msg += f" gap={st.gap_count}"
        if st.error_code != ErrorCode.OK:
            msg += f" err={st.error_code}"
        if st.reason:
            msg += f" ({st.reason})"
        print(msg, file=sys.stderr)

    sub = await robot.subscribe_robot_status(5.0, on_data, on_status)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, stop.set)
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    await stop.wait()

    err = await sub.unsubscribe()
    if err != ErrorCode.OK:
        print(f"unsubscribe: {err}", file=sys.stderr)
    await robot.close()
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("cert_dir", type=Path)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.host, args.cert_dir)))

