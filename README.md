# ProjectorRoot

Getting persistent ADB and root onto a cheap "HY300" Android projector that ships with developer access ripped out — and reverse-engineering the firmware along the way.

The device is a Magcubic/HY300-branded projector that is actually a **Rockchip RK3326** board (`rk3326_sgo`, Android 12 Go, `userdebug/release-keys`), with a heavily reskinned firmware by an ODM called **TXCZ**. On the stock firmware there is no way in: the "tap Build Number 7 times" developer-options unlock has been deleted from the code, and sitting on the home screen the device exposes no ADB at all.

**Result: persistent ADB + root in normal boot, over Wi-Fi, no cable, surviving reboots.** The write-up below traces every step that got there — including the dead ends, because most of the work was dead ends — and the one firmware mystery I never cracked.

> ⚠️ Everything here was done on a projector I own, for interoperability and to learn. See [Legal & scope](#legal--scope) before you touch your own device. Nothing here is a remote exploit; it all starts from physical possession and the stock recovery.

## At a glance

| | |
|---|---|
| Device | Magcubic / HY300-branded projector |
| Real silicon | Rockchip RK3326 (`rk3326_sgo`), 4× Cortex-A35, Android 12 Go |
| Firmware | `userdebug/release-keys`, reskinned by ODM "TXCZ" (`com.shzhtxcz.txbox` posing as `com.android.tv.settings`) |
| Goal | Persistent ADB + root in normal boot (stock firmware exposes neither) |
| Outcome | **Achieved** — `adb connect 192.168.1.10:5555` → `adb root` → `uid=0 (u:r:su:s0)`, persists across reboots |
| Still unsolved | `/system` edits silently revert on every boot — traced to a bespoke mechanism in U-Boot or earlier |
| Tools | Stock recovery root, liblp loop-mounts, jadx, hand-written AXML/DEX parsers, capstone, Ghidra 12.1.3 |
| Attempts logged | 19+, each with its reasoning — see [PROGRESS_LOG.md](PROGRESS_LOG.md) |

## What I wanted to do with it

The projector is fine hardware wrapped in software I don't control. The plan, once I had root, was to make it mine:

- **Debloat it** — rip out the TXCZ launcher and its bundled apps, install a clean launcher (Projectivy).
- **Control it from my PC** — `scrcpy` for screen + input, and drive it from `adb` instead of a stripped-down settings menu that hides most of Android.
- **Block ads and tracking device-wide** — Private DNS, and see for myself what the OEM apps phone home with (`logcat`, traffic capture).
- **Home automation** — turn it on/off and launch apps from Home Assistant's ADB integration.
- **The stretch dream** — the RK3326 also powers the Odroid Go Advance / Anbernic RG351 handhelds, which run mainline Linux. A real custom OS would mean porting the projector's own display/keystone/focus drivers. Months of work, probably not worth it, but the chip makes it *thinkable*.

None of that needs `/system` to be writable — it all lives in `/data`, which is exactly why persistent ADB was the whole ballgame.

## How access actually works

Two things work reliably and are the foundation for everything else:

- **Recovery root.** Hold the power button while powering on → stock AOSP recovery. There, `adb root` restarts adbd as root (`uid=0`, context `u:r:su:s0`) every time, no exploit needed. This build never locked it down.
- **Mounting the partitions from recovery.** `/data` is a flat ext4 partition and mounts directly. `/system` is *not* a flat partition — it's a logical volume inside the dynamic `super` partition, and recovery's own "Mount /system" is broken for this board. I parsed `super`'s liblp metadata header by hand to find the byte range and loop-mounted it:

  ```sh
  losetup -f -s -o 1048576 -S 800915456 /dev/block/by-name/super
  mount -t ext4 -o rw /dev/block/loop0 /mnt_system
  ```

The problem: **normal boot has no ADB at all**, and the usual unlock is gone. Recovery root can't simply flip the switch either, because the setting that controls ADB (`Settings.Global.adb_enabled`) lives in `/data/system`, which is **FBE-encrypted** and unreadable from recovery without the keys that only exist inside a booted Android.

## The win: persistent normal-boot ADB + root

The breakthrough was realizing there are two different locks, and they fail differently:

1. `/data/local.prop` is **plaintext and persists** across reboots (unlike `/system`, which reverts — see below). From recovery root I wrote:

   ```properties
   persist.sys.usb.config=mtp,adb
   persist.service.adb.enable=1
   persist.adb.tcp.port=5555
   service.adb.tcp.port=5555
   ```

2. Because the build is `userdebug` (`ro.debuggable=1`), init reads `local.prop` **early in boot**, so ADB (USB + TCP 5555) comes up for roughly **one second** before `system_server`'s `UsbDeviceManager` reconciles against `adb_enabled=0` and kills it again. Every earlier manual attempt missed that window.

3. So I automated the race ([`scripts/race.sh`](scripts/race.sh)): the instant ADB appears, hammer `settings put global adb_enabled 1` over both USB and Wi-Fi until it sticks. It landed on **iteration 3 (~1 s)**. Once `adb_enabled=1` is written into the CE-encrypted settings DB *by the running system*, `UsbDeviceManager` now reads `1` and **keeps** ADB instead of resetting it.

4. `ro.adb.secure` is unset, so there's no RSA authorization prompt — ADB is trusted immediately, and `adb root` escalates (userdebug).

The key insight: the property override alone only buys the one-second window; the thing that makes it *permanent* is flipping the real `adb_enabled` setting during that window, through the booted settings provider that recovery can't reach.

**Verified:** after `adb reboot`, the device comes back on its own at `192.168.1.10:5555`, `adb_enabled=1`, port 5555 listening, `adb root` → `uid=0`. No cable, no re-running the race. The race is a one-time cost.

## The mystery I didn't solve: `/system` reverts on every boot

Any edit to `/system` (even a brand-new file) is **silently reverted on the next boot** — byte-identical content restored, mtime reset to the `1970-01-01` build epoch, a fresh inode each time. That's not a live watcher; it's a whole-partition repopulation from a reference image.

I spent most of this project chasing it, and systematically ruled things out:

- **It's below Android.** Rebooting straight back into *recovery* (which shares zero Android-side code with normal boot) still wipes the edits. That kills every Android-side hypothesis at once — overlayfs, `txcz_ota`, fstab dm-verity, the reserved eMMC region, the (empty) `backup` partition.
- **It's not in U-Boot's boot path.** I located U-Boot's load base and command table from raw bytes ([`scripts/find_cmdtbl.py`](scripts/find_cmdtbl.py), [`scripts/walk_cmdtbl.py`](scripts/walk_cmdtbl.py)), then traced `do_boot_android` and `do_bootrkp` end-to-end in Ghidra. Both are **read-only** boot-image loaders — none of the seven partition-write functions I was hunting for are reachable. `boot_fit` was proven *not to exist* as a compiled command (structural proof from the command table, zero gap between neighbors).
- **It predates my build.** Diffing against a stock ROM from 7 months earlier, `do_boot_android`/`do_bootrkp` are instruction-for-instruction identical and `trust.bin` is byte-identical. `uboot.bin` is exhausted as a suspect across both revisions.

Where it stands: the mechanism is a **bespoke TXCZ addition** (stock Rockchip U-Boot never does this), living either in the **pre-GPT idbloader/SPL stage** that runs before U-Boot proper (dumped, string-clean, but never disassembled as code) or in the **TEE runtime** (`trust.bin`, only string-scanned so far). Defeating it for real would mean patching and reflashing `uboot`/`trust`, which is genuine brick territory recoverable only via hardware Maskrom — a line I chose not to cross. Full reasoning in [PROGRESS_LOG.md](PROGRESS_LOG.md), Attempts 11–19.

It doesn't block the goal: persistent ADB and root live entirely in `/data`, which never reverts.

## Reproduce this on your own board

You need the projector, a USB cable, a PC with `adb`, and the same `rk3326_sgo` userdebug firmware (check `getprop ro.build.fingerprint` in recovery). High level:

1. Boot to recovery (hold power while powering on), `adb root`.
2. Mount userdata: `mount -t ext4 /dev/block/by-name/userdata /mnt_data`. *(On Git Bash, `export MSYS_NO_PATHCONV=1` first or the device path gets mangled.)*
3. Append the four `persist.*`/`service.*` lines above to `/mnt_data/local.prop`; `sync; umount /mnt_data`.
4. `adb reboot`, then immediately run [`scripts/race.sh`](scripts/race.sh) `<logfile>` from your PC.
5. When it reports `adb_enabled` sticking, you have permanent normal-boot ADB. `adb root` for root.

This is specific to a **userdebug** build with `ro.adb.secure` unset. A `user` build would need a different way in entirely.

## Repository layout

```
README.md              this file
PROGRESS_LOG.md        the full blow-by-blow: 19+ attempts, each with its reasoning
SAFETY_PLAYBOOK.md     backup-first rules and brick-recovery notes I worked under
scripts/               everything I actually wrote (see table below)
scripts/ghidra/        headless Ghidra call-graph tracers for the U-Boot analysis
backups/               firmware/config pulled from the device (boot, vbmeta, uboot, trust, super header, init.rc)
analysis/              the evidence trail: hypothesis results (JSON), kernel logs, Ghidra run logs
```

### Scripts

| Script | What it does |
|--------|--------------|
| [`scripts/race.sh`](scripts/race.sh) | The win. Races `adb_enabled=1` into the ~1 s early-boot window over USB + Wi-Fi until it sticks. |
| [`scripts/find_cmdtbl.py`](scripts/find_cmdtbl.py) | Locates U-Boot's command table in a raw image and derives this build's `cmd_tbl_s` struct layout. |
| [`scripts/walk_cmdtbl.py`](scripts/walk_cmdtbl.py) | Walks the table from a known anchor to recover the whole command list — no Ghidra needed. |
| [`scripts/fullscan.py`](scripts/fullscan.py) | Threaded 1–65535 TCP port sweep of the device over the LAN. |
| [`scripts/banner.py`](scripts/banner.py) · [`scripts/http.py`](scripts/http.py) | Banner-grab / HTTP probe the open ports (turned out to be only a screen-cast stack). |
| [`scripts/axml_dump.py`](scripts/axml_dump.py) | Decodes binary `AndroidManifest.xml` (AXML string pool) without aapt. |
| [`scripts/dex_strings.py`](scripts/dex_strings.py) | Pulls the string pool from a `classes.dex` for quick grepping. |
| [`scripts/ghidra/`](scripts/ghidra/) | Headless Ghidra scripts that walk `do_boot_android`/`do_bootrkp` call graphs and flag any block-write. |

## Legal & scope

- The projector is mine. This is interoperability and security-research work on hardware I own, with no circumvention of any remote protection — it all begins from physical access and the vendor's own recovery.
- Not affiliated with Magcubic, TXCZ, or Rockchip. "HY300" is a branding reused across unrelated hardware; guides for the Allwinner "HY300 Pro" do **not** apply to this Rockchip board.
- The firmware images under `backups/` are the vendors' copyrighted material, included only as reference dumps from my unit. They are not licensed to you — dump your own.
- Do this only on a device you own, and read [SAFETY_PLAYBOOK.md](SAFETY_PLAYBOOK.md) first. The `/system`-revert section explains why I stopped short of reflashing the bootloader.

## License

My own code and write-ups (everything under `scripts/`, the Markdown docs, and `analysis/`) are MIT — see [LICENSE](LICENSE). The firmware images under `backups/` are **not** covered and remain their respective owners' property.
