# Clawd Buddy

A tiny pixel-art Clawd that sits on top of every window on your desktop and reacts to what
[Claude Code](https://claude.com/claude-code) is doing.

| State | When | Animation |
|---|---|---|
| Idle | Nothing running | Breathes, blinks, looks around; dozes off after a few minutes |
| Talking | Claude is replying or thinking | Mouth moves, speech bubble with dots |
| Coding | Edit / Write / Bash tools | Types on a keyboard; a mini editor fills with code |
| Waiting | Permission prompt or a question for you | Bouncing `?`, taps a foot |
| Done | Claude finished its turn | Hops with arms up, check mark and sparkles |

Each busy session gets its own crab with its project folder as a name tag, and every
subagent shows up as a smaller crab next to its parent while it runs.

## Requirements

- Windows
- Python 3 with Tkinter (included in the standard python.org / Microsoft Store installs)
- Claude Code (CLI or the desktop app's Code tab)

## Install

1. Clone the repo somewhere it can stay (the hooks point at this folder, so don't move or
   delete it afterwards):

   ```bash
   git clone https://github.com/Plut0ast/claudedesktop.git clawd-buddy
   cd clawd-buddy
   ```

2. Add the Claude Code hooks:

   ```bash
   python install.py
   ```

   This adds hooks to `~/.claude/settings.json` and saves a backup of your old settings as
   `~/.claude/settings.json.bak-clawd`. Running it again is safe: it replaces its own hooks
   instead of adding duplicates. `python` must be on your PATH, because the hooks call it.

3. Start a new Claude Code session (or send a prompt in an open one). The buddy launches
   by itself and appears in the bottom-right corner of your screen. To start it by hand:

   ```bash
   pythonw buddy.pyw
   ```

If you move the folder, run `python install.py` again from its new location.

To remove the hooks:

```bash
python install.py --uninstall
```

## Using it

- **Drag** to move it (the position is remembered).
- **Click** a crab to make it hop.
- **Right-click** for the menu: preview animations, change the size, reset position, quit.

## Settings

`settings.json` is created next to `buddy.pyw` on first run and reloaded live while the
buddy is running:

```json
{
  "scale": 3,
  "agent_scale": 2,
  "show_labels": true,
  "label_font_size": 7,
  "animation_speed": 0.5
}
```

- `scale`: screen pixels per art pixel for the main crabs (1 to 10)
- `agent_scale`: the same, for subagent crabs
- `show_labels`: name tags under the crabs when more than one is shown
- `label_font_size`: name tag font size
- `animation_speed`: 1 is lively, lower is calmer (0.1 to 3)

## How it works

`hook.py` runs on Claude Code hook events (`UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `Notification`, `Stop`, `SubagentStart`, `SubagentStop`, ...) and writes
one small JSON file per session and per subagent to `~/.claude/clawd-buddy-state/`.
`buddy.pyw` is a transparent, always-on-top Tkinter window that watches that folder and
draws a crab for each active one.
