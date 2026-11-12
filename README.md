# Local Builds Scheduler (LBS)

A small, pragmatic build queue runner for developers working with large repositories and long-running builds.

The goal is simple: run heavy local build jobs sequentially (one after another), usually overnight, without wasting hardware resources by running multiple expensive builds in parallel.

This project focuses on a common problem in modern development environments: running several expensive build workflows on a single machine efficiently and predictably.

Instead of maximizing parallel execution, Local Build Scheduler focuses on serial throughput and system stability:

> Keep the machine busy, but avoid unnecessary resource contention.

---

## Key Features

- **Sequential Execution**: Runs jobs one at a time to prevent CPU, disk, and build-cache contention.
- **Job-level Isolation**: Each job runs in its specified working directory (`cwd`) with customizable environment variables.
- **Robust Error Handling**: Configure whether to stop execution on job failure or continue running subsequent jobs in the queue.
- **Timeout and Retry Controls**: Set custom command timeouts and retry attempts with configurable delays at the individual job level.
- **Detailed Session & Job Logging**: Generates high-level session summaries as well as separate, real-time command output logs for every job.
- **Notification Integration**: Dispatches rich notifications via Slack/Discord webhooks, SMTP emails, or native desktop alerts (balloon tips on Windows).
- **Concurrency Prevention**: Uses native, cross-platform file locking (`lbs.lock`) in the log directory to ensure only one instance runs at a time.
- **Session Resuming**: Save state automatically, allowing you to resume interrupted sessions from incomplete (failed, partial, aborted, or skipped) jobs using `--resume latest`.
- **Dry-Run Mode**: Validate and view the full planned execution details (including paths, environment variables, commands, retries, and timeouts) without running any commands.
- **Split-Screen Live Dashboard**: By default on interactive terminals, splits the console into a live scrolling compiler viewport (top ~75%) and a pinned real-time status dashboard (bottom ~25%) with progress bar, active commands, queue counts, elapsed time, and dynamic terminal window tab title updates.
- **Secure Credentials**: Separate notification files (`notifications.yaml`) and support environment variable interpolation (e.g., `${SMTP_PASSWORD}`) to avoid committing secrets to source control.

---

## Installation

> [!TIP]
> If you are setting up LBS on a new machine for the first time, check out our step-by-step [Kickstart Guide](docs/kickstart.md). For an in-depth reference on YAML schemas, multi-phase pipelines, OS subprocess mechanics, and multi-clone repository setups, refer to the [Configuration Files Architecture & Usage Guide](docs/configuration_guide.md).

Requires Python 3.11 or higher. It is recommended to run LBS within a Python virtual environment.

### 1. Create a Virtual Environment
```bash
python -m venv .venv
```

### 2. Activate the Virtual Environment
* **Windows (PowerShell)**:
  ```powershell
  .venv\Scripts\activate
  ```
* **Windows (Command Prompt)**:
  ```cmd
  .venv\Scripts\activate.bat
  ```
* **POSIX (Linux/macOS)**:
  ```bash
  source .venv/bin/activate
  ```

### 3. Install LBS in Editable Mode
```bash
pip install -e .
```

---

## Configuration

LBS uses YAML for configuration. The main configuration defines global settings and individual job blocks. For full details on schema parameters, cross-job phases, Windows `cmd.exe` batch requirements, and repository isolation, refer to the [Comprehensive Configuration Files Architecture & Usage Guide](docs/configuration_guide.md).

### Example Main Configuration (`build-config.yaml`)

```yaml
settings:
  stop_on_failure: false        # Continue with subsequent jobs even if one fails
  log_dir: "./logs"             # Directory to store log files
  verbose: true                 # Stream command stdout/stderr to CLI console in addition to log files
  notifications:
    on_success: false           # Only trigger notifications on overall session status
    on_failure: true            # Trigger alerts if any job in the session fails
    desktop: true               # Show native desktop alert notifications (Windows only)

jobs:
  - name: workspace-a
    cwd: "c:\\projects\\workspace-a"
    env:
      BUILD_MODE: "debug"
      PATH: "d:\\tools;%PATH%"
    retries: 2                  # Retry the job up to 2 times if any command fails
    retry_delay_seconds: 10     # Wait 10 seconds before retrying
    command_timeout_minutes: 15 # Terminate job if commands take longer than 15 minutes
    commands:
      - git reset --hard
      - git clean -xffd
      - git pull
      - npm install
      - npm run build

  - name: workspace-b
    cwd: "d:\\projects\\workspace-b"
    commands:
      - cargo clean
      - cargo build --release
```

### Configuration Schema Reference

#### Global Settings (`settings`)

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `log_dir` | `string` | `"logs"` | Directory path where session and job logs are written. Can be absolute or relative. |
| `stop_on_failure` | `boolean` | `false` | If `true`, aborts the remaining jobs in the queue immediately if any job fails. |
| `verbose` | `boolean` | `true` | If `true` (default), mirrors command outputs directly to standard output in real-time. Can be silenced with `-q` / `--quiet`. |
| `notifications` | `object` | *(Optional)* | Configuration for sending status notifications. (See details below). |

##### Settings Notifications Schema (`settings.notifications`)

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `on_success` | `boolean` | `true` | Send notification when all scheduled jobs complete successfully. |
| `on_failure` | `boolean` | `true` | Send notification when one or more jobs fail. |
| `desktop` | `boolean` | `false` | If `true`, triggers native Windows desktop balloon alerts (balloon tips). |
| `slack_webhook` | `string` | `null` | Slack Incoming Webhook URL to post structured results. |
| `discord_webhook` | `string` | `null` | Discord Incoming Webhook URL to post structured results. |
| `email` | `object` | `null` | SMTP configuration for email summary reports (supports nested fields: `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `use_tls`, `sender`, and `recipients`). |

---

#### Job Specification (`jobs`)

The `jobs` key contains a list of jobs executed sequentially in the specified order.

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `name` | `string` | *(Required)* | Unique name identifying the job. |
| `cwd` | `string` | *(Required)* | Absolute path to the working directory where the job's commands will execute. |
| `commands` | `list[str]` | *(Required)* | List of shell commands to execute in sequence. A command failure terminates the job block. |
| `env` | `dict[str, str]` | `{}` | Environment variable overlays added/overridden specifically for this job's commands. |
| `retries` | `integer` | `0` | Number of times to retry the job's entire sequence if any command fails. |
| `retry_delay_seconds` | `number` | `0` | Delay (in seconds) to wait before retrying the job. |
| `command_timeout_minutes`| `number` | `null` | Max execution duration (in minutes) allowed for the entire job command sequence. Commands exceeding this are terminated. |

---

#### Environment Variable Interpolation

Any string value in configuration files containing `${VAR_NAME}` or `$VAR_NAME` is dynamically replaced with the value of the environment variable `VAR_NAME` when the configuration is loaded. Unset environment variables default to an empty string `""`.

---

## Command Line Interface (CLI) Reference

The global entry point is `lbs`. It provides several subcommands.

### Common Execution Combinations

| Use Case / Goal | Command Invocations | Description & Behavior |
| :--- | :--- | :--- |
| **Standard Run** | `lbs run config.yaml` | Executes all jobs defined in `config.yaml` sequentially with a live 75%/25% split-screen console (streaming live compiler output in the top 75% and pinning real-time queue progress in the bottom 25%). |
| **Quiet Run** | `lbs run config.yaml -q` | Suppresses live compiler output streaming to the terminal and renders an in-place updating single-line progress bar; logs are still saved to disk and the summary table is displayed. |
| **Dry Run** | `lbs run config.yaml --dry-run` | Validates configuration and prints the full execution plan (commands, envs, logs paths, timeouts, retries) without running them. |
| **Filtered Run** | `lbs run config.yaml -j compile -j test` | Runs *only* the specified jobs (e.g. `compile` and `test`) in their sequence order. |
| **Phase-Filtered Run** | `lbs run config.yaml -p sync` | Runs *only* the specified phase(s) (e.g. `sync`) across every active job. Can be combined with `-j`. |
| **Sequential Mode** | `lbs run config.yaml --mode sequential` | Runs each job to completion (all of its phases) before starting the next job, instead of running one phase across every job before moving to the next phase. Keeps a job's own phases close together in time. |
| **Resume Interrupted Run** | `lbs run config.yaml --resume latest` | Loads the state from `lbs_status_<config>.json` and executes only the incomplete (failed, partial, aborted, or skipped) jobs from the previous session. |
| **Fresh Run** | `lbs run config.yaml --fresh` | Discards any existing saved session state and starts all jobs from the beginning without requiring manual state file deletion. |
| **Inspect Session Status** | `lbs status config.yaml` | Inspects saved build queue status without executing, displaying per-job outcomes, phase details, elapsed times, and resume suggestions. |
| **Clean Session State** | `lbs clean config.yaml` | Deletes the profile-scoped status file (`lbs_status_<config>.json`) and temporary session files. |
| **Run with Notifications** | `lbs run config.yaml --notifications` | Enables status notifications to webhooks/desktop alerts defined in the configuration. |
| **Run with Secret Credentials** | `lbs run config.yaml -n private.yaml --notifications` | Merges settings from `private.yaml` (typically credentials) with `config.yaml` and executes with notifications enabled. |
| **Run and Auto-Shutdown** | `lbs run config.yaml --shutdown` | Executes all jobs, then schedules an OS shutdown **only if every job succeeded**. A failed session leaves the machine powered on for diagnosis. |
| **Overnight Resumed Run** | `lbs run config.yaml --resume latest --notifications` | Resumes a previous run and dispatches alerts on outcome. Append `--shutdown` to power the machine off on success. |
| **List Jobs** | `lbs list config.yaml` | Prints the names of all jobs in the order they will be executed, one per line. |
| **Validate Configuration** | `lbs validate config.yaml` | Validates YAML syntax and config schema. Exit code `0` if valid, `2` if invalid. |
| **Validate Merged Configuration** | `lbs validate config.yaml -n private.yaml` | Validates syntax and merged schema of both the main configuration and private notification config together. |

### Global Options

* `--version` — Show version info and exit.
* `-h`, `--help` — Show help message and exit.

### Subcommands

#### `run`
Run all or filtered jobs defined in the configuration file.

```bash
lbs run <config-path> [options]
```

**Options:**
* `-q`, `--quiet` — Suppress live command execution output from being streamed to the console and display an in-place updating single-line progress bar (full logs are still recorded to disk under `log_dir`, and the final summary table is still printed).
* `-j <job-name>`, `--job <job-name>` — Filter to run *only* the specified job. Can be specified multiple times (e.g. `lbs run config.yaml -j compile -j test`).
* `-p <phase-name>`, `--phase <phase-name>` — Filter to run *only* the specified phase (for configs using multi-phase `phases:` jobs). Can be specified multiple times and combined with `-j`.
* `--mode phased|sequential` — Execution strategy across jobs. `phased` (default) runs each phase across every active job before moving to the next phase (e.g. every job's `sync`, then every job's `build`). `sequential` instead runs every phase of one job to completion before starting the next job — use this to keep a job's own phases close together in time, e.g. so a job's `build` step starts right after its own `sync` instead of waiting behind other jobs' builds.
* `--dry-run` — Print the execution plan (log paths, environment variables, commands, retries, and timeouts) without running any commands.
* `--resume latest` — Resume an interrupted or failed session from the latest saved state (`lbs_state.json`), executing only the incomplete (failed, partial, aborted, or skipped) jobs.
* `--fresh`, `--ignore-saved-state` — Discard any existing saved session state (`lbs_status_<config>.json`) and temporary session files, executing all jobs from the beginning. Mutually exclusive with `--resume`.
* `-n <path>`, `--notifications-config <path>` — Path to a separate YAML file containing private notification settings (e.g., SMTP credentials, Slack/Discord webhooks) to merge with the main config.
* `--notifications` — Explicitly enable sending dispatches for desktop, webhook, and email notifications for this execution run.
* `--shutdown` — *Optional, off by default.* Schedules an OS shutdown after all jobs in the session complete (60-second delay; abort via `shutdown /a` on Windows or `shutdown -c` on Linux/macOS). The shutdown is only scheduled when the session **succeeds**: if any job fails the machine is deliberately left running so the failure can be diagnosed, and a message explaining the skip is written to stderr. It is also skipped under `--dry-run`, which executes no jobs.

#### `status`
Inspect saved session status for a configuration without executing.

```bash
lbs status <config-path> [options]
```

**Options:**
* `--json` — Output saved session status data as structured JSON instead of human-readable text.

#### `clean`
Remove saved session state and temporary progress logs for a specific configuration file.

```bash
lbs clean <config-path>
```

#### `validate`
Check if the provided configuration file exists, is valid YAML, and conforms to the schema.

```bash
lbs validate <config-path> [options]
```

**Options:**
* `-n <path>`, `--notifications-config <path>` — Path to a separate YAML notifications configuration file to validate together with the main config.

#### `list`
Print the names of all jobs defined in the configuration file, in order of execution (one per line).

```bash
lbs list <config-path>
```

---

## Exit Codes

The tool exits with explicit, predictable codes:
* `0` — Success: all scheduled jobs completed successfully (or in `lbs status`, all enabled jobs succeeded).
* `1` — Job Failure: one or more jobs failed, were interrupted, or remain uncompleted (or in `lbs status`, uncompleted/failed jobs exist).
* `2` — Setup/Configuration Error: command argument parse failures, configuration syntax errors, lock file contention, missing saved session state in `lbs status`, or invalid job filter names.

---

## Emergency / Recovery Playbook

A checklist for when an overnight or long-running session fails, gets interrupted, or you need to step in mid-run — covering both what to do and the mechanics behind `lbs`'s recovery features.

### 0. Activate the virtual environment first

Every command below assumes an active venv in your current shell — this doesn't persist between terminal sessions, so it's the first thing to do each time you open a new one:

* **Windows (PowerShell)**: `.venv\Scripts\activate`
* **Windows (Command Prompt)**: `.venv\Scripts\activate.bat`
* **POSIX (Linux/macOS)**: `source .venv/bin/activate`

If `lbs` isn't found afterwards, activation likely failed silently (see the PowerShell execution-policy gotcha in the [Kickstart Guide](docs/kickstart.md)) — you can always bypass it and call the venv's `lbs` directly: `.venv\Scripts\lbs.exe --version`.

### 1. See what actually happened — don't guess

```bash
lbs status config.yaml
```
Reads the saved `lbs_status_<config>.json` file (with `lbs_state.json` fallback) and shows per-job, per-command outcomes without touching anything:
```
LBS Session Status: config.yaml
Profile State: logs/lbs_status_config.json
Session Started: 2026-10-22 23:15:00 | Last Updated: 2026-10-23 01:42:10
Outcome: FAILED (Halted on job 'chromium-debug', phase 'compile')

Jobs:
  [PASS] chromium-release    (sync: DONE, compile: DONE)           took 01:45:12
  [FAIL] chromium-debug      (sync: DONE, compile: FAILED at cmd 3) took 00:42:01
  [SKIP] package-artifacts   (not started, aborted by failure)     (-)
  [OFF]  upload-symbols      (disabled: build_it is false)         (-)

Action:
  To resume from the failed step, run:
    lbs run config.yaml --resume latest
```
Pass `--json` for machine-readable output in CI or automated pipelines. Always check this before deciding how to recover — the failure might be one command deep into one job, not the whole thing.

### 2. Preview before you commit hours of build time

```bash
lbs run config.yaml --dry-run
```
Combine with whatever filters/flags you're about to use (`-j`, `-p`, `--resume`) to confirm the plan only touches what you expect.

### 3. Resume without redoing finished work

```bash
lbs run config.yaml --mode sequential --resume latest
```
This reads the saved status file and:
1. Reconstructs the status of all jobs and individual commands from the previous session.
2. Skips all jobs that already completed with a `SUCCESS` status.
3. Sequentially executes only the remaining incomplete (`FAILED`, `PARTIAL`, `ABORTED`, `INTERRUPTED`, or `PENDING`) jobs, **skipping individual commands that already succeeded (`DONE`)** so builds resume right where they left off.
4. If all selected jobs had already succeeded, it prints a status message and exits immediately.

Pairing it with `--mode sequential` keeps each job's own phases close together in time (a job's `build` starts right after its own `sync` instead of waiting behind other jobs' builds) — useful after a failure caused by something going stale or unreachable during a long wait between phases (e.g. a VPN/network drop during another job's multi-hour build).

### 4. When saved state itself is the problem

```bash
lbs run config.yaml --fresh    # (or --ignore-saved-state) discard state, rerun everything from scratch
lbs clean config.yaml          # just wipe the saved state, don't run anything
```
Use these instead of `--resume` (mutually exclusive with it) when the config changed meaningfully or the saved state looks wrong, rather than "one job failed." `lbs clean` confirms with `Cleared saved session state for config.yaml.` (or `No saved session state found...` if there was nothing to clear).

### 5. Scope a run to just what you need

```bash
lbs run config.yaml -j <job-name>               # only these job(s)
lbs run config.yaml -p <phase-name>             # only this phase, across all active jobs
lbs run config.yaml -p build -j <job-name>      # combine both
lbs list config.yaml                            # reminder of job names
```

### 6. Stepping away

```bash
lbs run config.yaml -q                           # quiet mode: compact progress bar, full logs still on disk
lbs run config.yaml --resume latest --shutdown   # power off automatically, only if the resumed session succeeds
```
`--shutdown` is skipped on failure, on `--dry-run`, and if any enabled job was filtered out — so it won't power off mid-recovery by accident.

### 7. "Another instance is already running"

LBS secures an exclusive file lock (`lbs.lock`) in `log_dir` so two instances can't write to the same logs or build concurrently. If you hit this error and nothing is actually running, delete the stale `lbs.lock` file; otherwise close the other `lbs` session first.

> **Don't reach for a build script's own `--no-sync`-style flag as a shortcut just because `lbs` already ran its `sync` phase.** A job's `build` step can still rely on that script's internal sync to do more than fetch — e.g. reapplying local patches that `lbs`'s own sync step resets. Skipping it can silently drop work that's unrelated to networking. Check what that flag actually gates in the underlying build script before assuming it's redundant.

---

## Logging

Logging is structured to capture both a high-level summary and real-time execution outputs.

### 1. Session Log
A file named `<YYYY-MM-DD>_session.log` contains high-level scheduler actions:
- Scheduler start and resume events
- Active settings and parameters loaded
- Job start, end, and duration times
- Exit codes and execution errors
- Final runs status summary

### 2. Job Logs
For each job `<job-name>`, a separate log file named `<YYYY-MM-DD>_<job-name>.log` is written. This log contains:
- Detailed execution context (CWD, environment overlays)
- Each exact command executed with a precise timestamp
- Raw standard output (stdout) and standard error (stderr) streamed in real-time
- Detailed exit codes or timeout errors

Example log directory layout:
```text
logs/
  lbs.lock
  lbs_state.json
  2026-06-19_session.log
  2026-06-19_prepare.log
  2026-06-19_compile.log
  2026-06-19_test.log
```

---

## Planned Improvements

Future updates may introduce the following features:
- Job priorities (ordering execution based on custom weights instead of sequence order)
- Time windows (allowing execution restricted to specific night windows)
- Resource locks (defining custom execution constraints for specific files or hardware)
- Smarter scheduling algorithms

---

## Design philosophy

Keep it small and predictable.

Prefer:
- simple configuration
- explicit behavior
- useful logs
- minimal dependencies

Avoid turning it into a complex CI system too early.

---

## Status

**Version 1.0.0** is fully implemented and ready for local development workflows. It provides robust sequential execution, session and job-level logging, flexible failure handling, configuration validation, and job filtering.

---

AI tools were used as coding assistants during development. All generated code was reviewed, tested, and integrated by the project maintainer.

---

© 2026 Silviu-Marius Ardelean. Licensed under the [Apache-2.0 License](LICENSE).
