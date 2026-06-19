# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.utils.notifier – Utility for dispatching desktop, webhook, and email notifications.
"""

from email.mime.text import MIMEText
import json
import smtplib
import subprocess
import sys
import urllib.request


def send_desktop_notification(title: str, message: str) -> None:
    """
    Trigger a Windows desktop balloon notification using a PowerShell command.
    Fails silently on non-Windows platforms or if PowerShell execution fails.
    """
    if sys.platform != "win32":
        return

    escaped_title = title.replace("'", "''")
    escaped_msg = message.replace("'", "''")

    ps_command = (
        "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
        "$sysicon = New-Object System.Windows.Forms.NotifyIcon; "
        "$sysicon.Icon = [System.Drawing.SystemIcons]::Information; "
        f"$sysicon.BalloonTipTitle = '{escaped_title}'; "
        f"$sysicon.BalloonTipText = '{escaped_msg}'; "
        "$sysicon.Visible = $true; "
        "$sysicon.ShowBalloonTip(5000); "
        "Start-Sleep -Seconds 1; "
        "$sysicon.Dispose();")

    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps_command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        pass


def send_slack_webhook(url: str, title: str, message: str) -> None:
    """Send a Slack notification using a JSON webhook payload."""
    payload = {"text": f"*{title}*\n{message}"}
    _post_json(url, payload)


def send_discord_webhook(url: str, title: str, message: str) -> None:
    """Send a Discord notification using a JSON webhook payload."""
    payload = {"content": f"**{title}**\n{message}"}
    _post_json(url, payload)


def send_email_notification(config, title: str, message: str) -> None:
    """Send a summary report email using standard smtplib."""
    if (not config or not config.smtp_host or not config.sender
            or not config.recipients):
        return

    msg = MIMEText(message)
    msg["Subject"] = title
    msg["From"] = config.sender
    msg["To"] = ", ".join(config.recipients)

    try:
        port = config.smtp_port or 587
        if port == 465:
            server = smtplib.SMTP_SSL(config.smtp_host, port, timeout=10)
        else:
            server = smtplib.SMTP(config.smtp_host, port, timeout=10)
            if config.use_tls:
                server.starttls()

        if config.smtp_username and config.smtp_password:
            server.login(config.smtp_username, config.smtp_password)

        server.sendmail(config.sender, config.recipients, msg.as_string())
        server.quit()
    except Exception:
        pass


def _post_json(url: str, payload: dict) -> None:
    """Helper method to POST JSON payload to url using urllib."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
    except Exception:
        pass


def dispatch_notifications(settings, success: bool, passed_count: int,
                           failed_count: int, skipped_count: int,
                           duration_str: str, job_summaries: dict) -> None:
    """
    Dispatch status notifications to all configured channels based on run outcome.
    """
    config = settings.notifications

    # Filter based on success/failure rules
    if success and not config.on_success:
        return
    if not success and not config.on_failure:
        return

    status_str = "SUCCESS" if success else "FAILED"
    title = f"LBS Session Completed: {status_str}"

    lines = [
        f"Status: {status_str}", f"Passed: {passed_count}",
        f"Failed: {failed_count}", f"Skipped: {skipped_count}",
        f"Duration: {duration_str}"
    ]

    # If there are failures, append job details
    if failed_count > 0:
        lines.append("")
        lines.append("Failed Jobs:")
        for name, summary in job_summaries.items():
            if summary.get("status") == "FAILED":
                dur = summary.get("duration")
                dur_str = f"{dur:.2f}s" if dur is not None else "N/A"
                lines.append(f"• {name} (failed in {dur_str})")

    message = "\n".join(lines)

    if config.desktop:
        send_desktop_notification(title, message)

    if config.slack_webhook:
        send_slack_webhook(config.slack_webhook, title, message)

    if config.discord_webhook:
        send_discord_webhook(config.discord_webhook, title, message)

    if config.email:
        send_email_notification(config.email, title, message)
