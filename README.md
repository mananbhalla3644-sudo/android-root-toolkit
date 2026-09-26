# Android Root & Custom Recovery Toolkit

Official-paths-only toolkit for unlocking, flashing TWRP, and Magisk root by device model.

## What it does
- `diagnose`: reads `ro.product.model/device/manufacturer`, bootloader lock, Knox warranty bit, OEM-toggle state
- `repair-oem`: helper for missing "OEM unlocking" toggle (date-back + account/WiFi/KG checks). Does NOT bypass carrier/KG lock.
- `guide`: brand-specific unlock steps (Samsung Download Mode, Pixel/fastboot, Xiaomi Mi Unlock, etc.)
- `flash`: flashes user-supplied recovery (`fastboot flash` or Samsung `.tar` via Odin/Heimdall)
- `magisk`: systemless root walkthrough

## What it does NOT do (on purpose)
- No Knox 0x0 bypass. Knox e-fuse trips to 0x1 on first custom flash and is **irreversible**. Claims otherwise are false.
- No silent bootloader bypass. Carrier/KG/RMM-locked devices cannot be scripted open.
- No per-model exploits (MTK/EDL) bundled — brick risk too high.

## Use (Windows)
```
winget install Google.PlatformTools
python android-root-toolkit\rootkit.py
python android-root-toolkit\rootkit.py diagnose
python android-root-toolkit\rootkit.py repair-oem
python android-root-toolkit\rootkit.py flash .\twrp-3.7-model.img
```

Samsung flash needs Odin with `.tar` in AP slot (disable Auto-Reboot, then boot to recovery via buttons).
TWRP downloads: https://twrp.me/Devices/
Magisk: https://github.com/topjohnwu/Magisk

Unlocking wipes data and voids warranty. Use only on devices you own.
