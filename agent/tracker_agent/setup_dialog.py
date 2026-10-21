"""First-run window: explains what is collected, then links this PC to the person with their setup code."""

import tkinter as tk
from tkinter import ttk

from tracker_agent import config, uploader

NOTICE = (
    "Activity Tracker records, while it is running:\n"
    "  • which app and window is in front, and for how long\n"
    "  • the site and page title of the active browser tab (with the browser extension)\n"
    "  • when you are idle or the PC is locked\n\n"
    "It never records screenshots, keystrokes, the clipboard or page contents.\n"
    "Use Pause or Private mode in the tray icon at any time. You review your daily report before it is sent."
)


def run(cfg: config.Config) -> bool:
    """Shows the dialog; returns True once the device is enrolled."""
    result = {"ok": False}
    root = tk.Tk()
    root.title("Activity Tracker setup")
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=16)
    frm.grid()

    ttk.Label(frm, text="Connect this PC", font=("Segoe UI", 13, "bold")).grid(column=0, row=0, sticky="w")
    ttk.Label(frm, text=NOTICE, justify="left", wraplength=440).grid(column=0, row=1, sticky="w", pady=(8, 12))

    ttk.Label(frm, text="Server address").grid(column=0, row=2, sticky="w")
    server = tk.StringVar(value=cfg.server)
    ttk.Entry(frm, textvariable=server, width=52).grid(column=0, row=3, sticky="we")

    ttk.Label(frm, text="Setup code (from the Downloads page)").grid(column=0, row=4, sticky="w", pady=(10, 0))
    code = tk.StringVar()
    code_entry = ttk.Entry(frm, textvariable=code, width=52, font=("Consolas", 12))
    code_entry.grid(column=0, row=5, sticky="we")

    status = ttk.Label(frm, text="", foreground="#b42318", wraplength=440)
    status.grid(column=0, row=6, sticky="w", pady=(8, 0))

    def connect(*_):
        cfg.server = server.get().strip().rstrip("/")
        status.config(text="Connecting…", foreground="#475467")
        root.update_idletasks()
        try:
            res = uploader.enrol(cfg.api, code.get().strip())
        except Exception as e:  # network errors and server messages alike are shown to the person
            status.config(text=f"Could not connect: {e}", foreground="#b42318")
            return
        config.set_token(res["token"])
        cfg.device_id = res["device_id"]
        cfg.save()
        result["ok"] = True
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(column=0, row=7, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Cancel", command=root.destroy).grid(column=0, row=0, padx=(0, 8))
    ttk.Button(btns, text="Connect", command=connect).grid(column=1, row=0)
    root.bind("<Return>", connect)
    code_entry.focus_set()
    root.mainloop()
    return result["ok"]
