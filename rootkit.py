#!/usr/bin/env python3
"""
Android Root & Custom Recovery Toolkit
- Detects device by model (adb/fastboot)
- Official bootloader unlock flow only (no silent Knox/security bypass)
- Samsung: OEM-unlock repair helper, Download-mode/Odin-Heimdall guide, Knox warning
- Generic: fastboot unlock + TWRP flash + Magisk root guide

DISCLAIMER: Unlocking wipes data, voids warranty, trips Samsung Knox 0x1 permanently.
The Knox e-fuse CANNOT be reset or bypassed in software. This tool does NOT hide it.
Use only on devices you own.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
DEVDB = BASE / "devices.json"

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"

def have(tool):
    return shutil.which(tool) is not None

def check_deps():
    print("=== Dependency check ===")
    for t in ["adb", "fastboot"]:
        print(f"[{'OK' if have(t) else 'MISSING'}] {t}")
    if not have("adb"):
        print("Install Platform-Tools: https://developer.android.com/tools/releases/platform-tools")
        print("and add to PATH. On Windows: winget install Google.PlatformTools")
    for t in ["heimdall", "odin4", "magisk"]:
        if have(t):
            print(f"[OK optional] {t}")
    print()

def adb_devices():
    code, out, _ = run("adb devices -l")
    lines = [l for l in out.splitlines()[1:] if l.strip() and "devices" not in l.lower() or (l.strip() and "\t" in l)]
    # simpler: parse lines with device id
    devs = []
    for l in out.splitlines()[1:]:
        l=l.strip()
        if not l or l.startswith("*") or l.startswith("List"):
            continue
        parts = l.split()
        if len(parts) >= 2:
            devs.append((parts[0], parts[1], l))
    return devs

def fastboot_devices():
    code, out, _ = run("fastboot devices -l")
    devs = []
    for l in out.splitlines():
        l=l.strip()
        if l:
            devs.append(l)
    return devs

def getprops():
    props = {}
    code, out, _ = run("adb shell getprop")
    for line in out.splitlines():
        m = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    return props

def get_setting(namespace, key):
    _, out, _ = run(f"adb shell settings get {namespace} {key}")
    return out.strip()

def diagnose(props):
    print("=== Device diagnosis ===")
    keys = ["ro.product.manufacturer","ro.product.brand","ro.product.model","ro.product.device",
            "ro.product.name","ro.build.version.release","ro.build.version.sdk",
            "ro.boot.flash.locked","ro.boot.warranty_bit","ro.boot.verifiedbootstate",
            "sys.oem_unlock_allowed","ro.oem_unlock_supported","ro.secure","ro.debuggable"]
    for k in keys:
        if k in props:
            print(f"{k} = {props[k]}")
    # Samsung knox check
    _, kv, _ = run("adb shell getprop ro.boot.warranty_bit")
    _, kl, _ = run("adb shell cat /sys/class/sec/ Knox 2>&1 | head")
    oem_allowed = get_setting("global", "oem_unlock_allowed")
    dev_cfg = get_setting("global", "development_settings_enabled")
    print(f"settings global oem_unlock_allowed = {oem_allowed or '(null/unknown)'}")
    print(f"settings global development_settings_enabled = {dev_cfg or '(null/unknown)'}")
    brand = (props.get("ro.product.manufacturer","") + " " + props.get("ro.product.brand","")).lower()
    is_samsung = "samsung" in brand
    print()
    if is_samsung:
        print("Samsung detected.")
        wb = props.get("ro.boot.warranty_bit", kv).strip()
        if wb == "1":
            print("[!] Knox Warranty Bit = 1 -> Knox already tripped (0x1). Cannot be reset.")
        elif wb == "0":
            print("[*] Knox Warranty Bit = 0 (untripped). Unlocking/rooting WILL trip it to 1 permanently.")
        else:
            print("[?] Knox bit unknown. Assume unlocking will trip Knox permanently.")
        print("NOTE: There is no software bypass that keeps Knox 0x0 after custom flash. Any tool claiming that is false.")
    locked = props.get("ro.boot.flash.locked", "")
    if locked == "1":
        print("[*] Bootloader reports locked.")
    elif locked == "0":
        print("[*] Bootloader reports unlocked.")
    if not oem_allowed or oem_allowed in ("null","0"):
        print("[!] OEM unlocking toggle appears OFF or missing. Run 'repair-oem' helper.")
    print()
    return is_samsung

def repair_oem_toggle():
    """
    Known fix for missing Samsung 'OEM unlocking' toggle (carrier/RMM/KG state).
    Cannot unlock a carrier-locked or KG-locked device; only restores toggle when eligible.
    Official preconditions: SIM removed, WiFi connected, signed into Samsung+Google account,
    uptime 7+ days (168h), no MDM/KG lock.
    """
    print("=== OEM-unlock toggle repair helper ===")
    print("This does NOT bypass carrier/KG/RMM lock. It only restores the toggle when eligible.")
    print("Steps automated + manual:")
    print(" 1. Checking current state...")
    print(f"  oem_unlock_allowed = {get_setting('global','oem_unlock_allowed')}")
    _, out, _ = run("adb shell getprop ro.boot.flash.locked")
    print(f"  ro.boot.flash.locked = {out}")
    _, out2, _ = run("adb shell dumpsys device_policy_manager | grep -i -m5 'admin\\|owner\\|profile'")
    if out2:
        print("  device_policy (MDM check, first lines):")
        for l in out2.splitlines()[:5]:
            print("   ", l.strip())
        if "profile" in out2.lower() or "owner" in out2.lower():
            print("[!] Possible MDM/work profile — remove it, else OEM toggle will stay hidden.")
    print()
    print("Manual pre-steps (do these on phone):")
    print("  a) Remove SIM, connect to WiFi, sign into Google + Samsung account.")
    print("  b) Settings > General management > Date and time: disable Automatic, set date 10-14 days back.")
    print("  c) Settings > Software update: disable Auto download. Do NOT update.")
    print("  d) Settings > Developer options: enable, then check for 'OEM unlocking'.")
    print("  e) Settings > Software update > Check, then reboot. Recheck Developer options.")
    print("  f) Set date back to Automatic, reboot again. Toggle should appear after 7-day uptime / KG 'Checking' passes.")
    print()
    ans = input("Run automated on-device refresh (disable auto-update + reboot)? [y/N]: ").strip().lower()
    if ans == "y":
        # Best-effort, harmless settings changes
        run("adb shell settings put global auto_time 0")
        run("adb shell settings put global auto_time_zone 0")
        print("[*] Disabled auto_time. Set date back manually in Settings, then reboot.")
        rb = input("Reboot device now? [y/N]: ").strip().lower()
        if rb == "y":
            run("adb reboot")
            print("Rebooting... wait 60s, then re-run 'diagnose'.")
            time.sleep(5)
    print()
    print("If toggle still missing after 7 days uptime + WiFi:")
    print(" - Carrier variant (U/U1/W) or KG State=Locked / RMM State=Prenormal -> must SIM-unlock / wait, cannot be scripted away.")
    print(" - US Snapdragon carrier models often have no unlock at all. No safe bypass exists.")

def unlock_guide(props):
    brand = (props.get("ro.product.manufacturer","") + " " + props.get("ro.product.brand","")).lower()
    print("=== Bootloader unlock guide (official paths only) ===")
    if "samsung" in brand:
        print("Samsung:")
        print(" 1. Enable Developer options (tap Build number 7x), enable OEM unlocking + USB debugging.")
        print(" 2. Power off. Hold Vol Up+Vol Down, plug USB to PC -> Download Mode.")
        print(" 3. Long-press Vol Up to unlock bootloader (wipes data, trips Knox).")
        print(" 4. Flash custom recovery .tar via Odin (AP slot) or heimdall: heimdall flash --RECOVERY recovery.tar")
        print(" 5. Boot to recovery, flash Magisk or patch AP with Magisk app.")
    elif "xiaomi" in brand or "redmi" in brand or "poco" in brand:
        print("Xiaomi/Redmi/POCO: bind Mi account in Developer options > Mi Unlock status, wait 7 days, use Mi Unlock Tool (Windows). Then 'fastboot flash recovery twrp.img'.")
    elif "oneplus" in brand or "google" in brand or "motorola" in brand or "sony" in brand or "nothing" in brand:
        print(" 1. adb reboot bootloader")
        print(" 2. fastboot flashing unlock  (or 'fastboot oem unlock' on older devices)")
        print(" 3. Confirm on device (volume/power). DATA WILL WIPE.")
    else:
        print("Generic fastboot device:")
        print("  adb reboot bootloader; fastboot flashing unlock; fastboot flash recovery recovery.img")
    print()
    print("No tool can 'bypass' a locked bootloader without the vendor's unlock without an exploit.")
    print("MTK/EDL exploits exist per-model but brick-risk is high and they still trip security. Not included by design.")

def flash_recovery(image: str, is_samsung=False):
    p = Path(image)
    if not p.exists():
        print(f"[!] Image not found: {image}")
        print("Download matching TWRP for your exact model from https://twrp.me/Devices/ and pass its path.")
        return
    print(f"[*] Using image: {p} ({p.stat().st_size//1024} KB)")
    confirm = input("Flash now? Device must be in fastboot/Download mode. [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return
    if is_samsung:
        if p.suffix.lower() == ".tar" or p.suffix.lower() == ".md5":
            print("For Samsung use Odin (Windows GUI) with this .tar in AP, or: heimdall flash --AP <file.tar>")
            if have("heimdall"):
                c, o, e = run(f'heimdall flash --RECOVERY "{p}"')
                print(o or e)
            else:
                print("heimdall not found. Open Odin manually; put file in AP slot, disable Auto-Reboot, flash, then boot to recovery with buttons.")
        else:
            print("[!] Samsung needs .tar/.tar.md5 for Odin. Convert: tar -H ustar -c recovery.img > recovery.tar")
    else:
        slot = input("Partition (default recovery, Pixel may use boot/init_boot)? [recovery]: ").strip() or "recovery"
        c, o, e = run(f'fastboot flash {slot} "{p}"')
        print(o or e)
        if c == 0:
            print("[OK] Flashed. Now 'fastboot reboot recovery' or hold recovery combo.")

def magisk_guide():
    print("=== Root with Magisk (systemless) ===")
    print(" 1. In TWRP backup boot/vendor_boot. Pull stock boot.img for your exact build.")
    print(" 2. Install Magisk app (https://github.com/topjohnwu/Magisk), patch boot.img/AP.tar in app.")
    print(" 3. fastboot flash boot magisk-patched.img  (Samsung: flash patched AP via Odin)")
    print(" 4. Reboot, verify with Magisk app + 'adb shell su -c id'.")
    print(" SafetyNet/Play Integrity will fail on unlocked devices; banking apps may refuse. Knox-dependent Samsung features (Secure Folder, Samsung Pay) break permanently.")

def menu():
    print("\nAndroid Root & Recovery Toolkit")
    print("1) Check dependencies")
    print("2) List devices (adb/fastboot)")
    print("3) Diagnose connected adb device (model, lock, Knox, OEM toggle)")
    print("4) Repair missing OEM-unlock toggle (helper)")
    print("5) Bootloader unlock guide (by brand)")
    print("6) Flash custom recovery image")
    print("7) Magisk root guide")
    print("0) Exit")

def main(argv):
    if len(argv) > 1 and argv[1] in ("-h","--help","help"):
        print(__doc__)
        print("Usage: python rootkit.py [diagnose|repair-oem|flash <img>|guide]")
        return 0
    if len(argv) > 1:
        check_deps()
        props = getprops() if adb_devices() else {}
        if argv[1] == "diagnose":
            if not props: print("[!] No adb device. Enable USB debugging + authorize."); return 1
            diagnose(props); return 0
        if argv[1] == "repair-oem":
            repair_oem_toggle(); return 0
        if argv[1] == "guide":
            unlock_guide(props); magisk_guide(); return 0
        if argv[1] == "flash" and len(argv) > 2:
            is_s = "samsung" in (props.get("ro.product.manufacturer","")+props.get("ro.product.brand","")).lower()
            flash_recovery(argv[2], is_samsung=is_s); return 0
        print("Unknown args. See --help."); return 1
    # interactive
    props_cache = {}
    while True:
        menu()
        c = input("> ").strip()
        if c == "0": break
        elif c == "1": check_deps()
        elif c == "2":
            print("adb:", adb_devices() or "none")
            print("fastboot:", fastboot_devices() or "none")
        elif c == "3":
            d = adb_devices()
            print("adb devices:", d or "none")
            if not d: continue
            props_cache = getprops()
            diagnose(props_cache)
        elif c == "4": repair_oem_toggle()
        elif c == "5":
            if not props_cache: props_cache = getprops()
            unlock_guide(props_cache)
        elif c == "6":
            img = input("Path to recovery (.img / Samsung .tar): ").strip().strip('"')
            is_s = "samsung" in (props_cache.get("ro.product.manufacturer","")+props_cache.get("ro.product.brand","")).lower()
            flash_recovery(img, is_samsung=is_s)
        elif c == "7": magisk_guide()
        else: print("Unknown option.")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
