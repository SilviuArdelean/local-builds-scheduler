# Local Builds Scheduler

A small, pragmatic builds queue runner for developers working with large repositories and long-running builds.

The goal is simple: run heavy local build jobs one after another, usually overnight, without wasting hardware resources by running multiple expensive builds in parallel.

This project focuses on a common problem in modern development environments: running several expensive build workflows on a single machine efficiently and predictably.

Instead of maximizing parallel execution, Local Build Scheduler focuses on throughput and stability:

> keep the machine busy, but avoid unnecessary contention.

## Why

Large repositories and complex build systems can be expensive to run. A developer may maintain multiple local workspaces, each requiring periodic synchronization and compilation.

A typical workflow may include steps such as:

```text
- updating sources
- cleaning build artifacts
- syncing dependencies
- running debug and release builds
```

Running several such workflows in parallel is not always beneficial. It can create bottlenecks around:

- shared caches (for example compiler caches)
- build system coordination
- disk I/O pressure
- antivirus scanning overhead
- filesystem churn
- environment conflicts between builds

Local Build Scheduler runs those jobs in a queue, with clear logging and predictable execution.

## Goals

The first version should be simple, reliable, and useful.

It should:

- read jobs from a YAML configuration file
- execute jobs sequentially
- run each job in its own working directory
- log command output per job
- log important scheduler events
- continue with the next job when one job fails, unless configured otherwise
- work well with shared build caches when execution is serialized
- make unattended builds easy to run and inspect later

## Non-goals

This is not a full CI system.

It does not try to replace:

- Jenkins
- Buildbot
- GitHub Actions
- Azure Pipelines
- TeamCity

It is also not intended to be a generic workflow engine from day one. The first version focuses on one machine, a queue of local jobs, and clear logs.

## Configuration

The project uses YAML for configuration.

Example:

```yaml
settings:
  stop_on_failure: false
  log_dir: logs

jobs:
  - name: workspace-a
    cwd: c:\projects\workspace-a
    commands:
      - git reset --hard
      - git clean -xffd
      - git pull
      - build-command-debug
      - build-command-release

  - name: workspace-b
    cwd: d:\projects\workspace-b
    commands:
      - sync-command
      - build-command
```

The schema is intentionally simple: define jobs, define where they run, define the commands.

## Logging

Logging is a core feature.

The scheduler produces two types of logs:

### Session log

A high-level log for the entire run:

- scheduler start time
- configuration loaded
- job start and end
- job duration
- failures
- final summary

### Job logs

A separate log file per job:

- commands executed
- command timing
- stdout
- stderr
- exit codes

Example layout:

```text
logs/
  2026-05-04_session.log
  2026-05-04_workspace-a.log
  2026-05-04_workspace-b.log
```

## Failure handling

By default, the scheduler continues to the next job when one job fails.

This is useful for unattended runs where one failing job should not block the rest.

Failures are clearly reported:

- failed command
- exit code
- job marked as failed in summary
- full logs preserved

Behavior can be configured:

```yaml
settings:
  stop_on_failure: false
```

## Cache considerations

Many build environments use shared caches (for example compiler caches).

There is usually a trade-off:

- one shared cache gives better hit rate
- multiple caches reduce contention but reduce efficiency

Since Local Build Scheduler runs jobs sequentially, using a shared cache is often the most effective approach.

## Disk I/O considerations

Build jobs are often disk-intensive.

The scheduler executes jobs in the configured order. Users can distribute workspaces across multiple drives and order jobs accordingly.

Future versions may introduce smarter scheduling strategies.

## Environment isolation

Build environments can be sensitive to configuration details.

Common issues include:

- PATH conflicts
- multiple tool versions
- inherited environment variables

Each job runs in its own working directory and may define environment variables if needed.

Example:

```yaml
jobs:
  - name: workspace-a
    cwd: c:\projects\workspace-a
    env:
      PATH: "d:\tools;%PATH%"
    commands:
      - build-command
```

The goal is to stay generic while allowing control where needed.

## Planned features

### Version 1

- YAML configuration
- sequential execution
- per-job logs
- session log
- configurable failure behavior
- summary output

### Later improvements

- job priorities
- retry logic
- time windows (for example night execution)
- resource locks
- resume support
- dry-run mode
- prevention of multiple instances
- smarter scheduling
- notifications

## CLI Reference

The CLI entry point `lbs` supports the following subcommands and options:

### Global Options
* `--version` — Show version info and exit.
* `-h`, `--help` — Show help message and exit.

### Subcommands

#### `run`
Run all or selected jobs defined in the configuration file.
```bash
lbs run <config-path> [options]
```
**Options:**
* `-v`, `--verbose` — Mirror command execution stdout/stderr directly to standard output (in addition to the log files).
* `-j <job-name>`, `--job <job-name>` — Run only the specified job. Can be specified multiple times to execute a subset of jobs (e.g. `lbs run config.yaml -j workspace-a -j workspace-c`).

#### `validate`
Check if the provided configuration file exists, is valid YAML, and conforms to the schema.
```bash
lbs validate <config-path>
```

#### `list`
Print the names of all jobs defined in the configuration file, in order of execution (one per line).
```bash
lbs list <config-path>
```

### Exit Codes
The tool exits with explicit, predictable codes:
* `0` — Success: all scheduled jobs completed successfully.
* `1` — Job Failure: one or more jobs failed.
* `2` — Setup/Configuration Error: command argument parse failures, configuration syntax errors, or invalid job filter names.

## Design philosophy

Keep it small and predictable.

Prefer:

- simple configuration
- explicit behavior
- useful logs
- minimal dependencies

Avoid turning it into a complex CI system too early.

## Status

**Version 0.5.0** is fully implemented and ready for local development workflows. It provides robust sequential execution, session and job-level logging, flexible failure handling, configuration validation, and job filtering.

---

AI tools were used as coding assistants during development. All generated code was reviewed, tested, and integrated by the project maintainer.

---

© 2026 Silviu-Marius Ardelean. Licensed under the [Apache-2.0 License](LICENSE).
