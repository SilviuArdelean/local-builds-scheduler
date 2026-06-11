# Local Builds Scheduler
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
