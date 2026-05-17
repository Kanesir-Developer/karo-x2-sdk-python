import argparse
import asyncio
import sys
from pathlib import Path

from karo_x2_sdk import (
    CertCredentials,
    ConnectionState,
    ConnectOptions,
    ErrorCode,
    Robot,
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
        client_id="estop-cmdvel-e2e-py/2.0",
    )
    async with Robot(opts) as robot:
        if robot.state != ConnectionState.READY:
            print("not ready", file=sys.stderr)
            return 2
        info = robot.info
        assert info is not None
        print(f"connected: sn={info.sn} "
              f"caps[chassis={info.granted_capabilities.chassis_control} "
              f"telemetry={info.granted_capabilities.telemetry_read}]")

        print("\n[1] EmergencyStop(engage=True) ...", end="", flush=True)
        r1 = await robot.emergency_stop(True, "e2e test trigger")
        print(f" ok={r1.ok} code={r1.code} msg='{r1.message}'")

        await asyncio.sleep(0.3)

        print("\n[2] CmdVel(0.1, 0, 0) during estop ...", end="", flush=True)
        r2 = await robot.cmd_vel(0.1, 0.0, 0.0)
        print(f" accepted={r2.accepted} code={r2.code} "
              f"msg='{r2.message}' rtt={r2.rtt_ms}ms")
        step2_ok = (not r2.accepted) and (
            r2.code == ErrorCode.CONTROL_E_STOP_ACTIVE or r2.code != ErrorCode.OK)
        print(f"    => {'PASS' if step2_ok else 'FAIL'}")

        await asyncio.sleep(0.3)

        print("\n[3] EmergencyStop(engage=False) ...", end="", flush=True)
        r3 = await robot.emergency_stop(False, "e2e test release")
        print(f" ok={r3.ok} code={r3.code}")

        await asyncio.sleep(0.5)

        print("\n[4] CmdVel(0, 0, 0) after release ...", end="", flush=True)
        r4 = await robot.cmd_vel(0.0, 0.0, 0.0)
        print(f" accepted={r4.accepted} code={r4.code} rtt={r4.rtt_ms}ms")
        step4_ok = r4.accepted and r4.code == ErrorCode.OK
        print(f"    => {'PASS' if step4_ok else 'FAIL'}")

        print("\n=== summary ===")
        print(f"  step 1 estop engage:   {'OK' if r1.ok else 'FAIL'}")
        print(f"  step 2 cmd_vel reject: {'OK' if step2_ok else 'FAIL'}")
        print(f"  step 3 estop release:  {'OK' if r3.ok else 'FAIL'}")
        print(f"  step 4 cmd_vel accept: {'OK' if step4_ok else 'FAIL'}")
        return 0 if (r1.ok and step2_ok and r3.ok and step4_ok) else 2

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("cert_dir", type=Path)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.host, args.cert_dir)))

