#!/system/bin/sh
# Auto-switch to HDMI-in viewer on connect; return home on disconnect.
NODE=/sys/kernel/debug/2-0050/hdmirx/status
while [ "$(getprop sys.boot_completed)" != "1" ]; do sleep 1; done
sleep 3
prev=""
while true; do
  if cat "$NODE" 2>/dev/null | grep -q plugin; then st=plugin; else st=plugout; fi
  if [ "$st" != "$prev" ]; then
    if [ "$st" = "plugin" ]; then
      setprop persist.txcz.source 1
      am start -n com.android.rockchip.camera2/.RockchipCamera2 >/dev/null 2>&1
    else
      setprop persist.txcz.source 0
      am start -a android.intent.action.MAIN -c android.intent.category.HOME >/dev/null 2>&1
    fi
    log -t hdmi_autoswitch "source -> $st"
    prev=$st
  fi
  sleep 2
done
