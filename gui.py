#!/usr/bin/env python3
"""Advanced GUI for Android Root & Recovery Toolkit (tkinter, stdlib only)."""
import json
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import rootkit as core  # reuse adb/fastboot core

BASE = Path(__file__).parent
DEVDB = BASE / "devices.json"

BRAND_GUIDES = {
    "samsung": ("Samsung (Odin/Heimdall)\n"
        "1. Dev options > OEM unlocking + USB debugging ON\n"
        "2. Power off, hold Vol Up+Vol Down, plug USB -> Download Mode\n"
        "3. Long-press Vol Up to unlock (wipes data, trips Knox 0x1 forever)\n"
        "4. Flash TWRP .tar via Odin AP slot (disable Auto-Reboot)\n"
        "5. Boot to recovery with buttons, flash Magisk / patched AP."),
    "xiaomi": "Xiaomi/Redmi/POCO\n1. Dev options > Mi Unlock status > bind Mi account\n2. Wait 7 days, use Mi Unlock Tool (Windows)\n3. fastboot flash recovery twrp.img",
    "google": "Pixel / OnePlus / Motorola / Nothing\n1. adb reboot bootloader\n2. fastboot flashing unlock (confirm on device, wipes data)\n3. fastboot flash recovery twrp.img / fastboot flash boot magisk.img",
    "generic": "Generic fastboot\nadb reboot bootloader; fastboot flashing unlock; fastboot flash recovery recovery.img",
}

class LogPanel:
    def __init__(self, text: tk.Text):
        self.text = text
        self.q: queue.Queue[str] = queue.Queue()
        self._poll()
    def write(self, s: str):
        self.q.put(s)
    def _poll(self):
        try:
            while True:
                s = self.q.get_nowait()
                self.text.configure(state="normal")
                self.text.insert("end", s if s.endswith("\n") else s + "\n")
                self.text.see("end")
                self.text.configure(state="disabled")
        except queue.Empty:
            pass
        self.text.after(120, self._poll)

def run_async(fn):
    def wrap(*a, **k):
        threading.Thread(target=fn, args=a, kwargs=k, daemon=True).start()
    return wrap

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Android Root & Recovery Toolkit — Advanced GUI")
        self.geometry("980x680")
        self.props: dict = {}
        self._build_style()
        self._build_layout()

    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Title.TLabel", font=("Segoe UI", 13, "bold"))
        st.configure("Warn.TLabel", foreground="#b00020")
        st.configure("Ok.TLabel", foreground="#0a7d2c")

    def _build_layout(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Android Root & Recovery Toolkit", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  Official unlock only — Knox trip is irreversible",
                  style="Warn.TLabel").pack(side="left", padx=10)
        ttk.Button(top, text="Refresh device", command=self.on_refresh).pack(side="right")
        ttk.Button(top, text="Check deps", command=self.on_deps).pack(side="right", padx=5)

        self.status = tk.StringVar(value="No device. Enable USB debugging, connect USB.")
        ttk.Label(self, textvariable=self.status, padding=(10, 0)).pack(fill="x")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_dash = ttk.Frame(nb, padding=10)
        self.tab_diag = ttk.Frame(nb, padding=10)
        self.tab_sam = ttk.Frame(nb, padding=10)
        self.tab_flash = ttk.Frame(nb, padding=10)
        self.tab_root = ttk.Frame(nb, padding=10)
        nb.add(self.tab_dash, text="Dashboard")
        nb.add(self.tab_diag, text="Diagnose")
        nb.add(self.tab_sam, text="Samsung / OEM fix")
        nb.add(self.tab_flash, text="Flash recovery")
        nb.add(self.tab_root, text="Root (Magisk)")

        self._build_dash()
        self._build_diag()
        self._build_sam()
        self._build_flash()
        self._build_root()

        logf = ttk.LabelFrame(self, text="Log", padding=5)
        logf.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        self.log_text = tk.Text(logf, height=9, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        self.log = LogPanel(self.log_text)
        self.log.write("Ready. Click Refresh device.")

    # ---- dashboard ----
    def _build_dash(self):
        f = self.tab_dash
        ttk.Label(f, text="Dependencies (adb / fastboot / heimdall)").pack(anchor="w")
        self.dep_var = tk.StringVar(value="—")
        ttk.Label(f, textvariable=self.dep_var).pack(anchor="w", pady=2)
        ttk.Label(f, text="Connected devices").pack(anchor="w", pady=(8, 0))
        self.dev_list = tk.Listbox(f, height=4)
        self.dev_list.pack(fill="x")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=8)
        for label, cmd in [
            ("adb reboot", lambda: self._adb("reboot")),
            ("bootloader", lambda: self._adb("reboot bootloader")),
            ("recovery", lambda: self._adb("reboot recovery")),
            ("fastboot: reboot", lambda: self._fb("reboot")),
            ("fastboot: reboot recovery", lambda: self._fb("reboot recovery")),
        ]:
            ttk.Button(row, text=label, command=cmd).pack(side="left", padx=3)
        ttk.Label(f, text="Model database (devices.json) TWRP hint:").pack(anchor="w")
        self.tw_var = tk.StringVar(value="—")
        ttk.Label(f, textvariable=self.tw_var, wraplength=900).pack(anchor="w")

    # ---- diagnose ----
    def _build_diag(self):
        f = self.tab_diag
        btn = ttk.Frame(f)
        btn.pack(fill="x")
        ttk.Button(btn, text="Full diagnose", command=self.on_diagnose).pack(side="left")
        ttk.Button(btn, text="Verify root (su)", command=self.on_verify_root).pack(side="left", padx=5)
        self.diag_summary = tk.StringVar(value="Not diagnosed yet.")
        ttk.Label(f, textvariable=self.diag_summary, style="Warn.TLabel", wraplength=900).pack(anchor="w", pady=5)
        cols = ("key", "value")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=14)
        self.tree.heading("key", text="Property")
        self.tree.heading("value", text="Value")
        self.tree.column("key", width=320)
        self.tree.column("value", width=600)
        self.tree.pack(fill="both", expand=True)

    # ---- samsung ----
    def _build_sam(self):
        f = self.tab_sam
        ttk.Label(f, text="KNOX WARNING: first custom flash trips Knox to 0x1 permanently. "
                  "No software bypass keeps 0x0. Secure Folder / Samsung Pay break forever.",
                  style="Warn.TLabel", wraplength=900).pack(anchor="w", pady=5)
        ttk.Label(f, text="OEM-toggle repair (only restores toggle when eligible — "
                  "does NOT bypass carrier / KG / RMM lock):").pack(anchor="w")
        steps = ("SIM removed, WiFi on, Google+Samsung login",
                 "Date set 10-14 days back, auto-update OFF",
                 "Software update > Check, reboot, recheck Dev options",
                 "Date back to Automatic, reboot, 7-day uptime / KG Checking passes")
        self.chk_vars = []
        for s in steps:
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(f, text=s, variable=v).pack(anchor="w")
            self.chk_vars.append(v)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="1. Check MDM / lock state", command=self.on_mdm).pack(side="left", padx=3)
        ttk.Button(row, text="2. Disable auto-time (adb)", command=self.on_disable_autotime).pack(side="left", padx=3)
        ttk.Button(row, text="3. Reboot device", command=lambda: self._adb("reboot")).pack(side="left", padx=3)
        ttk.Label(f, text="Samsung unlock steps:").pack(anchor="w", pady=(8, 0))
        self.sam_guide = tk.Text(f, height=8, font=("Consolas", 9))
        self.sam_guide.pack(fill="both", expand=True)
        self.sam_guide.insert("end", BRAND_GUIDES["samsung"])

    # ---- flash ----
    def _build_flash(self):
        f = self.tab_flash
        ttk.Label(f, text="Select recovery image for your EXACT model (TWRP: https://twrp.me/Devices/)").pack(anchor="w")
        r = ttk.Frame(f)
        r.pack(fill="x", pady=5)
        self.img_var = tk.StringVar()
        ttk.Entry(r, textvariable=self.img_var).pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="Browse…", command=self.on_browse).pack(side="left", padx=5)
        r2 = ttk.Frame(f)
        r2.pack(fill="x", pady=5)
        ttk.Label(r2, text="Partition:").pack(side="left")
        self.part_var = tk.StringVar(value="recovery")
        ttk.Combobox(r2, textvariable=self.part_var,
                     values=["recovery", "boot", "init_boot", "vendor_boot", "recovery_a", "recovery_b"],
                     width=15, state="readonly").pack(side="left", padx=5)
        ttk.Label(r2, text="Samsung uses .tar via Odin AP / heimdall").pack(side="left", padx=10)
        ttk.Button(f, text="Flash recovery (wipes nothing, but unlock wipes)",
                   command=self.on_flash).pack(anchor="w", pady=5)
        self.flash_hint = tk.StringVar(value="Non-Samsung: device must be in fastboot mode.")
        ttk.Label(f, textvariable=self.flash_hint, wraplength=900).pack(anchor="w")

    # ---- root ----
    def _build_root(self):
        f = self.tab_root
        ttk.Label(f, text="Systemless root via Magisk (backup boot first in TWRP)").pack(anchor="w")
        t = tk.Text(f, height=9, font=("Consolas", 9))
        t.pack(fill="both", expand=True, pady=5)
        t.insert("end",
            "1. Pull stock boot.img for your exact build\n"
            "2. Install Magisk app (https://github.com/topjohnwu/Magisk) > patch boot.img / AP.tar\n"
            "3. fastboot flash boot magisk-patched.img  (Samsung: flash patched AP via Odin)\n"
            "4. Reboot, verify with button below\n"
            "Note: Play Integrity / banking apps may fail on unlocked devices.")
        t.configure(state="disabled")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=5)
        ttk.Button(row, text="Pull boot.img (adb)", command=self.on_pull_boot).pack(side="left", padx=3)
        ttk.Button(row, text="Verify root", command=self.on_verify_root).pack(side="left", padx=3)

    # ---- handlers ----
    @run_async
    def on_deps(self):
        deps = {t: bool(shutil.which(t)) for t in ["adb", "fastboot", "heimdall"]}
        self.dep_var.set(" | ".join(f"{k}: {'OK' if v else 'MISSING'}" for k, v in deps.items()))
        self.log.write(f"deps: {self.dep_var.get()}")
        if not deps["adb"]:
            self.log.write("Install: winget install Google.PlatformTools, add to PATH.")

    @run_async
    def on_refresh(self):
        self.on_deps.__wrapped__(self)
        devs = core.adb_devices()
        fdevs = core.fastboot_devices()
        self.dev_list.delete(0, "end")
        for d in devs:
            self.dev_list.insert("end", f"adb: {d[0]} [{d[1]}]")
        for d in fdevs:
            self.dev_list.insert("end", f"fastboot: {d}")
        if devs:
            self.status.set(f"{len(devs)} adb device(s). Running quick props…")
            self.props = core.getprops()
            model = self.props.get("ro.product.model", "?")
            mfr = self.props.get("ro.product.manufacturer", "?")
            self.status.set(f"{mfr} {model} | Android {self.props.get('ro.build.version.release','?')}")
            self.log.write(f"connected: {mfr} {model} device={self.props.get('ro.product.device')}")
            self._update_twrp_hint()
        else:
            self.status.set("No adb device. Fastboot only?" if fdevs else "No device. Enable USB debugging + authorize.")
            self.log.write("no adb device found.")

    def _update_twrp_hint(self):
        try:
            db = json.loads(DEVDB.read_text(encoding="utf-8"))
        except Exception as e:
            self.tw_var.set(f"devices.json unreadable: {e}")
            return
        model = (self.props.get("ro.product.model", "") or "").lower()
        hit = next((v for k, v in db.items() if k.startswith("_") is False and model and model in k.lower()), None)
        if hit:
            self.tw_var.set(f"{hit.get('recovery_note','')} | {hit.get('twrp_url','')}")
        else:
            self.tw_var.set("No DB entry for this model. Get exact TWRP at https://twrp.me/Devices/ for your model/device code.")

    @run_async
    def on_diagnose(self):
        props = core.getprops()
        if not props:
            self.diag_summary.set("No adb device.")
            return
        self.props = props
        for i in self.tree.get_children():
            self.tree.delete(i)
        for k in sorted(props):
            if k.startswith("ro.") or k.startswith("sys.") or "oem" in k or "knox" in k.lower() or "warranty" in k:
                self.tree.insert("", "end", values=(k, props[k]))
        oem = core.get_setting("global", "oem_unlock_allowed")
        self.tree.insert("", "end", values=("settings global oem_unlock_allowed", oem or "(null)"))
        brand = (props.get("ro.product.manufacturer", "") + props.get("ro.product.brand", "")).lower()
        wb = props.get("ro.boot.warranty_bit", "")
        lock = props.get("ro.boot.flash.locked", "")
        msgs = []
        if "samsung" in brand:
            msgs.append("Samsung: Knox bit=" + (wb or "?") + (" (TRIPPED, permanent)" if wb == "1" else " (will trip on unlock)" if wb == "0" else ""))
        msgs.append("bootloader " + ("locked" if lock == "1" else "unlocked" if lock == "0" else "state unknown"))
        msgs.append("OEM toggle " + ("OFF/missing — use Samsung/OEM-fix tab" if oem in ("", "null", "0") else "allowed"))
        self.diag_summary.set(" | ".join(msgs))
        self.log.write("diagnose: " + " | ".join(msgs))
        self._update_twrp_hint()

    @run_async
    def on_mdm(self):
        _, out, _ = core.run("adb shell dumpsys device_policy_manager | grep -i -m5 admin")
        _, kg, _ = core.run("adb shell getprop ro.boot.warranty_bit; adb shell getprop ro.boot.flash.locked")
        self.log.write("MDM/policy:\n" + (out or "(none found — good)"))
        self.log.write("lock props:\n" + (kg or "?"))
        if out and ("owner" in out.lower() or "profile" in out.lower()):
            messagebox.showwarning("MDM found", "Work profile / device owner detected. Remove it or OEM toggle stays hidden.")

    @run_async
    def on_disable_autotime(self):
        core.run("adb shell settings put global auto_time 0")
        core.run("adb shell settings put global auto_time_zone 0")
        self.log.write("Disabled auto_time. Now set date 10-14 days back in Settings manually.")

    def on_browse(self):
        p = filedialog.askopenfilename(filetypes=[("Recovery", "*.img *.tar *.tar.md5"), ("All", "*.*")])
        if p:
            self.img_var.set(p)
            if p.lower().endswith((".tar", ".md5")):
                self.flash_hint.set("Samsung .tar selected: use Odin AP slot (disable Auto-Reboot) or heimdall.")
            else:
                self.flash_hint.set("Non-Samsung .img: device must be in fastboot mode.")

    @run_async
    def on_flash(self):
        img = self.img_var.get().strip().strip('"')
        if not img or not Path(img).exists():
            messagebox.showerror("No image", "Pick a valid recovery image first.")
            return
        brand = (self.props.get("ro.product.manufacturer", "") + self.props.get("ro.product.brand", "")).lower()
        is_sam = "samsung" in brand
        if not messagebox.askyesno("Confirm flash", f"Flash {Path(img).name} to {self.part_var.get()}?\nMake sure the image matches your EXACT model."):
            return
        if is_sam and not img.lower().endswith((".tar", ".md5")):
            messagebox.showinfo("Samsung needs .tar", "Convert: tar -H ustar -c recovery.img > recovery.tar, then flash via Odin AP.")
            return
        if is_sam:
            if shutil.which("heimdall"):
                c, o, e = core.run(f'heimdall flash --RECOVERY "{img}"')
                self.log.write(o or e or f"exit {c}")
            else:
                self.log.write("heimdall missing. Open Odin: AP slot -> .tar, disable Auto-Reboot, flash, then button-combo to recovery.")
                messagebox.showinfo("Use Odin", "heimdall not found. Flash the .tar in Odin AP manually.")
        else:
            c, o, e = core.run(f'fastboot flash {self.part_var.get()} "{img}"')
            self.log.write(o or e or f"exit {c}")
            if c == 0:
                self.log.write("OK. Run: fastboot reboot recovery")

    @run_async
    def on_pull_boot(self):
        c, o, e = core.run("adb shell ls /sdcard/boot.img; adb shell su -c id")
        self.log.write(o or e or "")
        self.log.write("Copy stock boot.img for your exact build to phone, patch in Magisk app, then fastboot flash it back.")

    @run_async
    def on_verify_root(self):
        c, o, e = core.run("adb shell su -c id")
        if c == 0 and "uid=0" in o:
            self.log.write("ROOT OK: " + o)
            messagebox.showinfo("Root", "Root OK: " + o)
        else:
            self.log.write("No root: " + (o or e or "su not found"))
            messagebox.showinfo("Root", "No root (su not granted).")

    @run_async
    def _adb(self, args):
        c, o, e = core.run(f"adb {args}")
        self.log.write((o or e or f"adb {args} -> exit {c}"))

    @run_async
    def _fb(self, args):
        c, o, e = core.run(f"fastboot {args}")
        self.log.write((o or e or f"fastboot {args} -> exit {c}"))

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
