# Missing Dependencies Demo

This demo lets you preview how Local Builds Scheduler handles both **soft
(partially working)** and **mandatory (hard-impact)** missing dependencies
without uninstalling anything from your virtual environment.

From the repository root, run all non-interactive scenarios in sequence:

```powershell
python demos\missing_deps_demo\run_demo.py all
```

Or run any individual scenario:

| Command | What it demonstrates |
| :--- | :--- |
| `python demos\missing_deps_demo\run_demo.py psutil` | Live split-screen dashboard with `psutil` missing: CPU, RAM, and Disk I/O show `N/A` (Disk Free still works) and `[WARNING]` stays visible below the dashboard and in the session log. |
| `python demos\missing_deps_demo\run_demo.py psutil-validate` | `lbs validate` emits `[WARNING]` on `stderr` while still printing `Configuration is valid.` on `stdout` (exit code `0`). |
| `python demos\missing_deps_demo\run_demo.py psutil-dry-run` | `lbs run --dry-run` emits `[WARNING]` on `stderr` while keeping the dry-run plan intact on `stdout`. |
| `python demos\missing_deps_demo\run_demo.py psutil-disabled` | With `settings.system_resources.enabled: false`, the `psutil` warning is suppressed. |
| `python demos\missing_deps_demo\run_demo.py yaml` | Missing mandatory `pyyaml`: prints a clean `Error:` with install hint on `stderr` and exits with code `2` (no traceback). |
| `python demos\missing_deps_demo\run_demo.py rich` | Missing mandatory `rich`: prints a clean `Error:` with install hint on `stderr` and exits with code `2` (no traceback). |
| `python demos\missing_deps_demo\run_demo.py mixed` | Mixed fatal + warning (`pyyaml` + `psutil` missing): prints `Error:` for `pyyaml` and `[WARNING]` for `psutil` on `stderr`, then exits with code `2`. |
| `python demos\missing_deps_demo\run_demo.py mixed-all` | All dependencies missing (`pyyaml`, `rich`, `psutil`): prints fatal `Error:` lines for `pyyaml` and `rich` plus `[WARNING]` for `psutil`, then exits with code `2`. |

The live `psutil` scenario writes runtime logs under `demos/missing_deps_demo/logs/`,
which is ignored by Git and can be safely removed between runs.
