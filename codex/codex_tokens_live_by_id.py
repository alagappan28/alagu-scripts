#!/usr/bin/env python3
"""
Live token monitor for one Codex conversation, selected by session ID.

Example:
  python3 codex_tokens_live.py 019f10c8-c221-77f2-8ffa-fa1d29651268

The script searches:
  ~/.codex/sessions/
  ~/.codex/archived_sessions/
"""

import argparse
import json
import time
from pathlib import Path
from typing import Optional

TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
)

PROMPT_LIMIT = 72


def session_id_from_file(path: Path) -> Optional[str]:
    """Read the session ID from the first session_meta record."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as log:
            for _ in range(100):
                line = log.readline()
                if not line:
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("type") != "session_meta":
                    continue

                payload = record.get("payload", {})
                value = payload.get("id") or payload.get("session_id")
                return str(value) if value else None
    except OSError:
        return None

    return None


def find_rollout(session_id: str) -> Path:
    """Find the newest rollout file belonging to the requested session."""
    roots = [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".codex" / "archived_sessions",
    ]

    # Fast path: Codex commonly includes the session ID in the filename.
    filename_matches = []
    for root in roots:
        if root.exists():
            filename_matches.extend(root.rglob(f"*{session_id}*.jsonl"))

    exact_matches = [
        path
        for path in filename_matches
        if path.is_file() and session_id_from_file(path) == session_id
    ]
    if exact_matches:
        return max(exact_matches, key=lambda path: path.stat().st_mtime)

    # Fallback: inspect rollout metadata in case the filename format changes.
    metadata_matches = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("rollout-*.jsonl"):
            if path.is_file() and session_id_from_file(path) == session_id:
                metadata_matches.append(path)

    if metadata_matches:
        return max(metadata_matches, key=lambda path: path.stat().st_mtime)

    searched = "\n  ".join(str(root) for root in roots)
    raise FileNotFoundError(
        f"No rollout found for session ID {session_id!r}.\n"
        f"Searched:\n  {searched}"
    )


def list_session_ids() -> list[str]:
    """Return known session IDs from active and archived rollout logs."""
    roots = [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".codex" / "archived_sessions",
    ]

    session_ids: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("rollout-*.jsonl"):
            if not path.is_file():
                continue
            session_id = session_id_from_file(path)
            if session_id:
                session_ids.add(session_id)

    return sorted(session_ids)


def cumulative_usage(record: dict) -> Optional[dict[str, int]]:
    """Extract cumulative token counters from a token_count event."""
    payload = record.get("payload", {})
    if record.get("type") != "event_msg" or payload.get("type") != "token_count":
        return None

    usage = payload.get("info", {}).get("total_token_usage")
    if not isinstance(usage, dict):
        return None

    return {
        key: int(usage.get(key, 0) or 0)
        for key in TOKEN_KEYS
    }


def parse_record(line: str) -> Optional[dict]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def turn_started(record: dict) -> Optional[str]:
    payload = record.get("payload", {})
    if record.get("type") != "event_msg" or payload.get("type") != "task_started":
        return None

    turn_id = payload.get("turn_id")
    return str(turn_id) if turn_id else None


def user_prompt(record: dict) -> Optional[str]:
    payload = record.get("payload", {})
    if record.get("type") != "event_msg" or payload.get("type") != "user_message":
        return None

    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def format_prompt(text: Optional[str]) -> str:
    if not text:
        return "-"

    compact = " ".join(text.split())
    if len(compact) <= PROMPT_LIMIT:
        return compact
    return compact[: PROMPT_LIMIT - 1].rstrip() + "…"


def print_usage_row(call_number: int, delta: dict[str, int], prompt: Optional[str]) -> None:
    uncached = max(
        0,
        delta["input_tokens"] - delta["cached_input_tokens"],
    )

    print(
        f"{call_number:>4}  "
        f"{delta['input_tokens']:>10,}  "
        f"{delta['cached_input_tokens']:>10,}  "
        f"{uncached:>10,}  "
        f"{delta['output_tokens']:>10,}  "
        f"{format_prompt(prompt)}",
        flush=True,
    )


def watch(path: Path, session_id: str, poll: float) -> None:
    previous = {key: 0 for key in TOKEN_KEYS}
    call_number = 0
    active_turn_id = None
    active_prompt = None

    with path.open("r", encoding="utf-8", errors="replace") as log:
        print(f"Session: {session_id}")
        print(f"Rollout: {path}\n")
        print("call  input       cached      uncached    output      prompt")
        print("----  ----------  ----------  ----------  ----------  ------------------------")

        # Replay existing records so the full history is visible first.
        for line in log:
            record = parse_record(line)
            if record is None:
                continue

            next_turn_id = turn_started(record)
            if next_turn_id is not None:
                active_turn_id = next_turn_id
                active_prompt = None

            prompt = user_prompt(record)
            if prompt is not None and active_turn_id is not None and active_prompt is None:
                active_prompt = prompt

            usage = cumulative_usage(record)
            if usage is not None:
                delta = {
                    key: usage[key] - previous[key]
                    for key in TOKEN_KEYS
                }

                if any(value < 0 for value in delta.values()):
                    previous = usage
                    print("[token counters reset; baseline updated]", flush=True)
                    continue

                if not any(delta.values()):
                    previous = usage
                    continue

                call_number += 1

                print_usage_row(call_number, delta, active_prompt)
                previous = usage

        while True:
            line = log.readline()
            if not line:
                time.sleep(poll)
                continue

            record = parse_record(line)
            if record is None:
                continue

            next_turn_id = turn_started(record)
            if next_turn_id is not None:
                active_turn_id = next_turn_id
                active_prompt = None

            prompt = user_prompt(record)
            if prompt is not None and active_turn_id is not None and active_prompt is None:
                active_prompt = prompt

            current = cumulative_usage(record)
            if current is None:
                continue

            delta = {
                key: current[key] - previous[key]
                for key in TOKEN_KEYS
            }

            # A restart or accounting reset can lower cumulative counters.
            if any(value < 0 for value in delta.values()):
                previous = current
                print("[token counters reset; baseline updated]", flush=True)
                continue

            # Ignore duplicate/rate-limit-only events.
            if not any(delta.values()):
                continue

            call_number += 1
            print_usage_row(call_number, delta, active_prompt)
            previous = current


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch token usage for one Codex session ID."
    )
    parser.add_argument(
        "session_id",
        nargs="?",
        help="Codex session ID shown by /status. If omitted, list known session IDs.",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=0.25,
        help="Polling interval in seconds (default: 0.25).",
    )
    args = parser.parse_args()

    if not args.session_id:
        session_ids = list_session_ids()
        if not session_ids:
            raise SystemExit("No session IDs found in ~/.codex sessions.")

        print("Available session IDs:")
        for session_id in session_ids:
            print(session_id)
        return

    path = find_rollout(args.session_id)
    watch(path, args.session_id, max(args.poll, 0.05))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (FileNotFoundError, PermissionError) as exc:
        raise SystemExit(f"Error: {exc}")
