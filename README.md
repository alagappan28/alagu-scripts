# alagu-scripts

Small, reusable scripts I can share and maintain in one place.

## Codex Support

This script works with both the Codex CLI and the Codex app.

Run `/status` in your Codex session to get the session ID for the current chat, then pass that ID to the script.
It replays the existing token history in the rollout file first, then keeps watching for new events. Each token row includes the starting user prompt for that turn so the usage is easier to identify.

## Layout

- `codex/` - scripts for Codex session logs and related tooling
- `README.md` - repo overview and usage notes
- `LICENSE` - permissive license for reuse

## Scripts

- `codex/codex_tokens_live_by_id.py` - list known Codex session IDs or watch token usage by turn prompt for one session

## Usage

```bash
python3 codex/codex_tokens_live_by_id.py
python3 codex/codex_tokens_live_by_id.py <session-id>
```
