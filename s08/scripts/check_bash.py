#!/usr/bin/env python3
"""
check_bash.py — PreToolUse hook for bash security validation.
Replaces s07's BashSecrityValidator.

Reads HOOK_TOOL_INPUT from environment and checks for dangerous patterns.
Exit codes:
  0 → safe, continue
  1 → dangerous, block execution

Environment variables set by HookManager:
  HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT, HOOK_MODE
"""
import os
import re
import sys

VALIDATORS = [
    ("shell_metachar",    r"[;&|`$]",           "Shell metacharacters detected"),
    ("sudo",             r"\bsudo\b",           "sudo privilege escalation"),
    ("rm_rf",            r"\brm\s+(-[a-zA-Z]*)?r", "Recursive delete (rm -r)"),
    ("cmd_substitution",  r"\$\(",              "Command substitution $(...)"),
    ("ifs_injection",    r"\bIFS\s*=",          "IFS variable manipulation"),
]

def main():
    tool_input_json = os.environ.get("HOOK_TOOL_INPUT", "{}")

    import json
    try:
        tool_input = json.loads(tool_input_json)
    except json.JSONDecodeError:
        print("[hook] Warning: could not parse HOOK_TOOL_INPUT", file=sys.stderr)
        sys.exit(0)

    command = tool_input.get("command", "")
    if not command:
        sys.exit(0)  # No command to check

    failures = []
    for name, pattern, desc in VALIDATORS:
        if re.search(pattern, command):
            failures.append((name, desc))

    if not failures:
        sys.exit(0)  # Safe

    # Separate severe (always deny) from moderate (ask user)
    severe_names = {"sudo", "rm_rf"}
    severe = [f for f in failures if f[0] in severe_names]

    if severe:
        reasons = "; ".join(desc for _, desc in severe)
        print(f"Bash security: {reasons}", file=sys.stderr)
        sys.exit(1)  # Block

    # Moderate issues: only block in "plan" mode, warn otherwise
    moderate_reasons = "; ".join(desc for _, desc in failures)
    mode = os.environ.get("HOOK_MODE", "default")

    if mode == "plan":
        print(f"Bash security (plan mode): {moderate_reasons}", file=sys.stderr)
        sys.exit(1)  # Block in plan mode
    else:
        print(f"Bash security flagged: {moderate_reasons}", file=sys.stderr)
        sys.exit(2)  # Inject warning message, still continue

if __name__ == "__main__":
    main()
