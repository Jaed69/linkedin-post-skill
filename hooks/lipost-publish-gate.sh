#!/usr/bin/env bash
# Require human approval for any Bash call that runs `lipost publish`.
cmd=$(jq -r '.tool_input.command // ""')
if printf '%s' "$cmd" | grep -Eq '(^|[[:space:];&|/(])lipost([[:space:]]+|[[:space:]].*[[:space:]])publish([[:space:]]|$)'; then
  jq -n '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:"lipost publish posts to LinkedIn: a human must approve this exact command."}}'
fi
exit 0
