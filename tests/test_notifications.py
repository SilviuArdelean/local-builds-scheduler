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
