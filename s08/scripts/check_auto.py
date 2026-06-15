#!/usr/bin/env python3
"""
check_auto.py — PreToolUse hook for auto mode.
In auto mode, read-only tools are auto-approved silently.
Write tools are left for other hooks (or the permission system) to decide.

This hook is a no-op (always exits 0), serving as a placeholder
to document the auto-mode logic. In a real system, this could
pre-populate allow decisions or skip further checks.

Reads HOOK_TOOL_NAME and HOOK_MODE from environment.
Exit codes:
  0 → always, let other hooks / agent loop decide
"""
import os
import sys


def main():
    mode = os.environ.get("HOOK_MODE", "default")

    # Only active in auto mode
    if mode != "auto":
        sys.exit(0)

    tool_name = os.environ.get("HOOK_TOOL_NAME", "")
    read_only_tools = {"read_file"}

    if tool_name in read_only_tools:
        # Read-only in auto mode: silently approve
        # (simple hooks can just exit 0)
        sys.exit(0)
    else:
        # Write tools in auto mode: let other hooks decide,
        # or fall through to the permission system
        sys.exit(0)


if __name__ == "__main__":
    main()
