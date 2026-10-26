# Comprehensive Configuration Files Architecture & Usage Guide

> **Document Status**: Authoritative Technical Guide
> **Target Audience**: LBS users, Chromium / C++ systems engineers, build engineers, and automation maintainers

---

## Table of Contents
1. [Section 1: Executive Summary & Overview](#section-1-executive-summary--overview)
   - [1.1 The Role of YAML Configuration Profiles](#11-the-role-of-yaml-configuration-profiles)
   - [1.2 Architectural Ingestion Flow](#12-architectural-ingestion-flow)
   - [1.3 Environment Variable Expansion](#13-environment-variable-expansion)
2. [Section 2: YAML Schema & Field Specification](#section-2-yaml-schema--field-specification)
   - [2.1 Global Settings (`settings`)](#21-global-settings-settings)
   - [2.2 Notification Settings (`settings.notifications`) & Credential Separation](#22-notification-settings-settingsnotifications--credential-separation)
   - [2.3 Job Specification (`jobs`)](#23-job-specification-jobs)
   - [2.4 Dual Schema: `commands` vs `phases`](#24-dual-schema-commands-vs-phases)
3. [Section 3: OS & Subprocess Execution Mechanics](#section-3-os--subprocess-execution-mechanics)
   - [3.1 Process Isolation & Execution Model](#31-process-isolation--execution-model)
   - [3.2 The Windows `cmd.exe` Batch Trap & The `call` Requirement](#32-the-windows-cmdexe-batch-trap--the-call-requirement)
   - [3.3 Environment Variable Persistence (`&&` vs Temporary Batch Scripts)](#33-environment-variable-persistence--vs-temporary-batch-scripts)
4. [Section 4: Architecture Patterns for Multi-Clone Repositories](#section-4-architecture-patterns-for-multi-clone-repositories)
   - [4.1 Multi-Clone Layouts Across Physical Drives (`C:` & `D:`)](#41-multi-clone-layouts-across-physical-drives-c--d)
   - [4.2 The Disabled-by-Default Toggle Pattern (`build_it: false`)](#42-the-disabled-by-default-toggle-pattern-build_it-false)
   - [4.3 Profile Segregation (Clean vs Nightly Incremental)](#43-profile-segregation-clean-vs-nightly-incremental)
5. [Section 5: Validation, Safety Rules & Submodule Protection](#section-5-validation-safety-rules--submodule-protection)
   - [5.1 Static & Load-Time Validation Rules](#51-static--load-time-validation-rules)
   - [5.2 Strict `cwd` Existence Checks](#52-strict-cwd-existence-checks)
   - [5.3 The Submodule Protection Pattern (`git clean -xffd -e /depot_tools/`)](#53-the-submodule-protection-pattern-git-clean--xffd--e-depot_tools)
6. [Section 6: State Management, Resuming, and Phase Structuring](#section-6-state-management-resuming-and-phase-structuring)
   - [6.1 Execution State Tracking (`lbs_state.json`)](#61-execution-state-tracking-lbs_statejson)
   - [6.2 Solving the Network Expiration Bottleneck (Cross-Job Phased Execution)](#62-solving-the-network-expiration-bottleneck-cross-job-phased-execution)
   - [6.3 Resume Granularity & Idempotence](#63-resume-granularity--idempotence)
7. [Section 7: Production YAML Templates & Troubleshooting Checklist](#section-7-production-yaml-templates--troubleshooting-checklist)
   - [7.1 Minimal Working Configuration Template](#71-minimal-working-configuration-template)
   - [7.2 Production Multi-Phase Chromium Clone Template](#72-production-multi-phase-chromium-clone-template)
   - [7.3 Common Pitfalls & Troubleshooting Checklist](#73-common-pitfalls--troubleshooting-checklist)

---

## Section 1: Executive Summary & Overview

### 1.1 The Role of YAML Configuration Profiles
Local Builds Scheduler (`lbs`) is an automation orchestrator built for developers running long, resource-intensive compilations (such as Chromium, Android, Node.js core, or LLVM) across multiple working directories and software forks on a single machine.

Unlike cloud CI/CD systems that spin up ephemeral virtual machines or containers for parallel execution, `lbs` is deliberately designed for **serial throughput and hardware stability**:
* It executes heavyweight build jobs sequentially to eliminate CPU thrashing, memory exhaustion, and I/O bus contention across physical disks (`C:`, `D:`).
* It coordinates environment setup, dependency synchronization, compilation, testing, and system power management without human supervision (e.g., overnight).

YAML configuration files are the central source of truth in LBS. They declare:
1. **Global scheduler behaviors** (logging targets, abort policies, live streaming, notifications).
2. **Repository targets and working directories** (`cwd`).
3. **Execution stages** (single-pass `commands` or cross-job `phases`).
4. **Environment overlays and fault tolerance** (`env`, timeouts, retries).

---

### 1.2 Architectural Ingestion Flow

The configuration pipeline transforms raw YAML text into typed, validated Python dataclasses before initiating any subprocess execution:

```
+-----------------------------------------------------------------------+
| 1. RAW CONFIGURATION FILES                                            |
|    main-config.yaml + optional notifications.yaml                     |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 2. INGESTION & MERGE (_read_and_merge_config)                         |
|    - yaml.safe_load parses document root                              |
|    - notifications.yaml overrides/augments settings.notifications     |
|    - Environment variables expanded (${VAR} / $VAR)                   |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 3. STATIC VALIDATION (validate_config)                                |
|    - Unconditional verification: checks cwd folder existence on disk  |
|    - Mutually exclusive commands vs phases check                      |
|    - Types, ranges, duplicates, and URL schemas validated             |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 4. TYPED INSTANTIATION (load_config)                                  |
|    Config                                                             |
|      ├── Settings (stop_on_failure, log_dir, verbose, quiet, Notifs)  |
|      └── list[Job] (name, cwd, build_it, phases, env, retries, etc.)  |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
| 5. SCHEDULER EXECUTION (lbs.runner.Scheduler)                         |
|    - Concurrency lock secured: log_dir/lbs.lock                       |
|    - State tracking initialized: log_dir/lbs_state.json               |
|    - JobExecutor dispatches commands to isolated subprocesses         |
+-----------------------------------------------------------------------+
```

Key dataclass models defined in [`lbs.config`](../lbs/config.py):
* `Config`: Top-level configuration container holding `settings` and `jobs`.
* `Settings`: Global execution policies (`stop_on_failure`, `log_dir`, `verbose`, `quiet`, `notifications`).
* `NotificationsConfig` & `EmailConfig`: Dispatch endpoints (webhooks, email SMTP, desktop alerts).
* `Job`: Execution unit defining target `cwd`, `build_it` activation toggle, `commands` or `phases`, environment overlays, retry counts, and execution timeouts.

---

### 1.3 Environment Variable Expansion

LBS supports dynamic string substitution using POSIX and bash-style syntax:
* `${VARIABLE_NAME}`
* `$VARIABLE_NAME`

```yaml
settings:
  log_dir: "${BUILD_LOGS_ROOT}/nightly"

jobs:
  - name: my-build
    cwd: "$PROJECT_ROOT/browser-src"
    commands:
      - "python3 build.py --output ${BUILD_ARTIFACTS_DIR}"
```

**Interpolation Rules**:
1. Variable expansion is recursive across strings, dictionary keys, and list items during ingestion (`_expand_env_vars`).
2. If an environment variable is defined in the parent process running `lbs`, its string value is substituted verbatim.
3. If the environment variable is **unset or empty**, LBS substitutes an empty string (`""`) without throwing an exception.
4. Expansion occurs **at configuration load time**, prior to schema validation. This allows dynamic resolution of file paths, log folders, and webhook tokens from host environment variables.

---

## Section 2: YAML Schema & Field Specification

### 2.1 Global Settings (`settings`)

The `settings` block configures scheduler-wide operational parameters. All fields are optional and apply sensible defaults if omitted.

```yaml
settings:
  log_dir: "./logs"             # Default: "logs"
  stop_on_failure: true         # Default: false
  quiet: false                  # Default: false (live output is streamed to console by default)
  notifications:                # Default: empty (disabled)
    on_success: true
    on_failure: true
    desktop: false
```

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `log_dir` | `string` | `"logs"` | Directory path where session summaries, state files (`lbs_state.json`), concurrency locks (`lbs.lock`), and job log files are written. Relative paths are resolved relative to the current working directory from which `lbs` is invoked. The directory is created automatically if it does not exist. |
| `stop_on_failure` | `boolean` | `false` | When `true`, any job or phase failure halts the scheduler immediately, marking unexecuted jobs as `ABORTED` (or `PARTIAL` if earlier phases completed). When `false`, LBS logs the failure and continues executing subsequent jobs. |
| `quiet` | `boolean` | `false` | When `true`, suppresses live streaming of command output to the terminal (silent mode) while continuing to capture full logs in the job log files and printing the final summary table. Can also be enabled via CLI flag `-q` / `--quiet`. |
| `verbose` | `boolean` | `true` | (*Legacy / Alternate*) Live output streaming is enabled by default (`true`). Setting `verbose: false` is equivalent to `quiet: true`. If `quiet: true` is set, it takes precedence. |
| `notifications` | `object` | `None` | Notification triggers and endpoint configurations. |

---

### 2.2 Notification Settings (`settings.notifications`) & Credential Separation

Notifications allow unattended runs (e.g., overnight schedules) to report outcomes to messaging channels, email, or local desktop alerts.

```yaml
settings:
  notifications:
    on_success: true
    on_failure: true
    desktop: false
    slack_webhook: "https://hooks.slack.com/services/T00/B00/XXXX"
    discord_webhook: "https://discord.com/api/webhooks/XXXX"
    email:
      smtp_host: "smtp.example.com"
      smtp_port: 587
      smtp_username: "build-bot@example.com"
      smtp_password: "${SMTP_PASS}"
      use_tls: true
      sender: "build-bot@example.com"
      recipients:
        - "dev-team@example.com"
```

#### Credential Separation Pattern (`notifications.yaml`)
To avoid committing private webhook URLs, SMTP credentials, and team emails into public git repositories, store notification settings in a separate file (e.g. `notifications.yaml` or `configs/private-notifications.yaml`):

```yaml
# notifications.yaml (Excluded via .gitignore)
notifications:
  on_failure: true
  slack_webhook: "https://hooks.slack.com/services/..."
  email:
    smtp_host: "smtp.office365.com"
    smtp_port: 587
    smtp_username: "silviu@example.com"
    smtp_password: "${BUILD_SMTP_SECRET}"
    sender: "silviu@example.com"
    recipients: ["silviu@example.com"]
```

When invoking LBS, merge the credential profile:
```bash
lbs run configs/build-config.yaml -n configs/notifications.yaml --notifications
```
> [!NOTE]
> If a file named `notifications.yaml` exists in the directory from which `lbs` is executed and no `-n` argument is passed, LBS merges it automatically by default.

---

### 2.3 Job Specification (`jobs`)

The `jobs` section is a required list of job definitions executed sequentially in the declared order.

```yaml
jobs:
  - name: compile-neo-core
    cwd: "d:\\sources\\browser-neo-one"
    build_it: true
    env:
      BUILD_MODE: "debug"
      DEPOT_TOOLS_WIN_TOOLCHAIN: "0"
    retries: 1
    retry_delay_seconds: 15
    command_timeout_minutes: 120
    phases:
      sync:
        - "call neo.bat"
        - "call gclient sync -f -D"
      build:
        - "call python3 build.py --shared --debug"
```

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `name` | `string` | **Yes** | — | Unique alphanumeric identifier for the job. Used in logs (`<date>_<name>.log`), console displays, CLI filtering (`-j <name>`), and state tracking in `lbs_state.json`. |
| `cwd` | `string` | **Yes** | — | Working directory where commands will execute. **Must exist on disk at configuration load time**, even if `build_it` is set to `false`. |
| `build_it` | `boolean` | No | `true` | Activation flag. When `false`, the scheduler skips the job entirely during execution without running any commands. |
| `commands` | `list[str]` | *Conditional* | `[]` | Single-pass list of shell commands executed sequentially. Mutually exclusive with `phases`. |
| `phases` | `dict[str, list[str]]` | *Conditional* | `{}` | Named execution stages (e.g., `sync`, `build`, `test`). Mutually exclusive with `commands`. |
| `env` | `dict[str, str]` | No | `{}` | Key-value dictionary of environment variables applied as overlays to the subprocess environment for this job. |
| `retries` | `integer` | No | `0` | Number of times to retry the job's command sequence if any command fails. Must be $\ge 0$. |
| `retry_delay_seconds` | `number` | No | `0` | Duration in seconds to sleep before initiating a retry attempt. Must be $\ge 0$. |
| `command_timeout_minutes`| `number` | No | `null` | Maximum duration in minutes allowed for the job's command execution attempt before terminating the subprocess group. Must be $> 0$. |

---

### 2.4 Dual Schema: `commands` vs `phases`

LBS provides first-class native support for two execution models:

#### Model A: Single-Pass (`commands:`)
Ideal for lightweight jobs, quick utility sequences, or standalone builds that do not require multi-stage orchestration:
```yaml
jobs:
  - name: cleanup-caches
    cwd: "c:\\sources\\tools"
    build_it: true
    commands:
      - "call clean_ccache.bat"
      - "echo 'Cache purged'"
```
* **Internal normalization**: When loaded, `job.phases` is automatically set to `{"default": job.commands}`.

#### Model B: Multi-Stage Pipelines (`phases:`)
Designed for complex repositories where tasks must be separated into distinct stages (such as upfront network synchronization vs long-running offline builds):
```yaml
jobs:
  - name: neo-chromium-build
    cwd: "c:\\sources\\browser-neo-one"
    build_it: true
    phases:
      sync:
        - "call neo.bat"
        - "call git fetch origin"
        - "call gclient sync -f -D"
      build:
        - "call python3 build.py --shared --debug"
```
* **Internal normalization**: When loaded, `job.commands` is automatically set to the flattened list of all commands across all phases.

> [!CAUTION]
> **Mutual Exclusivity Rule**: A job must specify **either** `commands` **or** `phases`. Specifying both (or neither) in the same job definition raises a `ConfigError` during validation:
> ```
> ConfigError: Job 'my-job' cannot specify both 'commands' and 'phases'
> ```

---

## Section 3: OS & Subprocess Execution Mechanics

### 3.1 Process Isolation & Execution Model

When `lbs.runner` executes a job or phase:
1. It creates an isolated temporary batch script (`lbs_job_<random>.bat` on Windows) or shell script (`lbs_job_<random>.sh` on POSIX).
2. All commands defined for that phase/job are written into the script file sequentially.
3. On Windows, each line is followed by an `%ERRORLEVEL%` check:
   ```cmd
   @echo off
   <command_1>
   if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
   <command_2>
   if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
   ```
4. On POSIX, the script starts with `set -e` to exit immediately on error:
   ```sh
   #!/bin/sh
   set -e
   <command_1>
   <command_2>
   ```
5. `JobExecutor` spawns the temporary script inside a dedicated process group (`CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session=True` on POSIX).
6. Output is captured asynchronously via a bounded queue and streamed simultaneously to the job log file and the console (if verbose).
7. If a timeout occurs, `_terminate_process` sends `CTRL_BREAK_EVENT` on Windows or `SIGKILL` to the process group on POSIX, preventing lingering orphan build tools (such as Ninja or MSBuild) from consuming CPU.

---

### 3.2 The Windows `cmd.exe` Batch Trap & The `call` Requirement

One of the most dangerous and elusive bugs in Windows build automation occurs when invoking batch scripts or `.bat`/`.cmd` wrappers from within another batch script.

#### The Problem
In Windows `cmd.exe`, when a batch script runs another batch script directly without the `call` keyword:
```cmd
REM Inside lbs_job.bat
neo.bat
git fetch origin
```
`cmd.exe` **permanently transfers execution control** to `neo.bat`. It does **not** treat it as a subroutine. When `neo.bat` finishes its last line or executes `exit /b 0`, the entire `cmd.exe` process **exits immediately with code 0**. 

Control **NEVER returns** to `lbs_job.bat`. As a result:
* `git fetch origin` and all subsequent commands are **silently skipped**.
* The job reports a false-positive `SUCCESS` in LBS because `neo.bat` exited with return code 0.
* The build artifact was never created, leaving developers puzzled as to why the job completed in 5 seconds instead of 2 hours.

#### The Toolchain Shim Hazard: Chromium `depot_tools`
Chromium's `depot_tools` toolchain ships almost all of its command-line utilities as `.bat` wrappers:
* `git` $\rightarrow$ `depot_tools\git.bat`
* `gclient` $\rightarrow$ `depot_tools\gclient.bat`
* `python3` / `python` $\rightarrow$ `depot_tools\python3.bat`
* `gn` / `ninja` $\rightarrow$ `depot_tools\ninja.bat`

When environment setup scripts (such as `avast.bat` or `neo.bat`) prepend `depot_tools` to the system `%PATH%`, running `git` or `python3` in `cmd.exe` does **not** invoke an `.exe` directly. It invokes `depot_tools\git.bat` or `depot_tools\python3.bat`.

Therefore, omitting `call` on `git` or `python3` triggers the exact same silent batch termination trap!

#### The Golden Rule for Windows Configurations
Always prepend `call` to scripts and toolchain shims:
```yaml
# CORRECT
phases:
  sync:
    - "call neo.bat"
    - "call git fetch origin"
    - "call git reset --hard FETCH_HEAD"
    - "call gclient sync -f -D -j 4"
  build:
    - "call python3 build.py --shared --debug"

# INCORRECT (Triggers silent abortion after the first .bat shim)
phases:
  sync:
    - "neo.bat"
    - "git fetch origin"
```

---

### 3.3 Environment Variable Persistence (`&&` vs Temporary Batch Scripts)

A common question in build automation is how environment variable modifications (such as running `vcvarsall.bat`, `avast.bat`, or `set PATH=...`) propagate across build steps.

1. **Subprocess Isolation**: In Python, running two independent subprocesses means changes made to `%PATH%` or environment variables in process 1 vanish the instant process 1 exits. Process 2 inherits only the clean parent environment.
2. **How LBS Solves This**: Because LBS writes all commands of a job phase into a **single temporary batch script** executed in one subprocess, environment modifications made in line 1 persist for lines 2, 3, and 4 within that phase!
   ```cmd
   call neo.bat              <-- Mutates %PATH% and sets %DEPOT_TOOLS%
   call python3 build.py     <-- Inherits the mutated %PATH% from line 1
   ```
3. **Chaining with `&&`**: If a developer wishes to execute multiple dependent actions on a single line or ensure a variable override is coupled to a specific binary execution, `&&` can be used:
   ```yaml
   commands:
     - "set DEPOT_TOOLS_WIN_TOOLCHAIN=0 && call python3 build.py"
   ```

---

## Section 4: Architecture Patterns for Multi-Clone Repositories

### 4.1 Multi-Clone Layouts Across Physical Drives (`C:` & `D:`)

Developers maintaining large codebases (such as ASB Chromium and NEO Chromium) frequently keep multiple complete source checkouts spread across physical drives (`C:` SSD for OS/speed, `D:` NVMe for storage capacity).

A typical developer workstation layout includes:
* **ASB Chromium (5 clones)**:
  * `c:\sources\browser-chromium`
  * `c:\sources\browser-chromium-second`
  * `c:\sources\browser-chromium-third`
  * `d:\sources\browser-chromium`
  * `d:\sources\browser-chromium-second`
* **NEO Chromium (4 clones)**:
  * `c:\sources\browser-neo-one`
  * `c:\sources\browser-neo-two`
  * `d:\sources\browser-neo-one`
  * `d:\sources\browser-neo-two`

LBS handles cross-drive switching transparently. Under the hood, Python's `subprocess.Popen(cwd=job.cwd)` changes both the active drive letter and directory for the spawned shell session. There is no need to write `c:` or `d:` drive-switching commands inside YAML profiles.

---

### 4.2 The Disabled-by-Default Toggle Pattern (`build_it: false`)

In a multi-clone environment, developers rarely want to rebuild all 9 clones in a single night. However, maintaining 9 separate configuration files leads to massive duplication.

#### The Pattern
Pre-define **all known repository clones** in the configuration profile, setting `build_it: false` on every job:

```yaml
jobs:
  - name: asb-c-main
    cwd: "c:\\sources\\browser-chromium"
    build_it: false
    phases: { ... }

  - name: asb-c-second
    cwd: "c:\\sources\\browser-chromium-second"
    build_it: false
    phases: { ... }

  - name: asb-d-main
    cwd: "d:\\sources\\browser-chromium"
    build_it: false
    phases: { ... }
```

#### Workflow Benefits
1. **Zero Guesswork**: The build commands, compiler flags, and toolchain configurations for every clone are permanently saved and version-controlled in the profile.
2. **One-Second Activation**: Before leaving at the end of the day, the developer opens the profile, flips `build_it: true` on the 1 or 2 clones they modified, and launches `lbs run`.
3. **Clean Logs**: Inactive clones are logged as `[DISABLED]` or skipped, leaving state logs clean and organized.
4. **CLI Targeted Overrides**: A developer can also leave `build_it: false` in YAML and run a single job ad-hoc via CLI:
   ```bash
   lbs run configs/clean-asb-debug.yaml -j asb-c-main
   ```
   *(Note: The `-j` filter targets the job name directly; jobs filtered with `-j` must have `build_it: true` to execute).*

---

### 4.3 Profile Segregation (Clean vs Nightly Incremental)

Do not mix clean builds from scratch with nightly incremental builds in the same file. Separate profiles by lifecycle and target:

```text
configs/
  clean-asb-debug.yaml       # Full clean (git clean -xffd, reset, sync, debug build)
  clean-asb-release.yaml     # Full clean (release compiler flags)
  clean-neo-debug.yaml       # NEO fork full clean
  clean-neo-release.yaml     # NEO fork full clean
  nightly-incremental.yaml   # Incremental fetch, rebase, and quick compile
```

Clean profiles perform destructive repository resets (`git clean -xffd`, removing caches and untracked files), while nightly incremental profiles preserve object caches and `out/` build directories for speed.

---

## Section 5: Validation, Safety Rules & Submodule Protection

### 5.1 Static & Load-Time Validation Rules

Before any subprocess is launched, LBS performs strict validation via `validate_config()` (or when invoked directly via `lbs validate <config.yaml>`).

Validation enforces the following rules:
1. **YAML Integrity**: Root element must be a dictionary; YAML syntax must parse cleanly.
2. **Job Metadata**: Every job must possess a non-empty, unique string `name`. Duplicate job names trigger an immediate `ConfigError`.
3. **Execution Schema**: Every job must define either `commands` (non-empty list of non-empty strings) or `phases` (non-empty dict of non-empty lists of non-empty strings).
4. **Numeric Limits**:
   * `retries`: Integer $\ge 0$.
   * `retry_delay_seconds`: Finite number $\ge 0$.
   * `command_timeout_minutes`: Finite number $> 0$.
5. **Notification URLs**: Webhooks must begin with `http://` or `https://`.

```bash
# Validate your configuration without executing any jobs:
lbs validate configs/my-config.yaml
```
Exit code `0` indicates the configuration is 100% valid. Exit code `2` indicates a syntax or schema validation error.

---

### 5.2 Strict `cwd` Existence Checks

A critical design choice in LBS is **strict load-time directory validation**:
```python
# lbs/config.py
if not Path(cwd).is_dir():
    raise ConfigError(f"Job '{name}' 'cwd' directory does not exist: {cwd}")
```

#### Why `cwd` is Checked Even When `build_it: false`
Even if a job is disabled (`build_it: false`), LBS **strictly requires that its `cwd` directory exists on the host filesystem during config loading**.

* **The Rationale**: This prevents typos in paths (e.g., `c:\sourcess\project` instead of `c:\sources\project`) from silently sleeping in configuration files for months until someone flips `build_it: true`.
* **The Operational Impact**: If a configuration template lists 5 clones, but the host machine only has 4 of them cloned, `lbs validate` and `lbs run` will raise a `ConfigError` citing the missing directory.
* **The Fix**: Comment out or remove any clone blocks whose working directories do not yet exist on that physical workstation.

---

### 5.3 The Submodule Protection Pattern (`git clean -xffd -e /depot_tools/`)

When performing a clean build from scratch, developers commonly use `git clean -xffd` to discard all untracked files, ignored binaries, and stale build output.

However, in Chromium and large enterprise repositories, running a naive `git clean -xffd` causes two catastrophic failures:

#### 1. Self-Destruction of the Running Shell Script
In many clone setups, `depot_tools` is checked out directly inside the repository root (`depot_tools/`).
Because `neo.bat` or `avast.bat` prepends `depot_tools` to `%PATH%`, the command `git` resolves to `depot_tools\git.bat`.
If you execute:
```cmd
git clean -xffd
```
Git sees `depot_tools/` as an untracked directory and **deletes it while `git.bat` is still being executed by `cmd.exe`**!
The instant the file is deleted, `cmd.exe` crashes with:
```
The system cannot find the path specified.
```
The job terminates with exit code 1 before the build ever begins.

#### 2. Preservation of Local Setup Scripts
`git clean -x` deletes all ignored files, which wipes out local setup scripts (such as `neo.bat`, `avast.bat`, or local proxy configurations) placed in the repository root.

#### The Protected Clean Solution
Always use the exact exclusion pattern shown below:
```cmd
call git clean -xffd -e *.bat -e /depot_tools/
```

* **`-e *.bat`**: Excludes and preserves local batch scripts in the root directory.
* **`-e /depot_tools/`**: Excludes the toolchain directory. **The leading slash is vital**: it anchors the exclusion strictly to the repository root (`/depot_tools/`), ensuring that any nested submodule or secondary third-party tools (e.g. `src/third_party/depot_tools`) are still cleanly re-synchronized.

#### Discarding Generated Bootstrap Dirtiness
`depot_tools` contains internal bootstrap scripts (`bootstrap\win\win_tools.py`) that generate `python3.bat` upon invocation. This leaves the `depot_tools` git working tree permanently dirty. Subsequent calls to `update_depot_tools.bat` then fail with:
```
error: Your local changes to the following files would be overwritten by checkout
```
To keep the toolchain clean, execute a hard reset inside `depot_tools`:
```yaml
phases:
  sync:
    - "call git clean -xffd -e *.bat -e /depot_tools/"
    - "cd depot_tools"
    - "call git reset --hard"
    - "call .\\update_depot_tools.bat"
    - "cd .."
```

---

## Section 6: State Management, Resuming, and Phase Structuring

### 6.1 Execution State Tracking (`lbs_state.json`)

LBS automatically records execution progress to an atomic JSON state file located at `<log_dir>/lbs_state.json`.

```json
{
  "config_file": "configs-internal/clean-neo-debug.yaml",
  "session_date": "2026-10-11",
  "jobs": {
    "neo-c-one": {
      "status": "SUCCESS",
      "duration": 4820.5
    },
    "neo-d-one": {
      "status": "FAILED",
      "duration": 312.4
    }
  }
}
```

State writes are **atomic**: LBS writes to a temporary file (`lbs_state_*.tmp`) in the log directory and uses `os.replace` to guarantee that power cuts, crashes, or `Ctrl+C` interruptions never corrupt the state record.

---

### 6.2 Solving the Network Expiration Bottleneck (Cross-Job Phased Execution)

#### The Problem
In enterprise environments, developers often work behind corporate VPNs, proxies, or security policies (e.g., Zscaler) that authenticate for a limited time window (e.g., 2 hours).

Under traditional sequential execution:
```
Time:     0h                 1.5h               3.0h
Job 1:    [ Sync: 10m ] ---> [ Compile: 1.5h ]  (Finished)
Job 2:                                          [ Sync Fails! Network expired after 2h ]
```
When Job 2 tries to run its `git fetch` or `gclient sync` 2 hours into the night, network authentication has expired, causing all remaining builds in the queue to fail.

#### The Cross-Job Phased Execution Solution
LBS implements **Phased Mode (`--mode phased`)**, which is the default execution strategy whenever `phases:` are defined in a configuration profile:

```
Phase 1 (sync):   [ Job 1 Sync: 10m ] ---> [ Job 2 Sync: 10m ]  <-- ALL NETWORK CALLS FINISH IN 20 MINS!
Phase 2 (build):  [ Job 1 Compile: 1.5h ] ---> [ Job 2 Compile: 1.5h ] <-- RUNS COMPLETELY OFFLINE!
```

#### CLI Phase Control
Developers can also execute specific phases manually:
```bash
# Run ONLY the sync phase across all active jobs (e.g. while still online):
lbs run configs/clean-neo-debug.yaml --phase sync

# Run ONLY the heavy build phase across all active jobs (e.g. offline later):
lbs run configs/clean-neo-debug.yaml --phase build

# Force traditional per-job sequential execution if desired:
lbs run configs/clean-neo-debug.yaml --mode sequential
```

---

### 6.3 Resume Granularity & Idempotence

When an overnight build fails, you can resume execution using:
```bash
lbs run configs/my-config.yaml --resume latest
```

#### How Resume Works:
1. LBS reads `lbs_state.json` from the configured `log_dir`.
2. Any job that previously achieved status `SUCCESS` is **completely skipped**.
3. Any job that was `FAILED`, `PARTIAL`, `ABORTED`, `PENDING`, or `SKIPPED` is scheduled for re-execution.
4. **Within a job attempt, execution begins at the first command of the incomplete phase.** There are no mid-command checkpoints.
5. If all target jobs have already succeeded, LBS outputs:
   ```
   All selected jobs in the previous session completed successfully. Nothing to resume.
   ```
   and exits cleanly with code `0`.

---

### 6.4 Job Lifecycle Statuses & Progress Reporting

LBS classifies completed and non-completed jobs with distinct lifecycle states in both console session summaries and saved state (`lbs_state.json` / `lbs_status_<config>.json`):

| Status | Description | Resume Behavior |
| :--- | :--- | :--- |
| `SUCCESS` | All phases and commands completed successfully (exit code 0). | Skipped upon resume. |
| `FAILED` | A command failed (non-zero exit code or timeout). | Re-executed from the incomplete command/phase. |
| `PARTIAL` | Job halted mid-execution (e.g. completed early phases, but halted before finishing because another job failed under `stop_on_failure: true` or run was interrupted). | Re-executed from the first incomplete command/phase. |
| `ABORTED` | Job was enabled and queued, but never started because a preceding failure triggered `stop_on_failure: true` or the run was interrupted. | Re-executed upon resume. |
| `DISABLED` | Explicitly turned off via `build_it: false`. | Skipped upon resume unless re-enabled. |
| `INTERRUPTED` | The active job executing when the user aborted with Ctrl+C. | Re-executed from the incomplete command/phase. |

In the post-run terminal summary and session log, an inline progress indicator clarifies exact progress at a glance (e.g. `(1/2 phases complete)`, `(phase 'build')`, or `(never started)`).

---

## Section 7: Production YAML Templates & Troubleshooting Checklist

### 7.1 Minimal Working Configuration Template

Save as `minimal-build.yaml`:

```yaml
# LBS Minimal Configuration Template
settings:
  log_dir: "./logs"
  stop_on_failure: true
  verbose: true

jobs:
  - name: test-workspace
    cwd: "."
    build_it: true
    commands:
      - "echo 'Starting build sequence...'"
      - "echo 'All commands executed successfully.'"
```

Validate and run:
```bash
lbs validate minimal-build.yaml
lbs run minimal-build.yaml
```

---

### 7.2 Production Multi-Phase Chromium Clone Template

Save as `configs/clean-chromium-production.yaml`:

```yaml
# Production Multi-Phase Profile for Chromium Forks (ASB / NEO)
# Architecture:
# - Cross-job phased execution: All 'sync' phases run before any 'build' phases
# - Submodule protection: depot_tools and batch scripts preserved during clean
# - Windows batch compatibility: all toolchain shims prefixed with 'call'

settings:
  log_dir: "./logs"
  stop_on_failure: true
  verbose: true
  notifications:
    on_success: true
    on_failure: true
    desktop: true

jobs:
  # Clone 1: Primary C: Drive Workspace
  - name: chromium-c-main
    cwd: "c:\\sources\\browser-chromium"
    build_it: true
    retries: 1
    retry_delay_seconds: 20
    command_timeout_minutes: 180
    phases:
      sync:
        - "call setup_env.bat"
        - "call git fetch origin"
        - "call git reset --hard FETCH_HEAD"
        - "call git clean -xffd -e *.bat -e /depot_tools/"
        - "cd depot_tools"
        - "call git reset --hard"
        - "call .\\update_depot_tools.bat"
        - "cd .."
        - "call gclient sync -f -D -j 4"
      build:
        - "call python3 build.py --shared --debug --ccache -t chrome"

  # Clone 2: Secondary D: Drive Workspace (Disabled by default)
  - name: chromium-d-main
    cwd: "d:\\sources\\browser-chromium"
    build_it: false
    retries: 1
    retry_delay_seconds: 20
    command_timeout_minutes: 180
    phases:
      sync:
        - "call setup_env.bat"
        - "call git fetch origin"
        - "call git reset --hard FETCH_HEAD"
        - "call git clean -xffd -e *.bat -e /depot_tools/"
        - "cd depot_tools"
        - "call git reset --hard"
        - "call .\\update_depot_tools.bat"
        - "cd .."
        - "call gclient sync -f -D -j 4"
      build:
        - "call python3 build.py --shared --release --ccache -t chrome"
```

---

### 7.3 Common Pitfalls & Troubleshooting Checklist

| Symptom / Error | Root Cause | Remediation |
| :--- | :--- | :--- |
| **Subsequent commands in a job are skipped silently; build finishes in seconds with code 0.** | Calling a `.bat` or `.cmd` file (or a shim like `git`, `gclient`, `python3`) without `call`. `cmd.exe` transferred execution permanently. | Add `call` before every batch script or toolchain shim (e.g. `call neo.bat`, `call git fetch`). |
| **`The system cannot find the path specified.` with exit code 1 during clean.** | Running `git clean -xffd` without excluding `/depot_tools/`. Git deleted `depot_tools\git.bat` while `cmd.exe` was running it. | Add `-e /depot_tools/` to git clean: `call git clean -xffd -e *.bat -e /depot_tools/`. |
| **`ConfigError: Job 'X' 'cwd' directory does not exist: ...`** | The directory specified in `cwd` is missing from the physical drive. LBS validates `cwd` even when `build_it: false`. | Create the folder on disk, correct the path, or comment out the job block in the YAML file. |
| **`ConfigError: Job 'X' cannot specify both 'commands' and 'phases'`** | A single job block defines both `commands:` and `phases:`. | Select either `commands:` (for simple flat lists) or `phases:` (for multi-pass pipelines). |
| **`Error: Another Local Builds Scheduler instance is already running.` (Exit code 2)** | Another LBS process is running in the same `log_dir`, or an interrupted session left a stale lock. | Verify no running instances in Task Manager. If none exist, remove `<log_dir>/lbs.lock` (for the default configuration, `logs/lbs.lock`). |
| **Zscaler / VPN network timeout causes Job 2 to fail overnight.** | Running in sequential mode instead of phased mode. Job 1 compiled for 2 hours before Job 2 attempted to sync. | Structure jobs with `phases: sync / build`. Phased mode runs all sync steps upfront across all clones while online. |
| **`update_depot_tools.bat` aborts with `Your local changes to the following files would be overwritten by checkout`.** | `bootstrap\win\win_tools.py` regenerated `python3.bat`, leaving the toolchain directory dirty. | Run `cd depot_tools && call git reset --hard && cd ..` before running `update_depot_tools.bat`. |

---
