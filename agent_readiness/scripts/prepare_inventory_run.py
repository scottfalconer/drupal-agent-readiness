#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_readiness.inventory_run_packet import (
    DEFAULT_COPY_ROOT,
    DEFAULT_SUBSTRATE,
    build_inventory_packet,
    packet_to_jsonable,
    prepare_inventory_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a disposable independent inventory run packet")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--variant", choices=["stock", "enhanced"], default="stock")
    parser.add_argument("--substrate", type=Path, default=DEFAULT_SUBSTRATE)
    parser.add_argument("--copy-root", type=Path, default=DEFAULT_COPY_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    builder = build_inventory_packet if args.dry_run else prepare_inventory_packet
    packet = builder(
        run_id=args.run_id,
        copy_root=args.copy_root,
        variant=args.variant,
        substrate=args.substrate,
    )
    print(json.dumps(packet_to_jsonable(packet), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
