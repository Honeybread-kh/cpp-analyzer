"""
Telegram notification plugin.

Leaf module: depends on the Python standard library only and imports nothing
from ``cpp_analyzer`` itself, so it can never introduce an import cycle and is
trivially unit-testable.

Usage:
    from cpp_analyzer.plugins.telegram import TelegramNotifier, format_report

    notifier = TelegramNotifier(token, chat_id)
    notifier.send(format_report("myproject", stats))
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

API_BASE = "https://api.telegram.org"

#: Telegram rejects messages longer than 4096 UTF-8 characters.
MAX_MESSAGE_LEN = 4096

#: Network timeout (seconds).  Never omit this — a hung socket would block the
#: whole MCP server otherwise.
TIMEOUT = 10


class TelegramNotifier:
    """Minimal Telegram Bot API client for sending plain-text messages."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str) -> bool:
        """
        Send ``text`` to the configured chat.

        Returns True on success, False on any failure.  Errors are reported
        without ever echoing the bot token (it lives in the request URL, so
        exception strings must not be printed verbatim).
        """
        # ``parse_mode`` is deliberately NOT set: project names and paths often
        # contain '_' or '*', which would break Markdown/HTML parsing.
        payload = {
            "chat_id": self.chat_id,
            "text": (text or "")[:MAX_MESSAGE_LEN],
        }
        url = f"{API_BASE}/bot{self.token}/sendMessage"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            # HTTPError is a subclass of URLError, so it must be caught first.
            # str(e) can embed the request URL (and thus the token) — only the
            # status code and reason are safe to surface.
            print(f"[telegram] HTTP {e.code}: {e.reason}")
            return False
        except urllib.error.URLError as e:
            print(f"[telegram] network error: {e.reason}")
            return False
        except Exception as e:  # noqa: BLE001 - never let a notifier crash a run
            print(f"[telegram] send failed: {type(e).__name__}")
            return False


def format_report(project_name: str, stats: dict) -> str:
    """
    Build a compact plain-text summary of a project's index statistics.

    ``stats`` is accessed defensively so a partial/legacy stats dict still
    produces a usable message.

    Example output::

        [cpp-analyzer] myproject
        Files: 42 | Symbols: 1234 | Calls: 5678
    """
    stats = stats or {}
    lines = [
        f"[cpp-analyzer] {project_name}",
        "Files: {files} | Symbols: {symbols} | Calls: {calls}".format(
            files=stats.get("files", 0),
            symbols=stats.get("symbols", 0),
            calls=stats.get("calls", 0),
        ),
    ]

    extras = [
        ("Functions", "functions"),
        ("Classes", "classes"),
        ("Config keys", "config_keys"),
    ]
    detail = " | ".join(f"{label}: {stats.get(key, 0)}" for label, key in extras)
    if detail:
        lines.append(detail)

    return "\n".join(lines)
