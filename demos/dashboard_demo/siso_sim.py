"""Simulates Chromium Siso/Ninja build output to preview the LBS dashboard."""

import sys
import time

total = int(sys.argv[1]) if len(sys.argv) > 1 else 63295
steps = int(sys.argv[2]) if len(sys.argv) > 2 else 300
delay = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05

for i in range(1, steps + 1):
    done = round(total * i / steps)
    elapsed = i * delay
    print(
        f"[{done}/{total}] {int(elapsed // 60)}m{elapsed % 60:05.2f}s "
        f"F CXX obj/content/browser/browser/file_{i}.obj",
        flush=True,
    )
    time.sleep(delay)
