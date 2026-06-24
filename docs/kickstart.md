# LBS Kickstart Guide

Welcome to the Local Builds Scheduler (LBS) onboarding guide. This document walks you through setting up LBS on a new machine, configuring your YAML build files, and running your first build sequence.

---

## 1. Prerequisites

Before installing, ensure the machine has the following tools installed:
* **Python**: Version **3.11** or higher. Confirm with:
  ```bash
  python --version
  ```
* **Git**: To clone the repository.
* **Compiler/Build Tools**: Ensure the compilers or build tools needed for your target software (e.g., Visual Studio Build Tools, MSBuild, GCC, Clang, Rust, or Node.js) are installed and added to the system PATH.

---

## 2. Step-by-Step Installation

### Step 1: Clone the Repository
Clone the repository to a folder on your local machine and enter the workspace directory:
```bash
git clone https://github.com/SilviuArdelean/local-builds-scheduler/
or
git clone git@github.com:SilviuArdelean/local-builds-scheduler.git
cd local-builds-scheduler
```

### Step 2: Establish the Python Virtual Environment
Always install python packages inside a virtual environment to prevent dependency conflicts with system-level packages.

1. **Create the virtual environment**:
   ```bash
   python -m venv .venv
   ```
2. **Activate the environment**:
   * **Windows (PowerShell)**:
     ```powershell
     .venv\Scripts\activate
     ```
   * **Windows (Command Prompt / CMD)**:
     ```cmd
     .venv\Scripts\activate.bat
     ```
   * **POSIX (Linux/macOS)**:
     ```bash
     source .venv/bin/activate
     ```
3. **Upgrade pip** (Recommended):
   ```bash
   python -m pip install --upgrade pip
   ```

### Step 3: Install LBS
Install the package in **editable mode** (`-e`). This compiles metadata links so any local changes you make to LBS files are immediately reflected in the CLI.
```bash
pip install -e .
```

### Step 4: Verify Installation
Verify that the `lbs` command is registered and functional:
```bash
lbs --version
```
*(If the command is not found, verify that your terminal shell successfully activated the `.venv` in the previous step, or run the package directly: `python -m lbs.cli --version`)*

---

## 3. Configuring Your First Build YAML File

LBS uses a structured YAML format to define settings and sequential build jobs. Below is a minimal template:

Create a new file named `my-build-config.yaml` in your workspace directory:

```yaml
# LBS Build Configuration Profile

settings:
  # Directory where session-level and job-specific logs are written
  log_dir: "./logs"

  # Stop execution of the remaining queue if any build fails
  stop_on_failure: true

  # Stream compiler standard outputs live to your terminal screen
  verbose: true

jobs:
  # Job 1: Clean build environment
  - name: clean-workspace
    cwd: "d:\\sources\\my-project"
    build_it: true
    commands:
      - "git clean -xffd"
      - "git reset --hard"

  # Job 2: Main compilation sequence
  - name: compile-project
    cwd: "d:\\sources\\my-project"
    build_it: true
    retries: 1                  # Retry compilation once if it fails
    retry_delay_seconds: 10     # Wait 10 seconds before retrying
    command_timeout_minutes: 30 # Terminate job if it takes longer than 30 mins
    commands:
      - "python3 build.py --shared --debug"
```

### Configuration Fields Breakdown:
* **`settings`**:
  * `log_dir`: Path to log output. If the directory does not exist, LBS creates it automatically.
  * `stop_on_failure`: Set to `true` to immediately halt subsequent jobs if one fails. Set to `false` if jobs are independent.
  * `verbose`: Set to `true` to see live compiler outputs on screen in addition to logs.
* **`jobs`**:
  * `name`: Unique identifier for the job. Used to name log files and track resume state.
  * `cwd`: Absolute path to the directory where commands will run. **Must exist on the machine.**
  * `build_it`: Boolean flag (`true` or `false`). Set to `false` to skip a job entirely.
  * `commands`: A list of commands. 
    * **Windows Note**: When calling other batch scripts inside commands, prefix them with `call` (e.g. `call avast.bat`).
  * `env`: *(Optional)* A key-value dictionary of environment variables specific to this job.
  * `retries` / `retry_delay_seconds`: *(Optional)* Number of retries and pause interval upon command failure.
  * `command_timeout_minutes`: *(Optional)* Terminate the execution if it hangs.

---

## 4. Run, Validate, and Monitor

Once your YAML is written, follow these run steps:

### 1. Validate the Configuration
Always check syntax and directory existence before running:
```bash
lbs validate my-build-config.yaml
```
*If validation fails, LBS prints a clean description of the missing folders or schema errors.*

### 2. Run a Dry Run
Verify the scheduled execution sequence:
```bash
lbs run my-build-config.yaml --dry-run
```
Ensure the target jobs are active and disabled jobs are marked `[DISABLED]`.

### 3. Run the Execution
Kick off the sequential execution:
```bash
lbs run my-build-config.yaml --verbose
```

### 4. Monitor & Recover
* **Logs**: Check `./logs/` for `<date>_session.log` and `<date>_<job-name>.log`.
* **State**: LBS writes execution progress to `logs/lbs_state.json`.
* **Resuming**: If a job fails, resolve the issue in your target build, and resume from the failure point by appending `--resume latest`:
  ```bash
  lbs run my-build-config.yaml --resume latest --verbose
  ```
