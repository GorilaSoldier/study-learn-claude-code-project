#!/usr/bin/env python3
"""
check_deny.py — PreToolUse hook for hard deny rules.
Replaces s07's deny rules in DEFAULT_RULES.

Reads HOOK_TOOL_NAME and HOOK_TOOL_INPUT from environment.
Exit codes:
  0 → no deny rule matched, continue
  1 → deny rule matched, block execution
"""
import json
import os
import sys

# Deny rules (hard-coded for teaching clarity)
# In production, these could come from a config file.
DENY_RULES = [
    # (tool_name, input_field, pattern, reason)
    ("bash", "command", "rm -rf /", "rm -rf / is always denied"),
    ("bash", "command", "sudo", "sudo is always denied"),
]


def main():
    tool_name = os.environ.get("HOOK_TOOL_NAME", "")
    tool_input_json = os.environ.get("HOOK_TOOL_INPUT", "{}")

    try:
        tool_input = json.loads(tool_input_json)
    except json.JSONDecodeError:
        sys.exit(0)

    for rule_tool, field, pattern, reason in DENY_RULES:
        if tool_name != rule_tool:
            continue
        value = tool_input.get(field, "")
        if pattern in value:
            print(f"Denied: {reason}", file=sys.stderr)
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
