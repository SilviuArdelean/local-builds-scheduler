# Dashboard Demo

This demo exercises the Local Builds Scheduler dashboard without running a real
Chromium build. It simulates four sequential jobs, sync/build phases, Siso-style
progress output, terminal resizing, and live compiler log streaming.

From the repository root, run:

```powershell
lbs run demos\dashboard_demo\dashboard-demo.yaml --fresh
```

The demo creates runtime logs and scheduler state under `logs/`. That directory
is ignored by Git and can be safely removed between runs.
