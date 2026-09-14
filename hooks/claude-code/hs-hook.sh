#!/usr/bin/env bash
# Hunter-Seeker decision point for Claude Code (Datagoat unit 23) — curl only, no Python.
#
#   hs-hook.sh session-start   POST /v1/decide for the case; write HS_ROUTE (+ lane, arm, lever id)
#                              to $CLAUDE_ENV_FILE so the rest of the session reads the route
#   hs-hook.sh post-tool       POST /v1/ingest-events action.attested with the tool NAME only
#   hs-hook.sh stop            POST /v1/ingest-events case.closed
#
# Environment: HS_API_KEY (a live key), HS_AGENT_ID (the agent), HS_CASE_ID (the case key; else the
# hook's session_id), HS_SOURCE (the registered event-stream source URI for attestations),
# HS_BASE_URL (default https://hunter-seeker.io/api), HS_FALLBACK (act | review | human | none;
# default none), HS_KIND_JSON (the case's kind attributes, default {}).
#
# Three rules: exit 0 always (a hook that fails must not stop the session); never a denial from
# this script — the ROUTE is written for the harness's own policy to read; on any error or a
# two-second timeout the route is the named fallback with its reason.
set -u
EVENT="${1:-}"
INPUT="$(cat 2>/dev/null || true)"
BASE="${HS_BASE_URL:-https://hunter-seeker.io/api}"
FALLBACK="${HS_FALLBACK:-none}"
case "$FALLBACK" in act|review|human|none) ;; *) FALLBACK=none ;; esac

field() { printf '%s' "$INPUT" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -n1; }
CASE_ID="${HS_CASE_ID:-$(field session_id)}"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

emit_env() {  # $1 route $2 lane $3 arm $4 lever_id $5 fallback_applied $6 verdict_id
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    {
      printf 'export HS_ROUTE=%q\n' "$1"; printf 'export HS_LANE=%q\n' "$2"
      printf 'export HS_ARM=%q\n' "$3"; printf 'export HS_LEVER_ID=%q\n' "$4"
      printf 'export HS_CASE_REF=%q\n' "$CASE_ID"; printf 'export HS_FALLBACK_APPLIED=%q\n' "$5"
      printf 'export HS_VERDICT_ID=%q\n' "$6"
    } >> "$CLAUDE_ENV_FILE"
  fi
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"hs route: %s (lane %s, arm %s)"}}\n' "$1" "${2:-}" "${3:-}"
}

jfield() { printf '%s' "$1" | sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -n1; }

case "$EVENT" in
  session-start)
    if [ -z "${HS_API_KEY:-}" ] || [ -z "${HS_AGENT_ID:-}" ] || [ -z "$CASE_ID" ]; then
      emit_env "$FALLBACK" "" "" "" 1 ""; exit 0
    fi
    BODY=$(printf '{"agent_id":"%s","case":{"case_id":"%s","kind":%s,"actor":{"kind":"agent","name":"claude-code"},"opened_at":"%s"}}' \
      "$HS_AGENT_ID" "$CASE_ID" "${HS_KIND_JSON:-{\}}" "$NOW")
    RES=$(curl -sS --max-time 2 -X POST "$BASE/v1/decide" -H "Authorization: Bearer $HS_API_KEY" \
      -H "Content-Type: application/json" -d "$BODY" 2>/dev/null) || RES=""
    ROUTE=$(jfield "$RES" route)
    case "$ROUTE" in act|review|human|none) emit_env "$ROUTE" "$(jfield "$RES" lane)" "$(jfield "$RES" lever_arm)" "$(jfield "$RES" lever_id)" 0 "$(jfield "$RES" verdict_id)" ;;
      *) emit_env "$FALLBACK" "" "" "" 1 "" ;;
    esac
    ;;
  post-tool)
    TOOL="$(field tool_name)"
    if [ -n "${HS_API_KEY:-}" ] && [ -n "${HS_SOURCE:-}" ] && [ -n "$CASE_ID" ] && [ -n "$TOOL" ]; then
      DATA=$(printf '{"tool":"%s"' "$TOOL")
      [ -n "${HS_ARM:-}" ] && DATA="$DATA,\"arm\":\"$HS_ARM\""
      [ -n "${HS_LEVER_ID:-}" ] && DATA="$DATA,\"lever_id\":\"$HS_LEVER_ID\""
      DATA="$DATA}"
      EV=$(printf '{"events":[{"specversion":"1.0","id":"%s:attest:%s:%s","source":"%s","type":"action.attested","subject":"%s","time":"%s","datacontenttype":"application/json","data":%s}]}' \
        "$CASE_ID" "$TOOL" "$(date +%s%N 2>/dev/null || date +%s)" "$HS_SOURCE" "$CASE_ID" "$NOW" "$DATA")
      curl -sS --max-time 2 -o /dev/null -X POST "$BASE/v1/ingest-events" -H "Authorization: Bearer $HS_API_KEY" \
        -H "Content-Type: application/json" -d "$EV" 2>/dev/null || true
    fi
    ;;
  stop)
    if [ -n "${HS_API_KEY:-}" ] && [ -n "${HS_SOURCE:-}" ] && [ -n "$CASE_ID" ]; then
      EV=$(printf '{"events":[{"specversion":"1.0","id":"%s:closed","source":"%s","type":"case.closed","subject":"%s","time":"%s","datacontenttype":"application/json","data":{}}]}' \
        "$CASE_ID" "$HS_SOURCE" "$CASE_ID" "$NOW")
      curl -sS --max-time 2 -o /dev/null -X POST "$BASE/v1/ingest-events" -H "Authorization: Bearer $HS_API_KEY" \
        -H "Content-Type: application/json" -d "$EV" 2>/dev/null || true
    fi
    ;;
  *) ;;
esac
exit 0
