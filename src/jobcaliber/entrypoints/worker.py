"""Worker process entry point: `jobcaliber-worker` (systemd keeps it alive)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jobcaliber.application.worker import Worker
from jobcaliber.bootstrap import build_context

DEFAULT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobcaliber-worker", description="schedule and run searches")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--poll", type=float, default=30.0, help="seconds between checks")
    parser.add_argument("--once", action="store_true",
                        help="execute a single tick and exit (queue check, post-deploy verification)")
    args = parser.parse_args(argv)

    worker = Worker(build_context(Path(args.root)), poll_s=args.poll)
    if args.once:
        outcome = worker.tick()
        if outcome is None:
            print("nothing due")
            return 0
        print(f"run {outcome.run_id}: {'failed: ' + str(outcome.error) if outcome.failed else 'ok'}")
        return 1 if outcome.failed else 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
