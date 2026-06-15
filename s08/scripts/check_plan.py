#!/usr/bin/env python3
"""
check_plan.py — PreToolUse hook for plan mode.
When mode is "plan", all write operations are blocked.

Reads HOOK_TOOL_NAME and HOOK_MODE from environment.
Exit codes:
  0 → not in plan mode, or tool is read-only
  1 → in plan mode + write tool → blocked
"""
import os
import sys

WRITE_TOOLS = {"write_file", "edit_file", "bash"}


def main():
    mode = os.environ.get("HOOK_MODE", "default")

    # Only active in plan mode
    if mode != "plan":
        sys.exit(0)

    tool_name = os.environ.get("HOOK_TOOL_NAME", "")
    if tool_name in WRITE_TOOLS:
        print(f"Plan mode: {tool_name} operations are blocked", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
