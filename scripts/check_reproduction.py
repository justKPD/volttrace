"""CI guard: the freshly generated benchmark summary must equal the committed one (seed set 0)."""

import json
import sys
from pathlib import Path

fresh = json.loads(Path(sys.argv[1]).read_text())["summary_per_seed"]["0"]
committed = json.loads(Path("docs/results/benchmark_summary.json").read_text())["summary_per_seed"]["0"]
if fresh != committed:
    print("benchmark summary changed - regenerate docs/results with `volttrace bench --seeds 0 1 2`")
    print("fresh:    ", json.dumps(fresh, indent=1))
    print("committed:", json.dumps(committed, indent=1))
    sys.exit(1)
print("benchmark reproduced exactly (seed set 0)")
