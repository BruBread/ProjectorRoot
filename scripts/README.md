# HY300/TXCZ RK3326 projector — root + HDMI auto-switch

## Persistent wifi adb root (normal boot)
`/data/local.prop` (plaintext, non-reverting) +  one-time boot-window race (`adb_enable_race.sh`)
flips `Settings.Global.adb_enabled=1`; then `adb connect PROJECTOR_IP:5555` + `adb root`.

## Auto HDMI-in switch
- `hdmi_autoswitch.sh` -> `/data/hdmi_autoswitch.sh` : polls `/sys/kernel/debug/2-0050/hdmirx/status`
  (`plugin`/`plugout`), switches to `com.android.rockchip.camera2/.RockchipCamera2` on connect,
  returns HOME on disconnect. Transition-based.
- `hdmi_autoswitch.rc` : the init service. Installed by appending its `service` block to
  `/vendor/etc/init/hw/init.rk3326.rc` (/vendor is boot-persistent; /system is not). SELinux permissive.

Backups of the original vendor init: `/cust/init.rk3326.rc.bak`, `/data/init.rk3326.rc.bak`,
and `backups/init.rk3326.rc.orig`.

## Brightness
The LED backlight runs at a fixed current: the `backlight` device tree node has no `pwms`, so
`/sys/class/backlight` is empty and Android's brightness slider (lights HAL) writes to a file that does not exist.
The only picture control that reaches the hardware is the VOP gamma LUT, which the factory `testgamma` service
(`/system/bin/testgammatx.sh`) sets at boot. Its `--brightness/--contrast/--hue/--saturation` options print
`prop id 0` and do nothing, because the LVDS connector has no such DRM properties.
`brightness.bat <0-100>` sets `--target_gamma` to `2.9 - level*0.022` (50 = factory 1.8) and saves the
command to `/data/brightness.sh`. `brightness.rc` (appended once to `/vendor/etc/init/hw/init.rk3326.rc`,
backup at `/cust/init.rk3326.rc.pre-brightness`) runs it after `testgamma` at every boot.

## Wireless PC screen streaming
Sunshine (PC host, AMF hardware encode) streams to Moonlight 12.2 on the projector (`c2.rk.hevc.decoder`
hardware decode, 1280x720@60, video only: Sunshine `stream_audio = disabled` keeps PC sound on the PC). `../ProjectorControl.bat` checks the SSID, connects wifi adb (finds the
projector by MAC if its DHCP address changed), starts `SunshineService` and waits for its port 47989, wakes the screen, and starts the "Desktop" stream through
Moonlight's `ShortcutTrampoline` activity (extras `UUID` + `AppName`). The stream lasts while the window is open:
Q or closing the window (a hidden PowerShell watcher waits on the cmd.exe PID) stops it and Sunshine.
Sunshine runs only while projecting: the first run asks for admin once (UAC) to add start/stop rights for
interactive users (`IU`) to the service DACL and set it to manual start (`sc config SunshineService start= demand`).
While streaming, Wi-Fi Direct extended listen (`wpa_cli -i p2p-dev-wlan0 p2p_ext_listen`) is off: it keeps the
projector visible to Win+K/Miracast by parking the single-radio AIC Wi-Fi chip on another channel for 500 ms of
every 1000 (`remain_on_channel` in dmesg), which froze the stream every second. A detached loop on the projector
sets it back to `500 1000` once Moonlight's process exits.
C opens the keystone page (`keystone/keystone.py --stream`); its grid button switches the projector between the alignment grid and the stream.
One-time setup: install both apps, then pair once (PIN shown by Moonlight, entered through Sunshine's `/api/pin`).
