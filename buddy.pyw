"""Clawd buddy: tiny always-on-top Claudes that react to what Claude Code is doing.

One crab per busy session, plus a smaller crab for each subagent while it runs.
State comes from ~/.claude/clawd-buddy-state/*.json, written by hook.py (Claude Code hooks).
Drag to move, click a crab to poke it, right-click for the menu.
"""
import ctypes
import json
import os
import random
import socket
import sys
import time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "clawd-buddy-state")
SETTINGS_FILE = os.path.join(HERE, "settings.json")   # user-editable, reloaded live
POSITION_FILE = os.path.join(HERE, "position.json")   # remembered window position
DEFAULT_SETTINGS = {
    "scale": 3,            # screen pixels per art pixel for the main crabs (1 = tiny, 10 = huge)
    "agent_scale": 2,      # same, for subagent crabs
    "show_labels": True,   # name tags under each crab when more than one is shown
    "label_font_size": 7,
    "animation_speed": 0.5,  # 1 = original lively speed, lower = calmer (0.1 - 3)
}
PORT = 47823  # single-instance lock; hook.py pings it to see if we're running

TRANSP = "#ff00fe"
ORANGE = "#d97757"
AGENT_ORANGE = "#e8a07c"
EYE = "#1a1a1a"
MOUTH = "#5c2414"
WHITE = "#fafafa"
DARK = "#262626"
YELLOW = "#f5c542"
GREEN = "#4ade80"
PANEL = "#1e1e2e"
KB_DARK = "#3a3a44"
KB_LIGHT = "#8a8a99"
CODE_COLORS = ("#c792ea", "#82aaff", "#c3e88d", "#ffcb6b", "#89ddff", "#f07178")

GW, GH = 28, 25          # one actor's cell, in art pixels
OX, OY = 5, GH - 10      # top-left of the crab sprite (16 wide, 10 tall incl. legs)
FPS = 10
DONE_SECONDS = 8          # "done" celebration length; finished subagents leave after it
STALE_SECONDS = 15 * 60   # talking/coding with no hook events for this long -> idle
WAIT_STALE = 2 * 3600     # forgotten permission prompts eventually stop showing
AGENT_STALE = 10 * 60     # subagent silent this long -> assume it's gone
SLEEP_AFTER = 180         # idle this long -> dozes off
STATES = ("idle", "talking", "coding", "waiting", "done")
ACTIVE = ("talking", "coding", "waiting", "done")

HOP = [0, -1, -3, -4, -4, -3, -1, 0, 0, 0]
TALK = [1, 2, 1, 0, 2, 1, 0, 0, 1, 2, 2, 0]

QMARK = [" ### ", "#   #", "    #", "  ## ", "  #  ", "     ", "  #  "]
CHECK = ["      #", "     ##", "#   ## ", "## ##  ", " ###   ", "  #    "]
ZED = ["###", " # ", "###"]
SPARKLES = [(OX - 3, OY - 2), (OX + 18, OY - 4), (OX - 1, OY - 10), (OX + 16, OY - 12), (OX + 20, OY + 3)]


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:
        return 1.0


class Pen:
    """Draws art pixels onto the canvas at a given offset and scale."""

    def __init__(self, canvas, x, y, s):
        self.canvas, self.x, self.y, self.s = canvas, x, y, s

    def px(self, x, y, w, h, color):
        s = self.s
        self.canvas.create_rectangle(self.x + x * s, self.y + y * s, self.x + (x + w) * s,
                                     self.y + (y + h) * s, fill=color, outline="", width=0)

    def glyph(self, rows, x, y, color):
        for j, r in enumerate(rows):
            for i, ch in enumerate(r):
                if ch != " ":
                    self.px(x + i, y + j, 1, 1, color)

    def box(self, bx, by, bw, bh, fill):
        """Box with clipped (rounded) corners."""
        self.px(bx + 1, by, bw - 2, bh, fill)
        self.px(bx, by + 1, bw, bh - 2, fill)


class Actor:
    """One crab: the main Claude of a session, or one of its subagents."""

    def __init__(self, key, session=None, agent=None, label=""):
        self.key, self.session, self.agent, self.label = key, session, agent, label
        self.color = AGENT_ORANGE if agent else ORANGE
        self.state, self.since, self.t, self.clock = "idle", time.time(), 0, 0.0
        self.mtime = None
        self.poke_t = None
        self.look, self.look_until = 0, 0
        self.blink_at = random.randint(10, 40)
        self.code, self.code_p = [], 0

    def set(self, st, ts=None):
        if st != self.state:
            self.state, self.t, self.clock, self.poke_t = st, 0, 0.0, None
        self.since = time.time() if ts is None else ts

    def age(self):
        return time.time() - self.since

    # ---------- body ----------
    def crab(self, pen, dy=0, eyes="normal", arms="side", mouth=0, squash=False, tap=False):
        p, c = pen.px, self.color
        x0 = OX
        y0 = OY + dy + (1 if squash else 0)
        feet = OY + dy + 10
        for i, lx in enumerate((3, 5, 10, 12)):
            bottom = feet - (1 if tap and i == 3 else 0)
            if bottom > y0 + 7:
                p(x0 + lx, y0 + 7, 1, bottom - (y0 + 7), c)
        p(x0 + 2, y0, 12, 7, c)

        if arms == "up":
            p(x0, y0 - 2, 2, 2, c); p(x0 + 1, y0, 1, 3, c)
            p(x0 + 14, y0 - 2, 2, 2, c); p(x0 + 14, y0, 1, 3, c)
        else:
            left = right = y0 + 3
            if arms == "typeL":
                left = y0 + 5
            elif arms == "typeR":
                right = y0 + 5
            elif arms == "wave":
                p(x0 + 14, y0 - 2, 2, 2, c); p(x0 + 14, y0, 1, 3, c)
                right = None
            p(x0, left, 2, 2, c)
            if right is not None:
                p(x0 + 14, right, 2, 2, c)

        for ex in (4, 11):
            if eyes == "happy":
                p(x0 + ex - 1, y0 + 3, 1, 1, EYE); p(x0 + ex, y0 + 2, 1, 1, EYE); p(x0 + ex + 1, y0 + 3, 1, 1, EYE)
            elif eyes == "closed":
                p(x0 + ex - (1 if ex == 4 else 0), y0 + 3, 2, 1, EYE)
            elif eyes == "blink":
                p(x0 + ex + self.look, y0 + 3, 1, 1, EYE)
            else:
                vy = {"up": 1, "down": 3}.get(eyes, 2)
                p(x0 + ex + self.look, y0 + vy, 1, 2, EYE)
        if mouth == 1:
            p(x0 + 7, y0 + 5, 2, 1, MOUTH)
        elif mouth == 2:
            p(x0 + 6, y0 + 5, 4, 1, MOUTH)

    def update_eyes(self, choices=(0, 0, 0, -1, 1)):
        if self.t >= self.look_until:
            self.look = random.choice(choices)
            self.look_until = self.t + random.randint(15, 45)
        blinking = self.blink_at <= self.t < self.blink_at + 2
        if self.t >= self.blink_at + 2:
            self.blink_at = self.t + random.randint(25, 60)
        return blinking

    # ---------- animations ----------
    def draw(self, pen, speed=1.0):
        if self.poke_t is not None and self.t - self.poke_t < len(HOP):
            k = self.t - self.poke_t
            self.crab(pen, dy=HOP[k], eyes="happy", arms="up" if HOP[k] < 0 else "side", squash=k == 7)
        else:
            getattr(self, "draw_" + self.state)(pen)
        self.clock += speed
        self.t = int(self.clock)

    def draw_idle(self, pen):
        t = self.t
        if self.age() > SLEEP_AFTER:
            self.look = 0
            self.crab(pen, eyes="closed", squash=(t // 15) % 2 == 0)
            for k in range(2):
                ph = (t + k * 20) % 40
                pen.glyph(ZED, OX + 13 + ph // 8, OY - 2 - ph // 4, WHITE)
            return
        blink = self.update_eyes()
        self.crab(pen, eyes="blink" if blink else "normal", squash=(t // 15) % 4 == 3)

    def draw_talking(self, pen):
        t = self.t
        blink = self.update_eyes((0, 0, 1))
        arms = "wave" if (t // 25) % 8 == 7 else "side"
        self.crab(pen, eyes="blink" if blink else "normal", mouth=TALK[(t // 2) % len(TALK)], arms=arms)
        bx, by, bw, bh = OX + 9, OY - 10, 14, 7
        pen.box(bx, by, bw, bh, WHITE)
        # tail pointing at the head
        pen.px(bx + 1, by + bh - 1, 2, 2, WHITE)
        pen.px(bx, by + bh + 1, 1, 1, WHITE)
        for k in range(3):
            bounce = -1 if (t // 4) % 4 == k else 0
            pen.px(bx + 3 + k * 3, by + 3 + bounce, 2, 2, DARK)

    def rand_line(self, maxlen):
        indent = random.choice((0, 0, 2, 2, 4))
        line, n = [None] * indent, indent
        while n < maxlen - 2:
            seg = random.randint(2, 5)
            line += [random.choice(CODE_COLORS)] * seg + [None]
            n += seg + 1
            if random.random() < 0.3:
                break
        return line[:maxlen]

    def draw_coding(self, pen):
        t = self.t
        self.look = 0
        arms = "typeL" if (t // 3) % 2 else "typeR"
        blink = self.update_eyes((0,))
        self.crab(pen, eyes="blink" if blink else "down", arms=arms)
        # keyboard in front
        pen.px(OX, OY + 7, 16, 2, KB_DARK)
        lit = (t // 3 * 5) % 7
        for i in range(7):
            pen.px(OX + 1 + i * 2, OY + 7, 1, 1, ORANGE if i == lit else KB_LIGHT)

        # little editor window above the head, typing out code
        bx, by, bw, bh = OX + 1, OY - 12, 18, 10
        pen.box(bx, by, bw, bh, PANEL)
        for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            pen.px(bx + 2 + i * 2, by + 1, 1, 1, c)
        maxlen = bw - 4
        if t != getattr(self, "code_t", None):  # type one character per clock tick
            self.code_t = t
            if not self.code or self.code_p >= len(self.code[-1]):
                self.code = (self.code + [self.rand_line(maxlen)])[-3:]
                self.code_p = 0
            else:
                self.code_p += 1
        for row, line in enumerate(self.code):
            shown = len(line) if row < len(self.code) - 1 else self.code_p
            y = by + 3 + row * 2
            for i, c in enumerate(line[:shown]):
                if c:
                    pen.px(bx + 2 + i, y, 1, 1, c)
            if row == len(self.code) - 1 and (t // 3) % 2 == 0:
                pen.px(bx + 2 + shown, y, 1, 1, WHITE)

    def draw_waiting(self, pen):
        t = self.t
        self.look = (-1, 0, 1, 0)[(t // 12) % 4]
        blink = self.blink_at <= t < self.blink_at + 2
        if t >= self.blink_at + 2:
            self.blink_at = t + random.randint(25, 60)
        self.crab(pen, eyes="blink" if blink else "up", tap=(t // 6) % 2 == 0)
        pen.glyph(QMARK, OX + 5, OY - 10 - (t // 8) % 2, YELLOW)

    def draw_done(self, pen):
        t = self.t
        k = t % (len(HOP) + 6)
        k = k if k < len(HOP) else 0
        self.crab(pen, dy=HOP[k], eyes="happy", arms="up" if HOP[k] < 0 else "side", squash=k == 7)
        pen.glyph(CHECK, OX + 4, OY - 13, GREEN)
        for i, (sx, sy) in enumerate(SPARKLES):
            ph = (t // 4 + i) % 3
            if ph == 0:
                pen.px(sx - 1, sy, 3, 1, YELLOW); pen.px(sx, sy - 1, 1, 3, YELLOW)
            elif ph == 1:
                pen.px(sx, sy, 1, 1, WHITE)


class Buddy:
    def __init__(self, lock):
        self.lock = lock
        self.dpi = set_dpi_aware()
        self.settings, self.settings_mtime = dict(DEFAULT_SETTINGS), None
        self.load_settings()

        self.root = tk.Tk()
        self.root.title("Clawd")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSP)
        self.root.configure(bg=TRANSP)
        self.canvas = tk.Canvas(self.root, bg=TRANSP, highlightthickness=0, bd=0)
        self.canvas.pack()

        self.actors = {}          # key -> Actor, from state files
        self.lonely = Actor("_idle")  # shown when nobody is busy
        self.lonely_shown = False
        self.preview, self.preview_until = [], 0
        self.layout = []          # [(actor, x0, x1)] for click hit-testing
        self.size = (0, 0)
        self.frame = 0
        self.drag = None

        pos = self.load_json(POSITION_FILE)
        right, bottom = pos.get("right"), pos.get("bottom")
        if right is None or bottom is None:
            right = self.root.winfo_screenwidth() - 40
            bottom = self.root.winfo_screenheight() - 50
        self.anchor = (int(right), int(bottom))  # window grows leftwards/upwards from here

        self.build_menu()
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.cleanup_old_files()
        self.root.after(0, self.tick)

    # ---------- config / window ----------
    @staticmethod
    def load_json(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    def load_settings(self):
        """(Re)read settings.json, creating it with defaults if it's missing."""
        if not os.path.exists(SETTINGS_FILE):
            self.write_settings(DEFAULT_SETTINGS)
        try:
            m = os.path.getmtime(SETTINGS_FILE)
        except OSError:
            return
        if m == self.settings_mtime:
            return
        self.settings_mtime = m
        data = self.load_json(SETTINGS_FILE)
        if not data:
            return  # missing or mid-edit / invalid JSON: keep the current settings
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        for key in ("scale", "agent_scale", "label_font_size"):
            try:
                merged[key] = max(1, min(20, int(merged[key])))
            except (TypeError, ValueError):
                merged[key] = DEFAULT_SETTINGS[key]
        try:
            merged["animation_speed"] = max(0.1, min(3.0, float(merged["animation_speed"])))
        except (TypeError, ValueError):
            merged["animation_speed"] = DEFAULT_SETTINGS["animation_speed"]
        self.settings = merged

    def write_settings(self, data):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def set_scale(self, s):
        data = self.load_json(SETTINGS_FILE) or dict(DEFAULT_SETTINGS)
        data["scale"] = s
        data["agent_scale"] = max(1, round(s * 0.7))
        self.write_settings(data)
        self.load_settings()

    def save_cfg(self):
        try:
            with open(POSITION_FILE, "w") as f:
                json.dump({"right": self.anchor[0], "bottom": self.anchor[1]}, f)
        except OSError:
            pass

    def build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        preview = tk.Menu(self.menu, tearoff=0)
        for st in STATES:
            preview.add_command(label=st.capitalize(), command=lambda s=st: self.start_preview([(s, None, "")]))
        preview.add_separator()
        preview.add_command(label="With 2 subagents", command=lambda: self.start_preview(
            [("talking", None, "my-project"), ("coding", "a1", "Explore"), ("talking", "a2", "general-purpose")]))
        preview.add_command(label="2 sessions at once", command=lambda: self.start_preview(
            [("coding", None, "portfolio"), ("waiting", None, "api-server")]))
        self.menu.add_cascade(label="Preview animation", menu=preview)
        size = tk.Menu(self.menu, tearoff=0)
        for s in range(1, 11):
            size.add_command(label=f"{s}x", command=lambda s=s: self.set_scale(s))
        size.add_separator()
        size.add_command(label="Open settings.json…", command=lambda: os.startfile(SETTINGS_FILE))
        self.menu.add_cascade(label="Size", menu=size)
        self.menu.add_command(label="Reset position", command=self.reset_position)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)

    def reset_position(self):
        self.anchor = (self.root.winfo_screenwidth() - 40, self.root.winfo_screenheight() - 50)
        self.size = (0, 0)
        self.save_cfg()

    def start_preview(self, specs):
        self.preview = []
        for i, (st, agent, label) in enumerate(specs):
            a = Actor(f"_preview{i}", session="_preview", agent=agent, label=label)
            a.set(st)
            self.preview.append(a)
        self.preview_until = time.time() + 10

    def quit(self):
        self.save_cfg()
        self.root.destroy()

    def on_press(self, e):
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y(), e.x_root, e.y_root, False)

    def on_drag(self, e):
        if not self.drag:
            return
        dx, dy, sx, sy, moved = self.drag
        if moved or abs(e.x_root - sx) + abs(e.y_root - sy) > 3:
            self.drag = (dx, dy, sx, sy, True)
            x, y = e.x_root - dx, e.y_root - dy
            self.root.geometry(f"+{x}+{y}")
            self.anchor = (x + self.size[0], y + self.size[1])

    def on_release(self, e):
        if self.drag and self.drag[4]:
            self.save_cfg()
        else:
            for actor, x0, x1 in self.layout:
                if x0 <= e.x < x1:
                    actor.poke_t = actor.t
        self.drag = None

    # ---------- state ----------
    def cleanup_old_files(self):
        try:
            for name in os.listdir(STATE_DIR):
                path = os.path.join(STATE_DIR, name)
                if time.time() - os.path.getmtime(path) > 24 * 3600:
                    os.remove(path)
        except OSError:
            pass

    def poll_files(self):
        try:
            names = [n for n in os.listdir(STATE_DIR) if n.endswith(".json")]
        except OSError:
            names = []
        keys = set()
        for name in names:
            key = name[:-5]
            keys.add(key)
            path = os.path.join(STATE_DIR, name)
            try:
                m = os.path.getmtime(path)
            except OSError:
                continue
            actor = self.actors.get(key)
            if actor and actor.mtime == m:
                continue
            try:
                with open(path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue  # mid-write; try again next poll
            if not actor:
                session, _, agent = key.partition("~")
                actor = self.actors[key] = Actor(key, session, agent or None)
            actor.mtime = m
            actor.label = data.get("label") or actor.label
            if data.get("state") in STATES:
                actor.set(data["state"], float(data.get("ts", m)))
        for key in list(self.actors):
            if key not in keys:
                del self.actors[key]

    def forget(self, actor):
        self.actors.pop(actor.key, None)
        try:
            os.remove(os.path.join(STATE_DIR, actor.key + ".json"))
        except OSError:
            pass

    def visible_actors(self):
        if self.preview and time.time() < self.preview_until:
            return self.preview
        self.preview = []

        # expire states
        for a in list(self.actors.values()):
            age = a.age()
            if a.agent:
                if (a.state == "done" and age > DONE_SECONDS) or (a.state != "waiting" and age > AGENT_STALE):
                    self.forget(a)
            elif (a.state == "done" and age > DONE_SECONDS) or \
                    (a.state in ("talking", "coding") and age > STALE_SECONDS) or \
                    (a.state == "waiting" and age > WAIT_STALE):
                a.set("idle")

        agents = [a for a in self.actors.values() if a.agent]
        busy_sessions = {a.session for a in agents}
        mains = [a for a in self.actors.values() if not a.agent
                 and (a.state in ACTIVE or a.session in busy_sessions)]
        mains.sort(key=lambda a: a.key)
        shown = []
        for m in mains:
            shown.append(m)
            shown += sorted((a for a in agents if a.session == m.session), key=lambda a: a.key)
        main_sessions = {m.session for m in mains}
        shown += sorted((a for a in agents if a.session not in main_sessions), key=lambda a: a.key)

        if not shown:
            if not self.lonely_shown:
                self.lonely.set("idle")
            shown = [self.lonely]
        self.lonely_shown = shown == [self.lonely]
        return shown

    def accept_pings(self):
        try:
            while True:
                conn, _ = self.lock.accept()
                conn.close()
        except OSError:
            pass

    # ---------- render ----------
    def tick(self):
        self.accept_pings()
        if self.frame % 3 == 0:
            self.poll_files()
            self.load_settings()
        self.render(self.visible_actors())
        self.frame += 1
        if self.frame % (FPS * 2) == 0:  # other windows can steal topmost; take it back
            self.root.attributes("-topmost", True)
            self.root.lift()
        self.root.after(1000 // FPS, self.tick)

    def render(self, actors):
        cfg = self.settings
        labels = len(actors) > 1 and cfg["show_labels"]
        font = ("Segoe UI", cfg["label_font_size"], "bold")
        label_h = round((cfg["label_font_size"] * 2 + 4) * self.dpi) if labels else 0
        scales = [cfg["agent_scale"] if a.agent else cfg["scale"] for a in actors]
        w = sum(GW * s for s in scales)
        h = max(GH * s for s in scales) + label_h
        if (w, h) != self.size:
            self.size = (w, h)
            self.canvas.config(width=w, height=h)
            self.root.geometry(f"{w}x{h}+{self.anchor[0] - w}+{self.anchor[1] - h}")

        self.canvas.delete("all")
        self.layout = []
        x = 0
        base = h - label_h
        for a, s in zip(actors, scales):
            aw = GW * s
            a.draw(Pen(self.canvas, x, base - GH * s, s), cfg["animation_speed"])
            self.layout.append((a, x, x + aw))
            if labels and a.label:
                text = a.label if len(a.label) <= 16 else a.label[:15] + "…"
                cx = x + (OX + 8) * s
                tid = self.canvas.create_text(cx, base + label_h // 2, text=text, fill=WHITE, font=font)
                x0, y0, x1, y1 = self.canvas.bbox(tid)
                pill = self.canvas.create_rectangle(x0 - 3, y0, x1 + 3, y1,
                                                    fill=DARK, outline="", width=0)
                self.canvas.tag_lower(pill, tid)
            x += aw


def main():
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", PORT))
        lock.listen(8)
        lock.setblocking(False)
    except OSError:
        sys.exit(0)  # already running
    Buddy(lock).root.mainloop()


if __name__ == "__main__":
    main()
