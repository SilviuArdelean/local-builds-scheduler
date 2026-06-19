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
    """,
                            encoding="utf-8")
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
    """,
                            encoding="utf-8")
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
    """,
                            encoding="utf-8")
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
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file4)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(
        exc.value)

    # 5. Boolean retry_delay_seconds should fail
    config_file5 = tmp_path / "bad_delay_bool.yaml"
    config_file5.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retry_delay_seconds: false
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file5)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(
        exc.value)

    # 5b. Infinite retry_delay_seconds should fail
    config_file5b = tmp_path / "bad_delay_inf.yaml"
    config_file5b.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retry_delay_seconds: .inf
    """,
                             encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file5b)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(
        exc.value)

    # 5c. NaN retry_delay_seconds should fail
    config_file5c = tmp_path / "bad_delay_nan.yaml"
    config_file5c.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retry_delay_seconds: .nan
    """,
                             encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file5c)
    assert "retry_delay_seconds' field must be a non-negative finite number" in str(
        exc.value)

    # 6. Valid float and integer parameters should load successfully
    config_file6 = tmp_path / "good_retries.yaml"
    config_file6.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        retries: 3
        retry_delay_seconds: 1.5
    """,
                            encoding="utf-8")
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
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file1)
    assert "command_timeout_minutes' field must be a positive finite number" in str(
        exc.value)

    # 2. Zero timeout should fail
    config_file2 = tmp_path / "zero_timeout.yaml"
    config_file2.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: 0
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file2)
    assert "command_timeout_minutes' field must be a positive finite number" in str(
        exc.value)

    # 3. Boolean timeout should fail
    config_file3 = tmp_path / "bool_timeout.yaml"
    config_file3.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: true
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3)
    assert "command_timeout_minutes' field must be a positive finite number" in str(
        exc.value)

    # 3b. Infinite timeout should fail
    config_file3b = tmp_path / "bad_timeout_inf.yaml"
    config_file3b.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: .inf
    """,
                             encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3b)
    assert "command_timeout_minutes' field must be a positive finite number" in str(
        exc.value)

    # 3c. NaN timeout should fail
    config_file3c = tmp_path / "bad_timeout_nan.yaml"
    config_file3c.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: .nan
    """,
                             encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3c)
    assert "command_timeout_minutes' field must be a positive finite number" in str(
        exc.value)

    # 4. Valid timeout should load successfully
    config_file4 = tmp_path / "good_timeout.yaml"
    config_file4.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        command_timeout_minutes: 2.5
    """,
                            encoding="utf-8")
    config = load_config(config_file4)
    assert config.jobs[0].command_timeout_minutes == 2.5


def test_config_notifications_validation(tmp_path):
    """Verify that notification configuration options are parsed and validated properly."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    # 1. Valid notifications load
    config_file1 = tmp_path / "good_notif.yaml"
    config_file1.write_text(f"""
    settings:
      notifications:
        on_success: false
        desktop: true
        slack_webhook: "https://hooks.slack.com/services/123"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """,
                            encoding="utf-8")
    config = load_config(config_file1)
    notif = config.settings.notifications
    assert notif.on_success is False
    assert notif.on_failure is True  # Default
    assert notif.desktop is True
    assert notif.slack_webhook == "https://hooks.slack.com/services/123"
    assert notif.discord_webhook is None

    # 2. Invalid webhook type should fail
    config_file2 = tmp_path / "bad_webhook_type.yaml"
    config_file2.write_text(f"""
    settings:
      notifications:
        slack_webhook: 12345
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file2)
    assert "slack_webhook' notification setting must be a non-empty string or null" in str(
        exc.value)

    # 3. Invalid webhook URL scheme should fail
    config_file3 = tmp_path / "bad_webhook_scheme.yaml"
    config_file3.write_text(f"""
    settings:
      notifications:
        discord_webhook: "ftp://discord.com/api"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file3)
    assert "discord_webhook' notification setting must be a valid http/https URL" in str(
        exc.value)

    # 4. Invalid boolean setting should fail
    config_file4 = tmp_path / "bad_notif_bool.yaml"
    config_file4.write_text(f"""
    settings:
      notifications:
        on_failure: "yes"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """,
                            encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file4)
    assert "on_failure' notification setting must be a boolean" in str(
        exc.value)


def test_config_notifications_merge_override(tmp_path):
    """Verify that values in a separate notifications file override/merge settings from the main config."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_file = tmp_path / "main_config.yaml"
    config_file.write_text(f"""
    settings:
      notifications:
        on_success: false
        desktop: false
        slack_webhook: "https://hooks.slack.com/services/original"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """, encoding="utf-8")

    notif_file = tmp_path / "notif_override.yaml"
    notif_file.write_text("""
    on_success: true
    desktop: true
    slack_webhook: "https://hooks.slack.com/services/overridden"
    email:
      smtp_host: "smtp.example.com"
      sender: "sender@example.com"
      recipients: ["user@example.com"]
    """, encoding="utf-8")

    config = load_config(config_file, notifications_path=notif_file)
    notif = config.settings.notifications
    assert notif.on_success is True
    assert notif.on_failure is True  # preserved default
    assert notif.desktop is True
    assert notif.slack_webhook == "https://hooks.slack.com/services/overridden"
    assert notif.email.smtp_host == "smtp.example.com"
    assert notif.email.sender == "sender@example.com"
    assert notif.email.recipients == ["user@example.com"]


def test_config_notifications_merge_wrapped(tmp_path):
    """Verify that notifications config with a root 'notifications' key is merged correctly."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_file = tmp_path / "main_config.yaml"
    config_file.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """, encoding="utf-8")

    notif_file = tmp_path / "notif_wrapped.yaml"
    notif_file.write_text("""
    notifications:
      desktop: true
      slack_webhook: "https://hooks.slack.com/services/wrapped"
    """, encoding="utf-8")

    config = load_config(config_file, notifications_path=notif_file)
    notif = config.settings.notifications
    assert notif.desktop is True
    assert notif.slack_webhook == "https://hooks.slack.com/services/wrapped"


def test_config_notifications_default_cwd(tmp_path, monkeypatch):
    """Verify that default notifications.yaml in CWD is automatically loaded and merged."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    # Move working directory to tmp_path
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / "main_config.yaml"
    config_file.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """, encoding="utf-8")

    default_notif_file = tmp_path / "notifications.yaml"
    default_notif_file.write_text("""
    desktop: true
    """, encoding="utf-8")

    config = load_config(config_file)
    assert config.settings.notifications.desktop is True


def test_config_notifications_missing_file(tmp_path):
    """Verify that a non-existent explicit notifications file path raises ConfigError."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_file = tmp_path / "main_config.yaml"
    config_file.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """, encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(
            config_file,
            notifications_path=tmp_path / "non_existent_notif.yaml",
        )
    assert "Notifications config file does not exist" in str(exc.value)


def test_config_notifications_malformed_yaml(tmp_path):
    """Verify that a malformed notifications YAML file raises ConfigError."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_file = tmp_path / "main_config.yaml"
    config_file.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """, encoding="utf-8")

    notif_file = tmp_path / "malformed.yaml"
    notif_file.write_text("invalid_key: [unclosed_brace", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file, notifications_path=notif_file)
    assert "Invalid notifications YAML syntax" in str(exc.value)


def test_config_notifications_not_a_dict(tmp_path):
    """Verify that a notifications file that is not a dictionary raises ConfigError."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_file = tmp_path / "main_config.yaml"
    config_file.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """, encoding="utf-8")

    notif_file = tmp_path / "not_dict.yaml"
    notif_file.write_text("- list_item", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(config_file, notifications_path=notif_file)
    assert "Notifications configuration must be a YAML dictionary" in str(exc.value)


def test_config_env_var_interpolation(tmp_path, monkeypatch):
    """Verify that environment variables referenced via ${VAR} or $VAR are interpolated in the config."""
    monkeypatch.setenv("TEST_LBS_LOG_DIR", "env_logs")
    monkeypatch.setenv("TEST_LBS_WEBHOOK", "https://hooks.slack.com/services/env")

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_file = tmp_path / "env_config.yaml"
    config_file.write_text(f"""
    settings:
      log_dir: "${{TEST_LBS_LOG_DIR}}"
      notifications:
        slack_webhook: "$TEST_LBS_WEBHOOK"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """, encoding="utf-8")

    config = load_config(config_file)
    assert config.settings.log_dir == "env_logs"
    assert config.settings.notifications.slack_webhook == "https://hooks.slack.com/services/env"


def test_config_build_it_validation(tmp_path):
    """Verify that the job build_it field is validated properly."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    # 1. build_it explicitly set to True
    config_file1 = tmp_path / "build_it_true.yaml"
    config_file1.write_text(f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
        build_it: true
    """, encoding="utf-8")
    config1 = load_config(config_file1)
    assert config1.jobs[0].build_it is True

    # 2. build_it explicitly set to False
    config_file2 = tmp_path / "build_it_false.yaml"
    config_file2.write_text(f"""
    jobs:
      - name: job-2
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 2"]
        build_it: false
    """, encoding="utf-8")
    config2 = load_config(config_file2)
    assert config2.jobs[0].build_it is False

    # 3. build_it not specified (defaults to True)
    config_file3 = tmp_path / "build_it_default.yaml"
    config_file3.write_text(f"""
    jobs:
      - name: job-3
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 3"]
    """, encoding="utf-8")
    config3 = load_config(config_file3)
    assert config3.jobs[0].build_it is True

    # 4. build_it with non-boolean should raise ConfigError
    config_file4 = tmp_path / "build_it_invalid.yaml"
    config_file4.write_text(f"""
    jobs:
      - name: job-4
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 4"]
        build_it: "yes"
    """, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_file4)
    assert "build_it' field must be a boolean" in str(exc.value)

