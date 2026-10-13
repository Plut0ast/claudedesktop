"""Claude Code hook: maps hook events to a buddy state and makes sure the buddy is running.

Each session gets its own state file, and each subagent gets its own file too, so parallel
hooks never fight over the same file:
    ~/.claude/clawd-buddy-state/<session>.json           the main Claude in that session
    ~/.claude/clawd-buddy-state/<session>~<agent>.json   a subagent it spawned

Must stay silent on stdout (UserPromptSubmit output would be added to Claude's context).
"""
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "clawd-buddy-state")
PORT = 47823

CODING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"}
ASK_TOOLS = {"AskUserQuestion", "ExitPlanMode"}


def safe(s):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(s))[:64] or "x"


def tool_state(tool):
    if tool in ASK_TOOLS:
        return "waiting"
    return "coding" if tool in CODING_TOOLS else "talking"


def updates_for(data):
    """Return a list of (agent_id or None, state, label, extra) to write."""
    ev = data.get("hook_event_name", "")
    agent = data.get("agent_id")
    label = os.path.basename(str(data.get("cwd", "")).rstrip("/\\"))
    if ev == "SubagentStart":
        return [(agent, "talking", data.get("agent_type", "agent"), {})]
    if ev == "SubagentStop":
        return [(agent, "done", data.get("agent_type", "agent"), {})]
    if ev == "PreToolUse":
        return [(agent, tool_state(data.get("tool_name", "")), None if agent else label, {})]
    if ev == "PostToolUse":
        return [(agent, "talking", None if agent else label, {})]
    if agent:
        return []  # anything else from inside a subagent: ignore
    if ev == "UserPromptSubmit":
        return [(None, "talking", label, {})]
    if ev == "Notification":
        kind = data.get("notification_type", "")
        msg = str(data.get("message", "")).lower()
        if kind == "permission_prompt" or "permission" in msg:
            return [(None, "waiting", label, {})]
        return []
    if ev == "Stop":
        return [(None, "done", label, {})]
    if ev == "SessionStart":
        return [(None, "idle", label, {})]
    return []


def write(path, payload):
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def ensure_running():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            return
    finally:
        s.close()
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for breakaway in (0x01000000, 0):  # try CREATE_BREAKAWAY_FROM_JOB so we outlive the hook
        try:
            subprocess.Popen([exe, os.path.join(HERE, "buddy.pyw")], cwd=HERE, close_fds=True,
                             creationflags=detached | breakaway, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        sid = safe(data.get("session_id", "default"))
        if data.get("hook_event_name") == "SessionEnd":
            for name in os.listdir(STATE_DIR):
                if name == sid + ".json" or name.startswith(sid + "~"):
                    os.remove(os.path.join(STATE_DIR, name))
        for agent, state, label, extra in updates_for(data):
            name = f"{sid}~{safe(agent)}.json" if agent else f"{sid}.json"
            path = os.path.join(STATE_DIR, name)
            payload = {"state": state, "ts": time.time(), "session": sid, "agent": agent, **extra}
            if not label:  # keep the label from SubagentStart / an earlier event
                try:
                    with open(path) as f:
                        label = json.load(f).get("label")
                except (OSError, ValueError):
                    pass
            if label:
                payload["label"] = label
            write(path, payload)
        if data.get("hook_event_name") in ("SessionStart", "UserPromptSubmit"):
            ensure_running()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
