# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Interactive demo launcher for previewing LBS missing-dependency behavior
safely without uninstalling packages from your virtual environment.

Usage (from repository root):
    python demos/missing_deps_demo/run_demo.py <scenario>

Scenarios:
    psutil           Live dashboard run with psutil missing (N/A + warning)
    psutil-validate  'lbs validate' with psutil missing (warning on stderr)
    psutil-dry-run   'lbs run --dry-run' with psutil missing (warning on stderr)
    psutil-disabled  'lbs validate' with psutil missing & monitoring disabled
    yaml             Missing mandatory 'pyyaml' (clean error, exit code 2)
    rich             Missing mandatory 'rich' (clean error, exit code 2)
    mixed            Missing mandatory 'pyyaml' + soft 'psutil' (error + warning)
    mixed-all        Missing 'pyyaml', 'rich', and 'psutil' (2 errors + 1 warning)
    all              Run all non-interactive scenarios in sequence
"""

from __future__ import annotations

import argparse
import importlib.metadata
import subprocess
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parents[1]
DEFAULT_CONFIG = DEMO_DIR / "missing-deps-demo.yaml"
DISABLED_CONFIG = DEMO_DIR / "missing-deps-disabled.yaml"

SCENARIOS = (
    "psutil",
    "psutil-validate",
    "psutil-dry-run",
    "psutil-disabled",
    "yaml",
    "rich",
    "mixed",
    "mixed-all",
    "all",
)


def _install_simulated_missing(module_name: str, dist_name: str) -> None:
    """Blocks importing module_name and hides dist_name from importlib.metadata."""

    class _ImportBlocker:
        def find_spec(self, name: str, path, target=None):
            if name == module_name or name.startswith(f"{module_name}."):
                raise ModuleNotFoundError(
                    f"No module named '{name}' (simulated by demo)",
                    name=module_name,
                )
            return None

    sys.meta_path.insert(0, _ImportBlocker())

    orig_distribution = importlib.metadata.distribution
    target_norm = dist_name.lower().replace("_", "-")

    def _masked_distribution(name: str):
        if name.lower().replace("_", "-") == target_norm:
            raise importlib.metadata.PackageNotFoundError(name)
        return orig_distribution(name)

    importlib.metadata.distribution = _masked_distribution  # type: ignore[assignment]


def _run_lbs_with_args(lbs_args: list[str]) -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from lbs.cli import main

    sys.argv = ["lbs", *lbs_args]
    try:
        main()
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    return 0


def _run_single_scenario(scenario: str) -> int:
    if scenario == "psutil":
        _install_simulated_missing("psutil", "psutil")
        return _run_lbs_with_args(["run", str(DEFAULT_CONFIG), "--fresh"])

    if scenario == "psutil-validate":
        _install_simulated_missing("psutil", "psutil")
        return _run_lbs_with_args(["validate", str(DEFAULT_CONFIG)])

    if scenario == "psutil-dry-run":
        _install_simulated_missing("psutil", "psutil")
        return _run_lbs_with_args(["run", str(DEFAULT_CONFIG), "--dry-run"])

    if scenario == "psutil-disabled":
        _install_simulated_missing("psutil", "psutil")
        return _run_lbs_with_args(["validate", str(DISABLED_CONFIG)])

    if scenario == "yaml":
        _install_simulated_missing("yaml", "pyyaml")
        return _run_lbs_with_args(["validate", str(DEFAULT_CONFIG)])

    if scenario == "rich":
        _install_simulated_missing("rich", "rich")
        return _run_lbs_with_args(["validate", str(DEFAULT_CONFIG)])

    if scenario == "mixed":
        _install_simulated_missing("yaml", "pyyaml")
        _install_simulated_missing("psutil", "psutil")
        return _run_lbs_with_args(["validate", str(DEFAULT_CONFIG)])

    if scenario == "mixed-all":
        _install_simulated_missing("yaml", "pyyaml")
        _install_simulated_missing("rich", "rich")
        _install_simulated_missing("psutil", "psutil")
        return _run_lbs_with_args(["validate", str(DEFAULT_CONFIG)])

    raise ValueError(f"Unknown scenario: {scenario}")


def _run_all_noninteractive() -> int:
    batch = [
        (
            "psutil-validate",
            "Soft dependency missing (psutil) during 'lbs validate'",
        ),
        (
            "psutil-dry-run",
            "Soft dependency missing (psutil) during 'lbs run --dry-run'",
        ),
        (
            "psutil-disabled",
            "psutil missing with system_resources.enabled=false (suppressed)",
        ),
        ("yaml", "Mandatory dependency missing (pyyaml)"),
        ("rich", "Mandatory dependency missing (rich)"),
        ("mixed", "Mixed fatal (pyyaml) + warning (psutil)"),
        ("mixed-all", "Mixed fatal (pyyaml, rich) + warning (psutil)"),
    ]
    for name, title in batch:
        print(f"\n{'=' * 72}", flush=True)
        print(f"Scenario: {name} — {title}", flush=True)
        print("=" * 72, flush=True)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), name],
            cwd=str(REPO_ROOT),
            check=False,
        )
        print(f"[Exit code: {proc.returncode}]", flush=True)
    print(
        "\nTo also preview the live split-screen dashboard with psutil missing, run:\n"
        "  python demos\\missing_deps_demo\\run_demo.py psutil"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preview LBS missing-dependency warnings and errors safely "
            "without uninstalling packages from your environment."
        )
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        default="all",
        choices=SCENARIOS,
        help="Scenario to run (default: 'all').",
    )
    args = parser.parse_args()
    if args.scenario == "all":
        sys.exit(_run_all_noninteractive())
    sys.exit(_run_single_scenario(args.scenario))


if __name__ == "__main__":
    main()
