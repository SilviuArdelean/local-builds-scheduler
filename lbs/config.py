# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.config – Configuration loader and validator.
"""

from dataclasses import dataclass, field
from pathlib import Path
import yaml


class ConfigError(Exception):
    """Exception raised when configuration loading or validation fails."""
    pass


@dataclass
class Settings:
    """Global scheduler settings."""
    stop_on_failure: bool = False
    log_dir: str = "logs"
    verbose: bool = False



@dataclass
class Job:
    """A single build job specification."""
    name: str
    cwd: str
    commands: list[str]
    env: dict[str, str] = field(default_factory=dict)
    retries: int = 0
    retry_delay_seconds: int | float = 0


@dataclass
class Config:
    """The root configuration object."""
    settings: Settings
    jobs: list[Job]


def validate_config(path: str | Path) -> None:
    """
    Validate that the config file at path exists, is valid YAML, and meets LBS constraints.
    
    Raises:
        ConfigError: If any validation rule is violated.
    """
    config_path = Path(path)

    if not config_path.is_file():
        raise ConfigError(f"Config file does not exist: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML syntax: {e}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Failed to load or parse configuration: {e}") from e

    # Top-level must be a dictionary
    if data is None:
        raise ConfigError("Configuration file is empty")
    if not isinstance(data, dict):
        raise ConfigError("Configuration root must be a YAML dictionary")

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
        if not isinstance(job_data, dict):
            raise ConfigError(f"Job at index {idx} must be a dictionary")

        if "name" not in job_data:
            raise ConfigError(
                f"Job at index {idx} is missing the 'name' field")
        name = job_data["name"]
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(
                f"Job name at index {idx} must be a non-empty string")
        if name in seen_names:
            raise ConfigError(f"Duplicate job name: '{name}'")
        seen_names.add(name)

        # Working Directory (CWD)
        if "cwd" not in job_data:
            raise ConfigError(f"Job '{name}' is missing 'cwd' field")
        cwd = job_data["cwd"]
        if not isinstance(cwd, str) or not cwd.strip():
            raise ConfigError(
                f"Job '{name}' 'cwd' field must be a non-empty string")
        if not Path(cwd).is_dir():
            raise ConfigError(
                f"Job '{name}' 'cwd' directory does not exist: {cwd}")

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

        # Environment Variables (Optional)
        if "env" in job_data:
            env = job_data["env"]
            if not isinstance(env, dict):
                raise ConfigError(
                    f"Job '{name}' 'env' field must be a dictionary")
            for k, v in env.items():
                if not isinstance(k, str):
                    raise ConfigError(
                        f"Job '{name}' 'env' key '{k}' must be a string")
                if not isinstance(v, str):
                    raise ConfigError(
                        f"Job '{name}' 'env' value for '{k}' must be a string")

        # Retries (Optional)
        if "retries" in job_data:
            retries = job_data["retries"]
            if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
                raise ConfigError(
                    f"Job '{name}' 'retries' field must be a non-negative integer"
                )

        # Retry Delay Seconds (Optional)
        if "retry_delay_seconds" in job_data:
            delay = job_data["retry_delay_seconds"]
            if not isinstance(delay, (int, float)) or isinstance(delay, bool) or delay < 0:
                raise ConfigError(
                    f"Job '{name}' 'retry_delay_seconds' field must be a non-negative number"
                )

    # Validate Settings (Optional)
    if "settings" in data:
        settings_data = data["settings"]
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
                raise ConfigError(
                    "'verbose' setting must be a boolean")



def load_config(path: str | Path) -> Config:
    """
    Load and parse config from path, applying default values where applicable.
    
    Raises:
        ConfigError: If validation fails.
    """
    config_path = Path(path)
    validate_config(config_path)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML syntax: {e}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Failed to load or parse configuration: {e}") from e

    # Apply settings defaults (in case 'settings' or individual settings keys are omitted)
    settings_dict = data.get("settings")
    if settings_dict is None:
        settings_dict = {}

    settings = Settings(
        stop_on_failure=settings_dict.get("stop_on_failure", False),
        log_dir=settings_dict.get("log_dir", "logs"),
        verbose=settings_dict.get("verbose", False)
    )


    # Construct Job dataclasses
    jobs = []
    for job_data in data["jobs"]:
        jobs.append(
            Job(name=job_data["name"],
                cwd=job_data["cwd"],
                commands=list(job_data["commands"]),
                env=dict(job_data.get("env", {})),
                retries=job_data.get("retries", 0),
                retry_delay_seconds=job_data.get("retry_delay_seconds", 0)))

    return Config(settings=settings, jobs=jobs)
