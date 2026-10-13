"""Add (or with --uninstall, remove) the buddy's hooks in ~/.claude/settings.json."""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
HOOK = os.path.join(HERE, "hook.py").replace("\\", "/")
COMMAND = f'python "{HOOK}"'
EVENTS = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreToolUse": "*",
    "PostToolUse": "*",
    "Notification": None,
    "Stop": None,
    "SubagentStart": None,
    "SubagentStop": None,
    "SessionEnd": None,
}


def is_ours(group):
    return any("clawd-buddy/hook.py" in h.get("command", "") for h in group.get("hooks", []))


def main():
    settings = {}
    if os.path.exists(SETTINGS):
        shutil.copy(SETTINGS, SETTINGS + ".bak-clawd")
        with open(SETTINGS) as f:
            settings = json.load(f)
    hooks = settings.setdefault("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [g for g in hooks[ev] if not is_ours(g)]
        if not hooks[ev]:
            del hooks[ev]
    if "--uninstall" not in sys.argv:
        for ev, matcher in EVENTS.items():
            group = {"hooks": [{"type": "command", "command": COMMAND, "timeout": 10}]}
            if matcher:
                group = {"matcher": matcher, **group}
            hooks.setdefault(ev, []).append(group)
    if not hooks:
        del settings["hooks"]
    with open(SETTINGS, "w") as f:
        json.dump(settings, f, indent=2)
    print("uninstalled" if "--uninstall" in sys.argv else "installed", "->", SETTINGS)


if __name__ == "__main__":
    main()
