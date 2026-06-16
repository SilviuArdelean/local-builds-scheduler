# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for the configuration module (loading and validation).
"""

from pathlib import Path
import pytest
from lbs.config import load_config, validate_config, ConfigError


def test_valid_config_loading(tmp_path):
    """A valid YAML config should load and construct the dataclasses with correct types."""
    config_file = tmp_path / "valid_config.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    yaml_content = f"""
    settings:
      stop_on_failure: true
      log_dir: "custom_logs"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands:
          - "echo 'hello'"
        env:
          KEY: "value"
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    config = load_config(config_file)
    assert config.settings.stop_on_failure is True
    assert config.settings.log_dir == "custom_logs"
    assert len(config.jobs) == 1
    assert config.jobs[0].name == "job-1"
    assert Path(config.jobs[0].cwd) == workspace_dir
    assert config.jobs[0].commands == ["echo 'hello'"]
    assert config.jobs[0].env == {"KEY": "value"}


def test_valid_config_defaults(tmp_path):
    """Optional sections (settings, env) should apply default values automatically."""
    config_file = tmp_path / "defaults_config.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    yaml_content = f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands:
          - "echo 'hello'"
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    config = load_config(config_file)
    # Defaults should be applied
    assert config.settings.stop_on_failure is False
    assert config.settings.log_dir == "logs"
    assert config.jobs[0].env == {}


def test_non_existent_config_file():
    """Validating or loading a non-existent file should raise ConfigError."""
    with pytest.raises(ConfigError) as exc:
        load_config("does_not_exist_at_all.yaml")
    assert "Config file does not exist" in str(exc.value)


def test_invalid_yaml_syntax(tmp_path):
    """Syntactically malformed YAML should raise ConfigError."""
    config_file = tmp_path / "bad_syntax.yaml"
    config_file.write_text("jobs: [name: {unclosed_brace", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "Invalid YAML syntax" in str(exc.value)


def test_empty_config_file(tmp_path):
    """An empty configuration file should raise ConfigError."""
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "Configuration file is empty" in str(exc.value)


def test_missing_jobs_section(tmp_path):
    """Config missing the 'jobs' section should raise ConfigError."""
    config_file = tmp_path / "no_jobs.yaml"
    config_file.write_text("settings: {stop_on_failure: true}",
                           encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "Configuration is missing 'jobs' section" in str(exc.value)


def test_duplicate_job_names(tmp_path):
    """Job names must be unique. Duplicates should raise ConfigError."""
    config_file = tmp_path / "duplicate_jobs.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    yaml_content = f"""
    jobs:
      - name: build-job
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
      - name: build-job
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 2"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "Duplicate job name: 'build-job'" in str(exc.value)


def test_cwd_directory_must_exist(tmp_path):
    """A non-existent working directory (cwd) should raise ConfigError."""
    config_file = tmp_path / "missing_cwd.yaml"
    non_existent_path = tmp_path / "does_not_exist_folder"

    yaml_content = f"""
    jobs:
      - name: bad-cwd-job
        cwd: "{non_existent_path.as_posix()}"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "cwd' directory does not exist" in str(exc.value)


def test_empty_commands_list(tmp_path):
    """An empty commands list should raise ConfigError."""
    config_file = tmp_path / "empty_commands.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    yaml_content = f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: []
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "commands' list cannot be empty" in str(exc.value)


def test_env_non_string_values(tmp_path):
    """Environment variable values that are parsed as non-strings should raise ConfigError."""
    config_file = tmp_path / "bad_env_value.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    # YAML parses 8080 as int, not str
    yaml_content = f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        env:
          PORT: 8080
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file)
    assert "env' value for 'PORT' must be a string" in str(exc.value)


def test_config_retries_validation(tmp_path):
    """Verify that retries and retry_delay_seconds are validated properly."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    
    # 1. Negative retries should fail
    config_file1 = tmp_path / "bad_retries.yaml"
    config_file1.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retries: -1
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file1)
    assert "retries' field must be a non-negative integer" in str(exc.value)

    # 2. Non-integer retries (e.g. float) should fail
    config_file2 = tmp_path / "bad_retries_float.yaml"
    config_file2.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retries: 2.5
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file2)
    assert "retries' field must be a non-negative integer" in str(exc.value)

    # 3. Boolean retries (e.g. true) should fail
    config_file3 = tmp_path / "bad_retries_bool.yaml"
    config_file3.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retries: true
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3)
    assert "retries' field must be a non-negative integer" in str(exc.value)

    # 4. Negative retry_delay_seconds should fail
    config_file4 = tmp_path / "bad_delay.yaml"
    config_file4.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retry_delay_seconds: -10
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file4)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(exc.value)

    # 5. Boolean retry_delay_seconds should fail
    config_file5 = tmp_path / "bad_delay_bool.yaml"
    config_file5.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retry_delay_seconds: false
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file5)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(exc.value)

    # 5b. Infinite retry_delay_seconds should fail
    config_file5b = tmp_path / "bad_delay_inf.yaml"
    config_file5b.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retry_delay_seconds: .inf
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file5b)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(exc.value)

    # 5c. NaN retry_delay_seconds should fail
    config_file5c = tmp_path / "bad_delay_nan.yaml"
    config_file5c.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retry_delay_seconds: .nan
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file5c)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(exc.value)

    # 6. Valid float and integer parameters should load successfully
    config_file6 = tmp_path / "good_retries.yaml"
    config_file6.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retries: 3
        retry_delay_seconds: 1.5
    """, encoding="utf-8")
    config = load_config(config_file6)
    assert config.jobs[0].retries == 3
    assert config.jobs[0].retry_delay_seconds == 1.5


def test_config_timeout_validation(tmp_path):
    """Verify that command_timeout_minutes is validated properly."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    # 1. Negative timeout should fail
    config_file1 = tmp_path / "bad_timeout.yaml"
    config_file1.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: -10
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file1)
    assert "command_timeout_minutes' field must be a positive finite number" in str(exc.value)

    # 2. Zero timeout should fail
    config_file2 = tmp_path / "zero_timeout.yaml"
    config_file2.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: 0
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file2)
    assert "command_timeout_minutes' field must be a positive finite number" in str(exc.value)

    # 3. Boolean timeout should fail
    config_file3 = tmp_path / "bool_timeout.yaml"
    config_file3.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: true
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3)
    assert "command_timeout_minutes' field must be a positive finite number" in str(exc.value)

    # 3b. Infinite timeout should fail
    config_file3b = tmp_path / "bad_timeout_inf.yaml"
    config_file3b.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: .inf
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3b)
    assert "command_timeout_minutes' field must be a positive finite number" in str(exc.value)

    # 3c. NaN timeout should fail
    config_file3c = tmp_path / "bad_timeout_nan.yaml"
    config_file3c.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: .nan
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3c)
    assert "command_timeout_minutes' field must be a positive finite number" in str(exc.value)

    # 4. Valid timeout should load successfully
    config_file4 = tmp_path / "good_timeout.yaml"
    config_file4.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: 2.5
    """, encoding="utf-8")
    config = load_config(config_file4)
    assert config.jobs[0].command_timeout_minutes == 2.5
