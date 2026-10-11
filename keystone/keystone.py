"""Browser-based projection-mapping controller for the HY300/TXCZ RK3326 projector.

Runs on the PC and serves a page to any browser on the LAN (laptop or phone). Two layers,
like any mapping tool:
- Warp: the projector's own SurfaceFlinger keystone. Corner offsets go in
  persist.sys.keystone.{lt,rt,lb,rb}; persist.sys.keystone.update=1 makes RenderEngine re-read them
  on the next frame it draws. persist.* props live in /data, so the warp survives reboots.
- Shape: a mask (circle, line, triangle, any polygon) drawn by helper/ProjMap.java, which runs on the
  projector via app_process and owns full-screen layers above everything (the mask, and the alignment
  grid below it). The mask is composited before the keystone, so shapes live in image pixels and
  follow the warp. It lasts while this runs.

With --stream (ProjectorControl.bat) it also starts this PC's Sunshine desktop stream in Moonlight,
and the page's grid button switches the projector between the grid and the stream.

Usage: python keystone.py [--device 192.168.1.10:5555] [--port 8300] [--stream HOST_UUID]
       python keystone.py --selftest
"""
import argparse
import json
import math
import os
import queue
import socket
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(HERE, "presets.json")
DEX = os.path.join(HERE, "projmap.dex")  # built from helper/ProjMap.java by helper/build.py
NAMES = ("lt", "rt", "lb", "rb")
HELPER_REMOTE = "/data/local/tmp/projmap.dex"
MOONLIGHT = "com.limelight"
P2P_LISTEN = "wpa_cli -p /data/vendor/wifi/wpa/sockets -i p2p-dev-wlan0 p2p_ext_listen"  # no args: off
END = "__keystone_end__"

DEV = "192.168.1.10:5555"
STREAM = None  # Moonlight's UUID for this PC's Sunshine host, set by --stream
W, H = 1280, 720  # replaced by `wm size` at startup
grid_on = False
current = {"shape": None}  # the page's shape description, set at startup and by /apply
presets_lock = threading.Lock()


# --- coordinates & validation ----------------------------------------------------
# The page works in screen pixels (origin top-left, y down). SurfaceFlinger wants
# each corner as an offset from its own panel corner with y pointing UP:
# TXCZ's factory 90% zoom is lt=64,-36 rb=-64,36.

def _bases(w, h):
    return ((0, 0), (w, 0), (0, h), (w, h))


def to_offsets(corners, w, h):
    return [(x - bx, by - y) for (x, y), (bx, by) in zip(corners, _bases(w, h))]


def from_offsets(offsets, w, h):
    return [(bx + ox, by - oy) for (ox, oy), (bx, by) in zip(offsets, _bases(w, h))]


def _num(n):
    return type(n) is int or (type(n) is float and math.isfinite(n))


def _pair(p):
    return isinstance(p, list) and len(p) == 2 and _num(p[0]) and _num(p[1])


def parse_corners(v, w, h):
    """Validate client corners (they end up in root commands): 4 [x, y] numbers -> clamped ints."""
    if not (isinstance(v, list) and len(v) == 4 and all(_pair(p) for p in v)):
        raise ValueError("corners must be 4 [x, y] number pairs")
    return [(min(max(round(x), 0), w), min(max(round(y), 0), h)) for x, y in v]


def parse_polygon(v, w, h):
    """Mask outline in image pixels. It goes on a root process's command line, so numbers only."""
    if not (isinstance(v, list) and 3 <= len(v) <= 256 and all(_pair(p) for p in v)):
        raise ValueError("polygon must be 3-256 [x, y] number pairs")
    return [(round(min(max(x, -w), 2 * w), 1), round(min(max(y, -h), 2 * h), 1)) for x, y in v]


def parse_shape(s):
    """The page's shape description (image pixels), kept for presets and other clients:
    sides 1 = circle {c, r}, 2 = line {pts, w}, 3-12 = polygon {pts}."""
    ok = isinstance(s, dict) and type(s.get("sides")) is int and 1 <= s["sides"] <= 12
    if ok and s["sides"] == 1:
        ok = _pair(s.get("c")) and _num(s.get("r"))
        keys = ("c", "r")
    elif ok:
        pts = s.get("pts")
        ok = isinstance(pts, list) and len(pts) == s["sides"] and all(_pair(p) for p in pts)
        ok = ok and (s["sides"] != 2 or _num(s.get("w")))
        keys = ("pts", "w") if s["sides"] == 2 else ("pts",)
    if not ok:
        raise ValueError("bad shape")
    return {"sides": s["sides"], "on": s.get("on") is True, **{k: s[k] for k in keys}}


def _parse_xy(s):
    try:
        x, y = s.split(",")
        return int(x), int(y)
    except ValueError:
        return 0, 0


# --- adb -----------------------------------------------------------------------

def adb(*args, timeout=30):
    return subprocess.run(["adb", "-s", DEV, *args], capture_output=True, text=True, timeout=timeout).stdout


def ensure_root():
    subprocess.run(["adb", "connect", DEV], capture_output=True, timeout=10)
    if adb("shell", "id -u", timeout=10).strip() != "0":
        adb("root", timeout=10)
        time.sleep(2)  # adbd restarts as root and drops the wifi connection
        subprocess.run(["adb", "connect", DEV], capture_output=True, timeout=10)
        adb("wait-for-device", timeout=15)


class AdbPipe:
    """A long-lived process on the projector, talked to line by line, so a drag doesn't spawn a
    process per update. Restarts it (reconnecting adb) once if it died or stopped answering."""

    def __init__(self, command="", stderr=subprocess.DEVNULL):
        self.command, self.stderr = command, stderr
        self.p = self.q = None
        self.lock = threading.Lock()

    def _start(self):
        ensure_root()
        self.p = subprocess.Popen(["adb", "-s", DEV, "shell", *([self.command] if self.command else [])],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr)
        self.q = q = queue.Queue()
        out = self.p.stdout

        def pump():
            for line in iter(out.readline, b""):
                q.put(line)
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()

    def _line(self, timeout):
        line = self.q.get(timeout=timeout)
        if line is None:
            raise OSError("adb shell exited")
        return line.decode(errors="replace").rstrip("\r\n")

    def _talk(self, text, read, timeout=8):
        with self.lock:
            for attempt in range(2):
                try:
                    if self.p is None or self.p.poll() is not None:
                        self._start()
                    self.p.stdin.write(text.encode())  # bytes: Windows text pipes would send \r\n
                    self.p.stdin.flush()
                    return read(timeout)
                except (OSError, queue.Empty, subprocess.SubprocessError) as e:
                    if self.p:
                        self.p.kill()
                    self.p = None
                    if attempt:
                        raise ConnectionError(f"projector unreachable ({e or 'timeout'})") from e

    def close(self):
        with self.lock:
            if self.p:
                self.p.stdin.close()
                self.p.wait(5)


class Shell(AdbPipe):
    """`adb shell`: each command ends with an echo marker, and run() returns the lines before it."""

    def run(self, cmd):
        def read(timeout):
            lines = []
            while (line := self._line(timeout)) != END:
                lines.append(line)
            return lines
        # newline, not ';', before the marker: `cmd &; echo` is a syntax error
        return self._talk(f"{cmd}\necho {END}\n", read)


class Helper(AdbPipe):
    """ProjMap (helper/ProjMap.java) via app_process: one "ok"/"err ..." reply per command line."""

    def __init__(self):
        super().__init__(stderr=subprocess.STDOUT)  # so a failed start can say why

    def _start(self):
        self.command = f"CLASSPATH={HELPER_REMOTE} exec app_process / ProjMap {W} {H}"  # W, H known by now
        super()._start()
        seen = []
        try:
            while (line := self._line(30)) != "ready":  # the VM takes ~2.5s to start
                seen.append(line)
        except OSError as e:
            raise OSError(f"helper failed to start: {' | '.join(seen[-3:]) or e}") from e

    def run(self, *cmds):
        def read(timeout):
            errs, n = [], 0
            while n < len(cmds):
                line = self._line(timeout)
                if line == "ok" or line.startswith("err "):  # skip anything else the VM prints
                    n += 1
                    errs += [line[4:]] if line != "ok" else []
            if errs:
                raise ValueError("projector helper: " + "; ".join(errs))
        self._talk("".join(c + "\n" for c in cmds), read)


SH = Shell()
HELPER = Helper()


# --- projector operations ------------------------------------------------------

written = {}  # prop -> value last written, so a drag only re-sets the corners that moved
mask_sent = "mask off"


def read_corners():
    out = SH.run("; ".join(f"getprop persist.sys.keystone.{n}; getprop persist.sys.keystone.{n}.init.xy"
                           for n in NAMES))
    out += [""] * (8 - len(out))
    live = [_parse_xy(out[i]) for i in range(0, 8, 2)]
    factory = [_parse_xy(out[i]) for i in range(1, 8, 2)]
    written.clear()
    written.update({n: f"{x},{y}" for n, (x, y) in zip(NAMES, live)})
    return from_offsets(live, W, H), from_offsets(factory, W, H)


def apply(corners, force=False):
    vals = {n: f"{ox},{oy}" for n, (ox, oy) in zip(NAMES, to_offsets(corners, W, H))}
    changed = [n for n in NAMES if force or written.get(n) != vals[n]]
    if not changed:
        return
    # RenderEngine reads the corners only when it actually draws, and SurfaceFlinger's client-composition
    # cache skips drawing an unchanged screen (a plain repaint, SF 1004, got 1 of 20 updates read).
    # The helper's `redraw` flips global saturation 1.0 <-> 0.999 (invisible) so every update draws.
    HELPER.run(*(f"prop persist.sys.keystone.{n} {vals[n]}" for n in changed),
               "prop persist.sys.keystone.update 1", "redraw")
    written.update(vals)


def set_mask(polygon):
    """polygon=None removes the mask."""
    global mask_sent
    cmd = "mask off" if polygon is None else "mask " + " ".join(f"{x:g} {y:g}" for x, y in polygon)
    if cmd != mask_sent:
        HELPER.run(cmd)
        mask_sent = cmd


# A page sends updates far faster than the device applies them (~15/s). Requests only merge into
# `pending`; one worker applies the newest state back to back, so stale positions never queue up.
# 0.4s after the last corner change it re-sends all four corners once: SurfaceFlinger can reset
# `update` just after we set it, dropping that update, and this makes the final state exact.
pending = {}
pending_cv = threading.Condition()
apply_error = None


def request(**job):
    with pending_cv:
        pending.update(job)
        pending_cv.notify()


def applier():
    global apply_error
    settle = None  # corners to re-send once things go quiet
    while True:
        with pending_cv:
            if not pending:
                pending_cv.wait(None if settle is None else 0.4)
            job = dict(pending)
            pending.clear()
        try:
            if "corners" in job:
                settle = job["corners"]
                apply(settle)
            if "polygon" in job:
                set_mask(job["polygon"])
            if not job and settle is not None:
                apply(settle, force=True)
                settle = None
            apply_error = None
        except Exception as e:  # keep the worker alive; a dead worker would silently stop all syncing
            apply_error = str(e)


def set_grid(on):
    """The helper's grid layer covers everything but the mask. A running stream keeps going underneath."""
    global grid_on
    HELPER.run("grid on" if on else "grid off")
    grid_on = on


def start_stream():
    """Wake the projector and (re)start the Sunshine "Desktop" stream through Moonlight's shortcut activity.
    Wi-Fi Direct extended listen (what keeps the projector visible to Win+K/Miracast) takes the radio to
    another channel for 500 ms of every 1000, which stalls the stream every second. It stays off while
    Moonlight runs: a detached loop turns it back on once Moonlight's process is gone, however the stream ends."""
    # ponytail: the loop waits for the process, not the stream; Moonlight left cached keeps Miracast hidden until it dies
    SH.run(f"input keyevent KEYCODE_WAKEUP; am force-stop {MOONLIGHT}; {P2P_LISTEN} >/dev/null; "
           f"am start -n {MOONLIGHT}/.ShortcutTrampoline --es UUID {STREAM} --es AppName Desktop >/dev/null\n"
           f"setsid sh -c 'sleep 10; while pidof {MOONLIGHT} >/dev/null; do sleep 2; done; {P2P_LISTEN} 500 1000' "
           f"</dev/null >/dev/null 2>&1 &")


# --- presets -------------------------------------------------------------------

def load_presets():
    try:
        with open(PRESETS, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_preset(name, corners, shape):
    """corners=None deletes the preset."""
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 40:
        raise ValueError("preset name must be 1-40 characters")
    name = name.strip()
    with presets_lock:
        p = load_presets()
        if corners is None:
            p.pop(name, None)
        else:
            p[name] = {"corners": parse_corners(corners, W, H), "shape": parse_shape(shape)}
        tmp = PRESETS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(p, f, indent=1)
        os.replace(tmp, PRESETS)  # atomic: a crash mid-write can't wipe existing presets
    return p


# --- http ------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: a drag sends ~25 requests/s

    def log_message(self, *args):
        pass

    def reply(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path == "/":
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self.reply(200, f.read(), "text/html; charset=utf-8")
            if self.path == "/state":
                corners, factory = read_corners()
                return self.reply(200, {"w": W, "h": H, "corners": corners, "factory": factory,
                                        "shape": current["shape"], "presets": load_presets(), "grid": grid_on,
                                        "stream": bool(STREAM)})
            self.reply(404, {"error": "not found"})
        except ConnectionError as e:
            self.reply(502, {"error": str(e)})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                return self.reply(413, {"error": "request too large"})
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            if self.path == "/apply":
                corners, shape = parse_corners(body.get("corners"), W, H), parse_shape(body.get("shape"))
                polygon = parse_polygon(body.get("polygon"), W, H) if shape["on"] else None
                current["shape"] = shape
                request(corners=corners, polygon=polygon)
                return self.reply(200, {"ok": True, "error": apply_error})
            if self.path == "/grid":
                set_grid(bool(body.get("on")))
                return self.reply(200, {"grid": grid_on})
            if self.path == "/presets":
                p = save_preset(body.get("name"), body.get("corners"), body.get("shape"))
                return self.reply(200, {"presets": p})
            self.reply(404, {"error": "not found"})
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except ConnectionError as e:
            self.reply(502, {"error": str(e)})


class DualStackServer(ThreadingHTTPServer):
    """IPv6 + IPv4 on one socket. IPv4-only made every `localhost` connection on Windows try ::1
    first and wait ~0.2-1s for it to fail."""
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((DEV.split(":")[0], 9))  # UDP connect sends nothing; it just picks the route
        return s.getsockname()[0]


def wait_keys(url):
    """--stream console: C opens the page, Q returns. Polled: a blocking getwch() holds Ctrl+C back until the next key."""
    import msvcrt  # Windows only, like ProjectorControl.bat
    while True:
        if not msvcrt.kbhit():
            time.sleep(0.1)
            continue
        key = msvcrt.getwch().lower()
        if key in "\x00\xe0":  # arrows, F-keys etc. send a second code, and PgDn's is "Q"
            msvcrt.getwch()
        elif key == "c":
            webbrowser.open(url)
        elif key == "q":
            return


def main():
    global DEV, W, H, STREAM
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default=DEV, help="projector adb address (default %(default)s)")
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--stream", metavar="HOST_UUID", help="also stream this PC's desktop (Moonlight's UUID for it)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    DEV, STREAM = args.device, args.stream
    if not os.path.exists(DEX):
        raise SystemExit("projmap.dex is missing: run  python helper/build.py")

    print(f"Connecting to {DEV} ...")
    size = [l for l in SH.run("wm size") if "size:" in l][-1]  # Override size wins if set
    W, H = map(int, size.split(":")[1].strip().split("x"))
    if STREAM:
        start_stream()
    current["shape"] = {"sides": 1, "on": False, "c": [W // 2, H // 2], "r": H * 2 // 5}
    adb("push", DEX, HELPER_REMOTE)
    print("Starting the projector helper ...")
    HELPER.run("mask off")  # starts it now, so the first drag doesn't wait for its VM
    srv = DualStackServer(("::", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"Projector panel {W}x{H}. Open on this PC:  {url}")
    print(f"                       on your phone:  http://{lan_ip()}:{args.port}")
    print("Streaming. C opens the controls, Q stops the stream." if STREAM else "Ctrl+C to stop.",
          "The warp stays on the projector; the shape mask lasts while this runs.")
    threading.Thread(target=applier, daemon=True).start()
    try:
        if STREAM:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            wait_keys(url)
        else:
            webbrowser.open(url)
            srv.serve_forever()
    except KeyboardInterrupt:
        pass
    HELPER.close()  # the helper resets saturation and removes the mask and grid as it exits


def selftest():
    w, h = 1280, 720
    live = [(134, -36), (-104, -66), (66, 38), (-66, 38)]  # read off the projector
    assert from_offsets(live, w, h) == [(134, 36), (1176, 66), (66, 682), (1214, 682)]
    assert to_offsets(from_offsets(live, w, h), w, h) == live
    assert to_offsets([(64, 36), (1216, 36), (64, 684), (1216, 684)], w, h) == \
        [(64, -36), (-64, -36), (64, 36), (-64, 36)]  # TXCZ factory 90% zoom
    assert parse_corners([[-5, 9999], [1.6, 2], [0, 0], [10 ** 400, 720]], w, h) == \
        [(0, 720), (2, 2), (0, 0), (1280, 720)]
    ok = [[0, 0]] * 3
    bad_points = ([["1;reboot", 0]] + ok, [[True, 0]] + ok, [[float("nan"), 0]] + ok, [[0, 0, 0]] + ok, None, [])
    for parse, bad_count in ((parse_corners, ok), (parse_polygon, ok[:2])):
        for bad in (bad_count, *bad_points):
            try:
                parse(bad, w, h)
            except ValueError:
                continue
            raise AssertionError(f"{parse.__name__} accepted {bad!r}")
    assert parse_polygon([[-5000, 1.26], [10 ** 400, 0], [3, 3]], w, h) == [(-1280, 1.3), (2560, 0), (3, 3)]
    assert parse_shape({"sides": 1, "on": 1, "c": [1, 2], "r": 3, "x": 9}) == {"sides": 1, "on": False, "c": [1, 2], "r": 3}
    assert parse_shape({"sides": 2, "on": True, "pts": [[0, 0], [1, 1]], "w": 5})["w"] == 5
    for bad in (None, {"sides": 0}, {"sides": 13, "pts": []}, {"sides": 3, "pts": [[0, 0]] * 2},
                {"sides": 2, "pts": [[0, 0]] * 2}, {"sides": 1, "c": [0, 0], "r": "1"}, {"sides": True, "c": [0, 0], "r": 1}):
        try:
            parse_shape(bad)
        except ValueError:
            continue
        raise AssertionError(f"parse_shape accepted {bad!r}")

    # applier: a burst collapses to the newest state, then one forced settle pass re-sends the corners
    global apply, set_mask
    real, calls = (apply, set_mask), []
    apply = lambda q, force=False: (calls.append((q, force)), time.sleep(0.05))
    set_mask = lambda poly: calls.append(("mask", poly))
    threading.Thread(target=applier, daemon=True).start()
    for i in range(20):
        request(corners=[(i, 0)] * 4, polygon=None if i < 19 else [(i, 0)] * 3)
        time.sleep(0.005)
    time.sleep(0.7)
    apply, set_mask = real
    assert calls[-3:] == [([(19, 0)] * 4, False), ("mask", [(19, 0)] * 3), ([(19, 0)] * 4, True)], calls
    assert len(calls) < 20 and all(c[1] is not True for c in calls[:-1]), calls

    # --stream console keys: PgDn (\xe0 Q) and F9 (\x00 C) must not stop or open anything
    import sys, types
    keys, opened, real = list("\xe0Q\x00Cxc") + ["Q"], [], (sys.modules.get("msvcrt"), webbrowser.open)
    sys.modules["msvcrt"] = types.SimpleNamespace(kbhit=lambda: True, getwch=lambda: keys.pop(0))
    webbrowser.open = opened.append
    wait_keys("u")
    sys.modules["msvcrt"], webbrowser.open = real
    assert opened == ["u"] and not keys, (opened, keys)
    print("selftest ok")


if __name__ == "__main__":
    main()
