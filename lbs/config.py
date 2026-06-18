# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.config – Configuration loader and validator.
"""

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re

import yaml


class ConfigError(Exception):
    """Exception raised when configuration loading or validation fails."""
    pass


@dataclass
class EmailConfig:
    """SMTP configuration for sending email notification reports."""
    smtp_host: str
    sender: str
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    use_tls: bool = True
    recipients: list[str] = field(default_factory=list)


@dataclass
class NotificationsConfig:
    """Configuration settings for notifications/webhooks/email."""
    on_success: bool = True
    on_failure: bool = True
    desktop: bool = False
    slack_webhook: str | None = None
    discord_webhook: str | None = None
    email: EmailConfig | None = None


@dataclass
class Settings:
    """Global scheduler settings."""
    stop_on_failure: bool = False
    log_dir: str = "logs"
    verbose: bool = False
    notifications: NotificationsConfig = field(
        default_factory=NotificationsConfig)


@dataclass
class Job:
    """A single build job specification."""
    name: str
    cwd: str
    commands: list[str]
    env: dict[str, str] = field(default_factory=dict)
    retries: int = 0
    retry_delay_seconds: int | float = 0
    command_timeout_minutes: int | float | None = None


@dataclass
class Config:
    """The root configuration object."""
    settings: Settings
    jobs: list[Job]


def _validate_job_metadata(
    job_data: dict,
    idx: int,
    seen_names: set[str],
) -> str:
    """Validates the job name and checks for duplicates, returning the name."""
    if "name" not in job_data:
        raise ConfigError(
            f"Job at index {idx} is missing the 'name' field"
        )
    name = job_data["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(
            f"Job name at index {idx} must be a non-empty string"
        )
    if name in seen_names:
        raise ConfigError(f"Duplicate job name: '{name}'")
    seen_names.add(name)
    return name


def _validate_job_cwd_and_commands(job_data: dict, name: str) -> None:
    """Validates the cwd and commands list for a job."""
    # Working Directory (CWD)
    if "cwd" not in job_data:
        raise ConfigError(f"Job '{name}' is missing 'cwd' field")
    cwd = job_data["cwd"]
    if not isinstance(cwd, str) or not cwd.strip():
        raise ConfigError(
            f"Job '{name}' 'cwd' field must be a non-empty string"
        )
    if not Path(cwd).is_dir():
        raise ConfigError(
            f"Job '{name}' 'cwd' directory does not exist: {cwd}"
        )

    # Commands list
    if "commands" not in job_data:
        raise ConfigError(f"Job '{name}' is missing 'commands' field")
    commands = job_data["commands"]
    if not isinstance(commands, list):
        raise ConfigError(f"Job '{name}' 'commands' must be a list")
    if not commands:
        raise ConfigError(f"Job '{name}' 'commands' list cannot be empty")
    for c_idx, cmd in enumerate(commands):
        if not isinstance(cmd, str) or not cmd.strip():
            raise ConfigError(
                f"Job '{name}' command at index {c_idx} must be a non-empty string"
            )


def _validate_job_options(job_data: dict, name: str) -> None:
    """Validates optional job settings like env overlays, retries, and timeouts."""
    # Environment Variables (Optional)
    if "env" in job_data:
        env = job_data["env"]
        if not isinstance(env, dict):
            raise ConfigError(
                f"Job '{name}' 'env' field must be a dictionary"
            )
        for k, v in env.items():
            if not isinstance(k, str):
                raise ConfigError(
                    f"Job '{name}' 'env' key '{k}' must be a string"
                )
            if not isinstance(v, str):
                raise ConfigError(
                    f"Job '{name}' 'env' value for '{k}' must be a string"
                )

    # Retries (Optional)
    if "retries" in job_data:
        retries = job_data["retries"]
        if (
            not isinstance(retries, int)
            or isinstance(retries, bool)
            or retries < 0
        ):
            raise ConfigError(
                f"Job '{name}' 'retries' field must be a non-negative integer"
            )

    # Retry Delay Seconds (Optional)
    if "retry_delay_seconds" in job_data:
        delay = job_data["retry_delay_seconds"]
        if (
            not isinstance(delay, (int, float))
            or isinstance(delay, bool)
            or not math.isfinite(delay)
            or delay < 0
        ):
            raise ConfigError(
                f"Job '{name}' 'retry_delay_seconds' field must be a non-negative finite number"
            )

    # Command Timeout Minutes (Optional)
    if "command_timeout_minutes" in job_data:
        timeout = job_data["command_timeout_minutes"]
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ConfigError(
                f"Job '{name}' 'command_timeout_minutes' field must be a positive finite number"
            )


def _validate_job(job_data: dict, idx: int, seen_names: set[str]) -> None:
    if not isinstance(job_data, dict):
        raise ConfigError(f"Job at index {idx} must be a dictionary")

    name = _validate_job_metadata(job_data, idx, seen_names)
    _validate_job_cwd_and_commands(job_data, name)
    _validate_job_options(job_data, name)


def _validate_email_config(email_data: dict) -> None:
    """Validates the SMTP and recipients configuration for email notifications."""
    if not isinstance(email_data, dict):
        raise ConfigError(
            "'email' notification setting must be a dictionary or null"
        )

    # Validate host
    if "smtp_host" not in email_data:
        raise ConfigError(
            "Missing 'smtp_host' in email notification configuration"
        )
    host = email_data["smtp_host"]
    if not isinstance(host, str) or not host.strip():
        raise ConfigError(
            "'smtp_host' email setting must be a non-empty string"
        )

    # Validate port
    if "smtp_port" in email_data:
        port = email_data["smtp_port"]
        if not isinstance(port, int) or isinstance(
                port, bool) or port <= 0:
            raise ConfigError(
                "'smtp_port' email setting must be a positive integer"
            )

    # Validate username and password
    for field_name in ["smtp_username", "smtp_password"]:
        if field_name in email_data:
            val = email_data[field_name]
            if val is not None and (not isinstance(val, str)
                                    or not val.strip()):
                raise ConfigError(
                    f"'{field_name}' email setting must be a string or null"
                )

    # Validate use_tls
    if "use_tls" in email_data:
        if not isinstance(email_data["use_tls"], bool):
            raise ConfigError(
                "'use_tls' email setting must be a boolean")

    # Validate sender
    if "sender" not in email_data:
        raise ConfigError(
            "Missing 'sender' in email notification configuration"
        )
    sender = email_data["sender"]
    if not isinstance(sender, str) or not sender.strip():
        raise ConfigError(
            "'sender' email setting must be a non-empty string"
        )

    # Validate recipients
    if "recipients" not in email_data:
        raise ConfigError(
            "Missing 'recipients' in email notification configuration"
        )
    recipients = email_data["recipients"]
    if not isinstance(recipients, list):
        raise ConfigError(
            "'recipients' email setting must be a list")
    if not recipients:
        raise ConfigError(
            "'recipients' email setting list cannot be empty")
    for r_idx, recipient in enumerate(recipients):
        if not isinstance(recipient,
                          str) or not recipient.strip():
            raise ConfigError(
                f"'recipients' email setting at index {r_idx} must be a non-empty string"
            )


def _validate_notifications(notif_data: dict) -> None:
    if not isinstance(notif_data, dict):
        raise ConfigError(
            "'notifications' setting must be a dictionary")

    for k in ["on_success", "on_failure", "desktop"]:
        if k in notif_data:
            if not isinstance(notif_data[k], bool):
                raise ConfigError(
                    f"'{k}' notification setting must be a boolean")

    for k in ["slack_webhook", "discord_webhook"]:
        if k in notif_data:
            val = notif_data[k]
            if val is not None:
                if not isinstance(val, str) or not val.strip():
                    raise ConfigError(
                        f"'{k}' notification setting must be a non-empty string or null"
                    )
                if not (val.startswith("http://")
                        or val.startswith("https://")):
                    raise ConfigError(
                        f"'{k}' notification setting must be a valid http/https URL"
                    )

    if "email" in notif_data:
        email_data = notif_data["email"]
        if email_data is not None:
            _validate_email_config(email_data)


def _validate_settings(settings_data: dict) -> None:
    if not isinstance(settings_data, dict):
        raise ConfigError("'settings' section must be a dictionary")

    if "stop_on_failure" in settings_data:
        if not isinstance(settings_data["stop_on_failure"], bool):
            raise ConfigError(
                "'stop_on_failure' setting must be a boolean")

    if "log_dir" in settings_data:
        log_dir = settings_data["log_dir"]
        if not isinstance(log_dir, str) or not log_dir.strip():
            raise ConfigError(
                "'log_dir' setting must be a non-empty string")

    if "verbose" in settings_data:
        if not isinstance(settings_data["verbose"], bool):
            raise ConfigError("'verbose' setting must be a boolean")

    if "notifications" in settings_data:
        _validate_notifications(settings_data["notifications"])


def _expand_env_vars(val):
    if isinstance(val, str):
        def replace(match):
            var_name = match.group(1) or match.group(2)
            return os.getenv(var_name, "")
        return re.sub(r'\$\{([^}]+)\}|\$(\w+)', replace, val)
    elif isinstance(val, dict):
        return {k: _expand_env_vars(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_expand_env_vars(x) for x in val]
    return val


def _read_and_merge_config(path: Path,
                           notifications_path: str | Path | None) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML syntax: {e}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Failed to load or parse configuration: {e}") from e

    if data is None:
        raise ConfigError("Configuration file is empty")
    elif not isinstance(data, dict):
        raise ConfigError("Configuration root must be a YAML dictionary")

    # Resolve and merge notifications
    resolved_notif_path = None
    if notifications_path is not None:
        resolved_notif_path = Path(notifications_path)
        if not resolved_notif_path.is_file():
            raise ConfigError(
                f"Notifications config file does not exist: {notifications_path}"
            )
    else:
        default_path = Path("notifications.yaml")
        if default_path.is_file():
            resolved_notif_path = default_path

    if resolved_notif_path is not None:
        try:
            with open(resolved_notif_path, "r", encoding="utf-8") as f:
                notif_payload = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid notifications YAML syntax: {e}") from e
        except (OSError, UnicodeDecodeError) as e:
            raise ConfigError(
                f"Failed to load or parse notifications configuration: {e}"
            ) from e

        if notif_payload is not None:
            if not isinstance(notif_payload, dict):
                raise ConfigError(
                    "Notifications configuration must be a YAML dictionary")

            if "notifications" in notif_payload and isinstance(
                    notif_payload["notifications"], dict):
                notif_dict = notif_payload["notifications"]
            else:
                notif_dict = notif_payload

            # Safely merge
            if "settings" not in data or data["settings"] is None:
                data["settings"] = {}
            if not isinstance(data["settings"], dict):
                raise ConfigError("'settings' section must be a dictionary")

            if "notifications" not in data["settings"] or data["settings"][
                    "notifications"] is None:
                data["settings"]["notifications"] = {}
            elif not isinstance(data["settings"]["notifications"], dict):
                raise ConfigError(
                    "'notifications' setting must be a dictionary")

            data["settings"]["notifications"].update(notif_dict)

    return _expand_env_vars(data)


def validate_config(path: str | Path,
                    notifications_path: str | Path | None = None) -> None:
    """
    Validate that the config file at path exists, is valid YAML, and meets LBS constraints.
    
    Raises:
        ConfigError: If any validation rule is violated.
    """
    config_path = Path(path)

    if not config_path.is_file():
        raise ConfigError(f"Config file does not exist: {config_path}")

    data = _read_and_merge_config(config_path, notifications_path)

    # Jobs must be present
    if "jobs" not in data:
        raise ConfigError("Configuration is missing 'jobs' section")

    jobs_data = data["jobs"]
    if not isinstance(jobs_data, list):
        raise ConfigError("'jobs' section must be a list")
    if not jobs_data:
        raise ConfigError("'jobs' list cannot be empty")

    # Validate each job
    seen_names = set()
    for idx, job_data in enumerate(jobs_data):
        _validate_job(job_data, idx, seen_names)

    # Validate Settings (Optional)
    if "settings" in data:
        _validate_settings(data["settings"])


def load_config(path: str | Path,
                notifications_path: str | Path | None = None) -> Config:
    """
    Load and parse config from path, applying default values where applicable.
    
    Raises:
        ConfigError: If validation fails.
    """
    config_path = Path(path)
    validate_config(config_path, notifications_path=notifications_path)

    data = _read_and_merge_config(config_path, notifications_path)

    # Apply settings defaults (in case 'settings' or individual settings keys are omitted)
    settings_dict = data.get("settings")
    if settings_dict is None:
        settings_dict = {}

    notif_dict = settings_dict.get("notifications")
    if notif_dict is None:
        notif_dict = {}

    email_dict = notif_dict.get("email")
    email_config = None
    if email_dict is not None:
        email_config = EmailConfig(
            smtp_host=email_dict["smtp_host"],
            smtp_port=email_dict.get("smtp_port", 587),
            smtp_username=email_dict.get("smtp_username", None),
            smtp_password=email_dict.get("smtp_password", None),
            use_tls=email_dict.get("use_tls", True),
            sender=email_dict["sender"],
            recipients=list(email_dict["recipients"]))

    notifications = NotificationsConfig(
        on_success=notif_dict.get("on_success", True),
        on_failure=notif_dict.get("on_failure", True),
        desktop=notif_dict.get("desktop", False),
        slack_webhook=notif_dict.get("slack_webhook", None),
        discord_webhook=notif_dict.get("discord_webhook", None),
        email=email_config)

    settings = Settings(stop_on_failure=settings_dict.get(
        "stop_on_failure", False),
                        log_dir=settings_dict.get("log_dir", "logs"),
                        verbose=settings_dict.get("verbose", False),
                        notifications=notifications)

    # Construct Job dataclasses
    jobs = []
    for job_data in data["jobs"]:
        jobs.append(
            Job(name=job_data["name"],
                cwd=job_data["cwd"],
                commands=list(job_data["commands"]),
                env=dict(job_data.get("env", {})),
                retries=job_data.get("retries", 0),
                retry_delay_seconds=job_data.get("retry_delay_seconds", 0),
                command_timeout_minutes=job_data.get("command_timeout_minutes",
                                                     None)))

    return Config(settings=settings, jobs=jobs)
