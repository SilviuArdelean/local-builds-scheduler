# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for the notifications engine.
"""

import json
import urllib.request
from unittest.mock import patch, MagicMock

from lbs.config import Config, Settings, Job, NotificationsConfig
from lbs.runner import Scheduler


@patch("urllib.request.urlopen")
def test_send_slack_webhook(mock_urlopen):
    """Verify that Slack webhook constructs and POSTs the correct JSON payload."""
    from lbs.utils.notifier import send_slack_webhook

    mock_response = MagicMock()
    mock_urlopen.return_value.__enter__.return_value = mock_response

    webhook_url = "https://hooks.slack.com/services/test-slack"
    send_slack_webhook(webhook_url, "Build Title", "Build Message text")

    # Assert urlopen was called
    assert mock_urlopen.call_count == 1
    args, _ = mock_urlopen.call_args
    req = args[0]

    # Verify request details
    assert isinstance(req, urllib.request.Request)
    assert req.full_url == webhook_url
    assert req.headers["Content-type"] == "application/json"

    # Verify JSON content
    data = json.loads(req.data.decode("utf-8"))
    assert data == {"text": "*Build Title*\nBuild Message text"}


@patch("urllib.request.urlopen")
def test_send_discord_webhook(mock_urlopen):
    """Verify that Discord webhook constructs and POSTs the correct JSON payload."""
    from lbs.utils.notifier import send_discord_webhook

    mock_response = MagicMock()
    mock_urlopen.return_value.__enter__.return_value = mock_response

    webhook_url = "https://discord.com/api/webhooks/test-discord"
    send_discord_webhook(webhook_url, "Build Title", "Build Message text")

    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    assert isinstance(req, urllib.request.Request)
    assert req.full_url == webhook_url

    data = json.loads(req.data.decode("utf-8"))
    assert data == {"content": "**Build Title**\nBuild Message text"}


@patch("sys.platform", "win32")
@patch("subprocess.run")
def test_send_desktop_notification_win32(mock_sub_run):
    """Verify that desktop notification triggers PowerShell on Windows."""
    from lbs.utils.notifier import send_desktop_notification

    send_desktop_notification("Job Alert", "Everything is done!")

    assert mock_sub_run.call_count == 1
    args, _ = mock_sub_run.call_args
    cmd_args = args[0]

    assert cmd_args[0] == "powershell"
    assert "-Command" in cmd_args

    # Check that script contains our title and message
    script = cmd_args[-1]
    assert "Job Alert" in script
    assert "Everything is done!" in script


@patch("sys.platform", "darwin")
@patch("subprocess.run")
def test_send_desktop_notification_non_win32(mock_sub_run):
    """Verify that desktop notification is skipped on non-Windows platforms."""
    from lbs.utils.notifier import send_desktop_notification

    send_desktop_notification("Alert", "Skip me")

    assert mock_sub_run.call_count == 0


@patch("urllib.request.urlopen")
def test_dispatch_notifications_on_success(mock_urlopen, tmp_path):
    """Verify Scheduler.run triggers webhook on success if configured."""
    log_dir = tmp_path / "logs"
    settings = Settings(
        log_dir=str(log_dir),
        notifications=NotificationsConfig(
            on_success=True,
            slack_webhook="https://hooks.slack.com/services/abc"))
    jobs = [Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"])]
    config = Config(settings=settings, jobs=jobs)

    success = Scheduler.run(config)
    assert success is True

    # Webhook should have been called
    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    data = json.loads(req.data.decode("utf-8"))
    assert "SUCCESS" in data["text"]


@patch("urllib.request.urlopen")
def test_dispatch_notifications_skip_on_success(mock_urlopen, tmp_path):
    """Verify Scheduler.run skips webhook on success if on_success is False."""
    log_dir = tmp_path / "logs"
    settings = Settings(
        log_dir=str(log_dir),
        notifications=NotificationsConfig(
            on_success=False,
            slack_webhook="https://hooks.slack.com/services/abc"))
    jobs = [Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"])]
    config = Config(settings=settings, jobs=jobs)

    success = Scheduler.run(config)
    assert success is True

    # Webhook should NOT have been called
    assert mock_urlopen.call_count == 0


@patch("smtplib.SMTP")
def test_send_email_notification_starttls(mock_smtp):
    """Verify that send_email_notification connects via SMTP and issues starttls/login/sendmail."""
    from lbs.utils.notifier import send_email_notification
    from lbs.config import EmailConfig

    mock_server = MagicMock()
    mock_smtp.return_value = mock_server

    email_config = EmailConfig(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username="user@gmail.com",
        smtp_password="app-password",
        use_tls=True,
        sender="lbs-scheduler@builds.local",
        recipients=["user@gmail.com", "other@gmail.com"])

    send_email_notification(email_config, "Subject Line", "Email Body message")

    # Verify SMTP server was instantiated on correct host/port
    mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)

    # Verify connection logic
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user@gmail.com", "app-password")

    # Verify mail sending
    assert mock_server.sendmail.call_count == 1
    sender, recipients, msg_str = mock_server.sendmail.call_args[0]
    assert sender == "lbs-scheduler@builds.local"
    assert recipients == ["user@gmail.com", "other@gmail.com"]
    assert "Subject: Subject Line" in msg_str
    assert "Email Body message" in msg_str
    mock_server.quit.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_send_email_notification_ssl(mock_smtp_ssl):
    """Verify that send_email_notification connects via SMTP_SSL for port 465."""
    from lbs.utils.notifier import send_email_notification
    from lbs.config import EmailConfig

    mock_server = MagicMock()
    mock_smtp_ssl.return_value = mock_server

    email_config = EmailConfig(smtp_host="smtp.gmail.com",
                               smtp_port=465,
                               smtp_username="user@gmail.com",
                               smtp_password="app-password",
                               use_tls=False,
                               sender="lbs-scheduler@builds.local",
                               recipients=["user@gmail.com"])

    send_email_notification(email_config, "Subject Line", "Email Body message")

    # Verify SMTP_SSL was instantiated
    mock_smtp_ssl.assert_called_once_with("smtp.gmail.com", 465, timeout=10)

    # starttls should not be called for SMTP_SSL
    mock_server.starttls.assert_not_called()
    mock_server.login.assert_called_once_with("user@gmail.com", "app-password")
    mock_server.sendmail.assert_called_once()
    mock_server.quit.assert_called_once()


@patch("urllib.request.urlopen")
def test_scheduler_run_with_separate_notifications_config(
        mock_urlopen, tmp_path):
    """Verify Scheduler.run utilizes merged settings from a separate notifications file."""
    from lbs.config import load_config

    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"""
    settings:
      log_dir: "{log_dir.as_posix()}"
      notifications:
        on_success: false
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """,
                           encoding="utf-8")

    notif_file = tmp_path / "notifications_private.yaml"
    notif_file.write_text("""
    on_success: true
    slack_webhook: "https://hooks.slack.com/services/from-private-file"
    """,
                          encoding="utf-8")

    # Load config with overrides
    config = load_config(config_file, notifications_path=notif_file)

    success = Scheduler.run(config)
    assert success is True

    # Webhook should have been called because it was overridden to True in the private file
    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "https://hooks.slack.com/services/from-private-file"


def test_no_notifications_flag_disables_triggers():
    """Verify that when no-notifications behavior is enforced (triggers are False), notifications are bypassed."""
    from lbs.utils.notifier import dispatch_notifications

    # Create mock settings where notifications is configured, but on_success/on_failure is False
    mock_settings = MagicMock()
    mock_settings.notifications.on_success = False
    mock_settings.notifications.on_failure = False
    mock_settings.notifications.slack_webhook = "https://hooks.slack.com/services/test"

    with patch("urllib.request.urlopen") as mock_urlopen:
        dispatch_notifications(settings=mock_settings,
                               success=True,
                               passed_count=1,
                               failed_count=0,
                               skipped_count=0,
                               duration_str="00:00:05",
                               job_summaries={})
        assert mock_urlopen.call_count == 0


def test_dispatch_notifications_aborted_session():
    """Verify notification payload structure for an aborted session."""
    from lbs.utils.notifier import dispatch_notifications

    mock_settings = MagicMock()
    mock_settings.notifications.on_success = True
    mock_settings.notifications.on_failure = True
    mock_settings.notifications.slack_webhook = "https://hooks.slack.com/services/test"

    job_summaries = {
        "chromium-debug": {"status": "FAILED", "duration": 2521.0},
        "package-artifacts": {"status": "ABORTED"},
        "upload-symbols": {"status": "DISABLED"},
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        dispatch_notifications(
            settings=mock_settings,
            success=False,
            passed_count=1,
            failed_count=1,
            skipped_count=2,
            duration_str="00:42:01",
            job_summaries=job_summaries,
            interrupted=False,
            aborted_jobs=["package-artifacts (aborted)", "upload-symbols (disabled)"],
            resume_cmd="lbs run configs/chromium.yaml --resume latest",
        )
        assert mock_urlopen.call_count == 1
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode("utf-8"))
        text = data["text"]

        assert "*LBS Session Completed: FAILED*" in text
        assert "Status: FAILED (Aborted after 1 failure)" in text
        assert "Passed: 1 | Failed: 1 | Aborted: 2" in text
        assert "Duration: 00:42:01" in text
        assert "Failed Jobs:\n• chromium-debug (failed in 00:42:01)" in text
        assert "Aborted / Skipped:\n• package-artifacts (aborted)\n• upload-symbols (disabled)" in text
        assert "Resume command:\n  lbs run configs/chromium.yaml --resume latest" in text


def test_dispatch_notifications_interrupted_session():
    """Verify notification payload structure for a session interrupted by Ctrl+C."""
    from lbs.utils.notifier import dispatch_notifications

    mock_settings = MagicMock()
    mock_settings.notifications.on_success = True
    mock_settings.notifications.on_failure = True
    mock_settings.notifications.slack_webhook = "https://hooks.slack.com/services/test"

    job_summaries = {
        "job-1": {"status": "SUCCESS", "duration": 10.0},
        "job-2": {"status": "INTERRUPTED", "duration": 5.0},
        "job-3": {"status": "ABORTED"},
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        dispatch_notifications(
            settings=mock_settings,
            success=False,
            passed_count=1,
            failed_count=1,
            skipped_count=1,
            duration_str="00:00:15",
            job_summaries=job_summaries,
            interrupted=True,
            aborted_jobs=["job-3 (aborted)"],
            resume_cmd="lbs run configs/test.yaml --resume latest",
        )
        assert mock_urlopen.call_count == 1
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode("utf-8"))
        text = data["text"]

        assert "*LBS Session Interrupted: CANCELLED*" in text
        assert "Status: CANCELLED (Interrupted by user)" in text
        assert "Passed: 1 | Failed: 1 | Aborted: 1" in text
        assert "Duration: 00:00:15" in text
        assert "Failed Jobs:\n• job-2 (failed in 00:00:05)" in text
        assert "Aborted / Skipped:\n• job-3 (aborted)" in text
        assert "Resume command:\n  lbs run configs/test.yaml --resume latest" in text


@patch("urllib.request.urlopen")
def test_scheduler_run_triggers_notification_on_keyboard_interrupt(mock_urlopen, tmp_path):
    """Verify that Scheduler.run dispatches notification upon KeyboardInterrupt."""
    import pytest

    log_dir = tmp_path / "logs"
    settings = Settings(
        log_dir=str(log_dir),
        notifications=NotificationsConfig(
            on_failure=True,
            slack_webhook="https://hooks.slack.com/services/on-interrupt",
        ),
    )
    jobs = [
        Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"]),
        Job(name="job-2", cwd=str(tmp_path), commands=["echo 2"]),
    ]
    config = Config(settings=settings, jobs=jobs)

    with patch("lbs.runner._execute_phase_run", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            Scheduler.run(config, config_path=tmp_path / "test.yaml")

    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    data = json.loads(req.data.decode("utf-8"))
    assert "*LBS Session Interrupted: CANCELLED*" in data["text"]
    assert "Status: CANCELLED" in data["text"]
    assert "Resume command:" in data["text"]


@patch("urllib.request.urlopen")
def test_scheduler_run_triggers_notification_on_stop_on_failure_abort(mock_urlopen, tmp_path):
    """Verify that Scheduler.run dispatches abort breakdown when stop_on_failure halts execution."""
    log_dir = tmp_path / "logs"
    settings = Settings(
        stop_on_failure=True,
        log_dir=str(log_dir),
        notifications=NotificationsConfig(
            on_failure=True,
            slack_webhook="https://hooks.slack.com/services/on-abort",
        ),
    )
    # job-1 fails, job-2 should be aborted
    jobs = [
        Job(name="job-fail", cwd=str(tmp_path), commands=['python -c "import sys; sys.exit(1)"']),
        Job(name="job-aborted", cwd=str(tmp_path), commands=["echo hello"]),
    ]
    config = Config(settings=settings, jobs=jobs)

    success = Scheduler.run(config, config_path=tmp_path / "test.yaml")
    assert success is False

    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    data = json.loads(req.data.decode("utf-8"))
    text = data["text"]

    assert "*LBS Session Completed: FAILED*" in text
    assert "Status: FAILED (Aborted after 1 failure)" in text
    assert "Passed: 0 | Failed: 1 | Aborted: 1" in text
    assert "Failed Jobs:" in text
    assert "job-fail" in text
    assert "Aborted / Skipped:" in text
    assert "• job-aborted (aborted)" in text
    assert "Resume command:" in text


def test_build_aborted_jobs_list_helper():
    """Verify that build_aborted_jobs_list correctly categorizes all non-completed statuses."""
    from lbs.utils.notifier import build_aborted_jobs_list
    from lbs.runner import _build_aborted_jobs_list

    summaries = {
        "job-success": {"status": "SUCCESS"},
        "job-failed": {"status": "FAILED"},
        "job-disabled": {"status": "DISABLED"},
        "job-skipped": {"status": "SKIPPED"},
        "job-aborted": {"status": "ABORTED"},
        "job-partial": {"status": "PARTIAL"},
        "job-pending": {"status": "PENDING"},
    }

    aborted = build_aborted_jobs_list(summaries)
    assert aborted == [
        "job-disabled (disabled)",
        "job-skipped (skipped)",
        "job-aborted (aborted)",
        "job-partial (aborted)",
        "job-pending (aborted)",
    ]

    # Verify runner module helper produces identical result
    assert _build_aborted_jobs_list(summaries) == aborted


def test_multiphase_job_interruption_duration_accumulates(tmp_path):
    """Verify that when a multi-phase job is interrupted, duration includes prior completed phases."""
    import pytest
    import time

    log_dir = tmp_path / "logs"
    settings = Settings(log_dir=str(log_dir))
    job = Job(
        name="multi-phase-job",
        cwd=str(tmp_path),
        phases={
            "phase-1": ["echo p1"],
            "phase-2": ["echo p2"],
        },
    )
    config = Config(settings=settings, jobs=[job])

    original_execute_phase_run = None
    from lbs.runner import _execute_phase_run as real_execute_phase_run

    def mock_phase_run(*args, **kwargs):
        phase_name = kwargs.get("phase_name")
        if phase_name == "phase-1":
            # Simulate phase 1 taking 2.5 seconds
            job_durations = kwargs.get("job_durations")
            job_name = kwargs.get("job").name
            job_durations[job_name] += 2.5
            return True, False, 2.5
        elif phase_name == "phase-2":
            # Interrupt during phase 2
            time.sleep(0.05)
            raise KeyboardInterrupt

    with patch("lbs.runner._execute_phase_run", side_effect=mock_phase_run):
        with pytest.raises(KeyboardInterrupt):
            Scheduler.run(config, config_path=tmp_path / "test.yaml")

    # Verify saved status file records accumulated duration >= 2.5s
    from lbs.config import resolve_status_path
    status_path = resolve_status_path(log_dir, tmp_path / "test.yaml")
    assert status_path.is_file()
    import json
    data = json.loads(status_path.read_text(encoding="utf-8"))
    job_summary = data["jobs"]["multi-phase-job"]
    assert job_summary["status"] == "INTERRUPTED"
    assert job_summary["duration"] >= 2.5

