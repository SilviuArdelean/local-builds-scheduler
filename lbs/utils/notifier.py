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


def dispatch_notifications(
    settings,
    success: bool,
    passed_count: int,
    failed_count: int,
    skipped_count: int,
    duration_str: str,
    job_summaries: dict,
    interrupted: bool = False,
    aborted_jobs: list[str] | None = None,
    resume_cmd: str | None = None,
) -> None:
    """
    Dispatch status notifications to all configured channels based on run outcome.
    """
    if not settings or not getattr(settings, "notifications", None):
        return
    config = settings.notifications

    # Filter based on success/failure rules
    if success and not config.on_success:
        return
    if not success and not config.on_failure:
        return

    if interrupted:
        title = "LBS Session Interrupted: CANCELLED"
    else:
        status_str = "SUCCESS" if success else "FAILED"
        title = f"LBS Session Completed: {status_str}"

    formatted_aborted = []
    if aborted_jobs:
        for item in aborted_jobs:
            item_str = str(item).strip()
            if not item_str.startswith("• "):
                if "(" not in item_str and job_summaries and item_str in job_summaries:
                    st = job_summaries[item_str].get("status", "aborted").lower()
                    if st in ("disabled", "skipped", "partial", "aborted"):
                        item_str = f"• {item_str} ({st})"
                    else:
                        item_str = f"• {item_str} (aborted)"
                elif "(" not in item_str:
                    item_str = f"• {item_str} (aborted)"
                else:
                    item_str = f"• {item_str}"
            formatted_aborted.append(item_str)
    elif aborted_jobs is None and (not success or interrupted) and job_summaries:
        for name, summary in job_summaries.items():
            st = summary.get("status")
            if st in ("ABORTED", "PARTIAL", "SKIPPED", "DISABLED", "PENDING"):
                label = "disabled" if st == "DISABLED" else ("skipped" if st == "SKIPPED" else "aborted")
                formatted_aborted.append(f"• {name} ({label})")

    if interrupted or formatted_aborted:
        if interrupted:
            status_line = "Status: CANCELLED (Interrupted by user)"
        else:
            fail_word = "failure" if failed_count == 1 else "failures"
            status_line = (
                f"Status: FAILED (Aborted after {failed_count} {fail_word})"
                if failed_count > 0
                else "Status: FAILED (Aborted)"
            )

        aborted_cnt = len(formatted_aborted) if formatted_aborted else skipped_count
        lines = [
            status_line,
            f"Passed: {passed_count} | Failed: {failed_count} | Aborted: {aborted_cnt}",
            f"Duration: {duration_str}",
        ]
    else:
        status_str = "SUCCESS" if success else "FAILED"
        lines = [
            f"Status: {status_str}",
            f"Passed: {passed_count}",
            f"Failed: {failed_count}",
            f"Skipped: {skipped_count}",
            f"Duration: {duration_str}",
        ]

    # If there are failures or interruptions, append job details
    if failed_count > 0 or (interrupted and job_summaries):
        failed_entries = []
        for name, summary in job_summaries.items():
            if summary.get("status") in ("FAILED", "INTERRUPTED"):
                dur = summary.get("duration")
                if isinstance(dur, (int, float)):
                    h = int(dur) // 3600
                    m = (int(dur) % 3600) // 60
                    s = int(dur) % 60
                    dur_str = f"{h:02d}:{m:02d}:{s:02d}"
                elif isinstance(dur, str):
                    dur_str = dur
                else:
                    dur_str = "N/A"
                failed_entries.append(f"• {name} (failed in {dur_str})")
        if failed_entries:
            lines.append("")
            lines.append("Failed Jobs:")
            lines.extend(failed_entries)

    if formatted_aborted:
        lines.append("")
        lines.append("Aborted / Skipped:")
        for item in formatted_aborted:
            lines.append(item)

    if resume_cmd:
        lines.append("")
        lines.append("Resume command:")
        lines.append(f"  {resume_cmd.strip()}")

    message = "\n".join(lines)

    if config.desktop:
        send_desktop_notification(title, message)

    if config.slack_webhook:
        send_slack_webhook(config.slack_webhook, title, message)

    if config.discord_webhook:
        send_discord_webhook(config.discord_webhook, title, message)

    if config.email:
        send_email_notification(config.email, title, message)
