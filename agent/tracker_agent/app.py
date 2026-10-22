"""Tray app: samples every 5 s, uploads every 60 s, and shows its state at all times."""

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
from datetime import UTC, datetime, timedelta

import pystray
from PIL import Image, ImageDraw

from tracker_agent import __version__, config, setup_dialog, uploader, win
from tracker_agent.core import Coalescer, State, build_sample
from tracker_agent.local_server import DEFAULT_RULES, TabStore
from tracker_agent.local_server import start as start_local_server
from tracker_agent.outbox import Outbox

log = logging.getLogger("agent")
SAMPLE_S = 5
UPLOAD_S = 60
RULES_S = 600
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "ActivityTracker"
COLORS = {"tracking": "#12b76a", "paused": "#f79009", "private": "#667085", "disconnected": "#f04438"}
LABELS = {"tracking": "Tracking is on", "paused": "Paused", "private": "Private mode: no details recorded",
          "disconnected": "Not connected to the server"}


def icon_image(mode: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=COLORS[mode])
    d.rectangle((22, 18, 42, 24), fill="white")  # a simple "T" so it is recognisable at 16 px
    d.rectangle((29, 18, 35, 46), fill="white")
    return img


class Agent:
    def __init__(self, cfg: config.Config, tabs: TabStore):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.state = State(private=cfg.private, idle_threshold_s=cfg.idle_threshold_s, domain_only=cfg.domain_only,
                           paused_until=datetime.fromisoformat(cfg.paused_until) if cfg.paused_until else None)
        self.tabs = tabs
        config.APP_DIR.mkdir(parents=True, exist_ok=True)
        self.outbox = Outbox(config.QUEUE_FILE)
        self.coalescer = Coalescer(interval_s=SAMPLE_S)
        self.stop = threading.Event()
        self.upload_now = threading.Event()
        self.unauthorized = False
        self.last_sent: datetime | None = None
        self.last_error: str | None = None
        self.icon: pystray.Icon | None = None
        self._shown_mode: str | None = None
        self.rules: dict = dict(DEFAULT_RULES)

    # --- state -------------------------------------------------------------------------------------
    def mode(self) -> str:
        if self.unauthorized or not config.get_token():
            return "disconnected"
        with self.lock:
            if self.state.paused_until and datetime.now(UTC) < self.state.paused_until:
                return "paused"
            if self.state.private:
                return "private"
        return "tracking"

    def status(self) -> dict:
        return {"mode": self.mode(), "label": LABELS[self.mode()], "version": __version__, "server": self.cfg.server,
                "pending": self.outbox.count(),
                "last_sent": self.last_sent.isoformat() if self.last_sent else None}

    def _persist(self) -> None:
        with self.lock:
            self.cfg.private = self.state.private
            self.cfg.paused_until = self.state.paused_until.isoformat() if self.state.paused_until else None
        self.cfg.save()
        self.refresh_icon()

    def pause(self, minutes: int) -> None:
        with self.lock:
            self.state.paused_until = datetime.now(UTC) + timedelta(minutes=minutes)
        self._persist()

    def resume(self) -> None:
        with self.lock:
            self.state.paused_until = None
            self.state.private = False
        self._persist()

    def toggle_private(self) -> None:
        with self.lock:
            self.state.private = not self.state.private
        self._persist()

    # --- loops -------------------------------------------------------------------------------------
    def sample_loop(self) -> None:
        while not self.stop.wait(SAMPLE_S):
            try:
                app, title = win.foreground()
                now = datetime.now(UTC)
                with self.lock:
                    sample = build_sample(now, self.state, app, title, win.idle_seconds(), win.is_locked(),
                                          self.tabs.snapshot())
                    if self.state.paused_until and now >= self.state.paused_until:
                        self.state.paused_until = None
                self.outbox.put(self.coalescer.add(sample))
                self.refresh_icon()
            except Exception:
                log.exception("sample failed")

    def upload_once(self) -> None:
        token = config.get_token()
        if not token:
            return
        while events := self.outbox.peek():
            try:
                uploader.send_events(self.cfg.api, token, events)
            except uploader.Unauthorized:
                self.unauthorized = True
                self.last_error = "This PC was disconnected by an admin. Reconnect with a new setup code."
                self.refresh_icon()
                return
            except Exception as e:
                self.last_error = str(e)[:200]
                log.warning("upload failed: %s", self.last_error)
                return
            self.outbox.remove([e["seq"] for e in events])
            self.last_sent, self.last_error, self.unauthorized = datetime.now(UTC), None, False

    def refresh_rules(self) -> None:
        token = config.get_token()
        if not token:
            return
        try:
            self.rules = uploader.page_rules(self.cfg.api, token)
        except Exception as e:  # keep the last rules; uploads report connection problems
            log.info("page rules not refreshed: %s", e)

    def upload_loop(self) -> None:
        last_rules = 0.0
        while not self.stop.is_set():
            if time.monotonic() - last_rules > RULES_S:
                self.refresh_rules()
                last_rules = time.monotonic()
            self.upload_once()
            self.upload_now.wait(UPLOAD_S)
            self.upload_now.clear()

    # --- tray --------------------------------------------------------------------------------------
    def refresh_icon(self) -> None:
        mode = self.mode()
        if self.icon and mode != self._shown_mode:
            self._shown_mode = mode
            self.icon.icon = icon_image(mode)
            self.icon.title = f"Activity Tracker — {LABELS[mode]}"
            self.icon.update_menu()

    def reconnect(self) -> None:
        def run():
            if setup_dialog.run(self.cfg):
                self.unauthorized = False
                self.upload_now.set()
                self.refresh_icon()
        threading.Thread(target=run, daemon=True).start()

    def quit(self) -> None:
        self.stop.set()
        self.outbox.put(self.coalescer.flush())
        self.upload_once()
        self.outbox.close()
        if self.icon:
            self.icon.stop()

    def menu(self) -> pystray.Menu:
        Item, Menu = pystray.MenuItem, pystray.Menu

        def paused_text(_):
            with self.lock:
                until = self.state.paused_until
            return f"Paused until {until.astimezone().strftime('%H:%M')}" if until else ""

        def info_text(_):
            if self.last_error:
                return f"Last upload failed: {self.last_error[:60]}"
            n = self.outbox.count()
            sent = self.last_sent.astimezone().strftime("%H:%M") if self.last_sent else "not yet"
            return f"Last sent {sent}" + (f" · {n} waiting" if n else "")

        return Menu(
            Item(lambda _: LABELS[self.mode()], None, enabled=False),
            Item(paused_text, None, enabled=False, visible=lambda _: self.mode() == "paused"),
            Item(info_text, None, enabled=False),
            Menu.SEPARATOR,
            Item("Pause", Menu(*(Item(f"{m} minutes", (lambda m: lambda: self.pause(m))(m)) for m in (15, 30, 60)))),
            Item("Resume", lambda: self.resume(), visible=lambda _: self.mode() in ("paused", "private")),
            Item("Private mode", lambda: self.toggle_private(), checked=lambda _: self.state.private),
            Menu.SEPARATOR,
            Item("Open my day", lambda: webbrowser.open(self.cfg.server)),
            Item("Reconnect…", lambda: self.reconnect(), visible=lambda _: self.mode() == "disconnected"),
            Item("Start with Windows", lambda: set_autostart(not autostart_enabled()),
                 checked=lambda _: autostart_enabled(), visible=getattr(sys, "frozen", False)),
            Item(f"Quit (version {__version__})", lambda: self.quit()),
        )

    def run(self) -> None:
        threading.Thread(target=self.sample_loop, name="sampler", daemon=True).start()
        threading.Thread(target=self.upload_loop, name="uploader", daemon=True).start()
        mode = self.mode()
        self.icon = pystray.Icon("ActivityTracker", icon_image(mode), f"Activity Tracker — {LABELS[mode]}",
                                 self.menu())
        self._shown_mode = mode
        self.icon.run()


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


def relaunch() -> None:
    cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "tracker_agent"]
    # A one-file build started from another one-file build would otherwise reuse the parent's temporary
    # unpack folder, which is deleted when the parent exits.
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    subprocess.Popen(cmd, env=env, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def _log_crashes() -> None:
    """With --noconsole there is no stderr, so unhandled errors would vanish; send them to agent.log."""
    sys.excepthook = lambda t, e, tb: log.critical("unhandled error", exc_info=(t, e, tb))
    threading.excepthook = lambda a: log.critical("unhandled error in thread %s", a.thread.name if a.thread else "?",
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def main() -> int:
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=config.LOG_FILE, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    _log_crashes()
    if not win.single_instance():
        return 0  # already running; its tray icon is visible
    cfg = config.Config.load()
    # Listen for the extension straight away, so it can tell "agent not running" from "setup not finished".
    tabs = TabStore()
    running: dict[str, Agent] = {}

    def status() -> dict:
        if "agent" in running:
            return running["agent"].status()
        return {"mode": "setup", "label": "The agent is running but not connected yet. Finish its setup window.",
                "version": __version__, "server": cfg.server}

    server = None
    def page_rules() -> dict:
        return running["agent"].rules if "agent" in running else DEFAULT_RULES

    try:
        server = start_local_server(config.LOCAL_PORT, tabs, status, page_rules)
    except OSError:
        log.error("port %s is in use; the browser extension cannot reach the agent", config.LOCAL_PORT)
    if not config.get_token():
        if not setup_dialog.run(cfg):
            return 1
        log.info("setup done, device %s; restarting", cfg.device_id)
        if getattr(sys, "frozen", False):
            set_autostart(True)  # on after first setup; the person can switch it off in the tray menu
        # Start tracking in a fresh process: the tray icon must not share a process with the closed setup
        # window, and a normal start (already linked) is the well-trodden path.
        if server:
            server.shutdown()
            server.server_close()
        win.release_single_instance()
        relaunch()
        return 0
    log.info("agent %s started, device %s", __version__, cfg.device_id)
    running["agent"] = Agent(cfg, tabs)
    running["agent"].run()
    return 0
