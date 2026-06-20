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
- **Session Resuming**: Save state automatically, allowing you to resume interrupted sessions from the last failed or skipped job using `--resume latest`.
- **Dry-Run Mode**: Validate and view the full planned execution details (including paths, environment variables, commands, retries, and timeouts) without running any commands.
- **Secure Credentials**: Separate notification files (`notifications.yaml`) and support environment variable interpolation (e.g., `${SMTP_PASSWORD}`) to avoid committing secrets to source control.

---

## Installation

Assuming you have cloned the repository, install it locally:

```bash
pip install -e .
```

*Note: Requires Python 3.11 or higher.*

---

## Configuration

LBS uses YAML for configuration. The main configuration defines global settings and individual job blocks.

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
| `verbose` | `boolean` | `false` | If `true`, mirrors all command outputs (stdout/stderr) directly to standard output in real-time. |
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
| **Standard Run** | `lbs run config.yaml` | Executes all jobs defined in `config.yaml` sequentially. |
| **Dry Run** | `lbs run config.yaml --dry-run` | Validates configuration and prints the full execution plan (commands, envs, logs paths, timeouts, retries) without running them. |
| **Filtered Run** | `lbs run config.yaml -j compile -j test` | Runs *only* the specified jobs (e.g. `compile` and `test`) in their sequence order. |
| **Verbose Debugging** | `lbs run config.yaml -v` | Mirrors command stdout/stderr directly to standard output in real-time while also saving logs to disk. |
| **Resume Interrupted Run** | `lbs run config.yaml --resume latest` | Loads the state from `lbs_state.json` and executes only the failed or skipped jobs from the previous session. |
| **Run with Notifications** | `lbs run config.yaml --notifications` | Enables status notifications to webhooks/desktop alerts defined in the configuration. |
| **Run with Secret Credentials** | `lbs run config.yaml -n private.yaml --notifications` | Merges settings from `private.yaml` (typically credentials) with `config.yaml` and executes with notifications enabled. |
| **Run and Auto-Shutdown** | `lbs run config.yaml --shutdown` | Executes all jobs and schedules an OS shutdown after completion (ideal for overnight builds). |
| **Overnight Resumed Run** | `lbs run config.yaml --resume latest --notifications --shutdown` | Resumes a previous run, dispatches alerts on outcome, and shuts down the machine upon completion. |
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
* `-v`, `--verbose` — Mirror command execution stdout/stderr directly to standard output (in addition to writing log files).
* `-j <job-name>`, `--job <job-name>` — Filter to run *only* the specified job. Can be specified multiple times (e.g. `lbs run config.yaml -j compile -j test`).
* `--dry-run` — Print the execution plan (log paths, environment variables, commands, retries, and timeouts) without running any commands.
* `--resume latest` — Resume an interrupted or failed session from the latest saved state (`lbs_state.json`), executing only the failed or skipped jobs.
* `-n <path>`, `--notifications-config <path>` — Path to a separate YAML file containing private notification settings (e.g., SMTP credentials, Slack/Discord webhooks) to merge with the main config.
* `--notifications` — Explicitly enable sending dispatches for desktop, webhook, and email notifications for this execution run.
* `--shutdown` — Automatically schedules an OS shutdown after completion of all jobs in the session (60-second delay; can be aborted via `shutdown /a` on Windows or `shutdown -c` on Linux/macOS).

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
* `0` — Success: all scheduled jobs completed successfully.
* `1` — Job Failure: one or more jobs failed.
* `2` — Setup/Configuration Error: command argument parse failures, configuration syntax errors, lock file contention, or invalid job filter names.

---

## Advanced Capabilities

### Single-Instance Prevention (Concurrency Lock)

To prevent multiple scheduler instances from writing to the same logs or executing builds concurrently, LBS secures an exclusive file lock (`lbs.lock`) in the configured log directory (`log_dir`). If a secondary instance attempts to run using a configuration pointing to the same log directory, it will terminate immediately with a clean error message and exit code `2`.

### Session Resuming (`--resume latest`)

LBS automatically tracks execution progress inside a `lbs_state.json` file created inside the `log_dir`. 

If a build fails, or the scheduler is interrupted (e.g., `Ctrl+C`), you can rerun the exact same command adding the `--resume latest` flag:
```bash
lbs run config.yaml --resume latest
```
This reads `lbs_state.json` and:
1. Reconstructs the status of all jobs from the session.
2. Skips all jobs that have already completed with a `SUCCESS` status.
3. Sequentially executes only the remaining `FAILED`, `PENDING`, or `SKIPPED` jobs.
4. If all selected jobs had already succeeded, it outputs a status message and exits immediately.

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
