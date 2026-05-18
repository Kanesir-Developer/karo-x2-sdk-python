import argparse
import asyncio
import sys
from pathlib import Path

from karo_x2_sdk import (
    CertCredentials,
    ConnectionState,
    ConnectOptions,
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
        client_id="estop-example-py/2.0",
    )
    async with Robot(opts) as robot:
        if robot.state != ConnectionState.READY:
            print("not ready", file=sys.stderr)
            return 2

        print("engaging soft e-stop...")
        r1 = await robot.emergency_stop(True, "demo: triggering soft estop")
        print(f"engage ok={r1.ok} code={r1.code} msg={r1.message}")
        if not r1.ok:
            return 3

        print("estop engaged, cmd_vel will be rejected for 5s...")
        await asyncio.sleep(5)

        print("releasing soft e-stop...")
        r2 = await robot.emergency_stop(False, "demo end")
        print(f"release ok={r2.ok} code={r2.code}")
        return 0 if r2.ok else 4

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("cert_dir", type=Path)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.host, args.cert_dir)))

