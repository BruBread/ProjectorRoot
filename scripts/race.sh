#!/usr/bin/env bash
export MSYS_NO_PATHCONV=1
IP=PROJECTOR_IP:5555
LOG="$1"
echo "[*] rebooting to normal boot $(date +%T)" > "$LOG"
adb reboot >>"$LOG" 2>&1
sleep 1
WIN=0
for i in $(seq 1 900); do
  # try to establish wifi transport
  adb connect $IP >/dev/null 2>&1
  # fire the flip on whatever transport exists (usb default + wifi), short timeout so we never block
  timeout 3 adb shell "settings put global adb_enabled 1" >/dev/null 2>&1 && echo "[hit-usb $i $(date +%T)]" >>"$LOG"
  timeout 3 adb -s $IP shell "settings put global adb_enabled 1" >/dev/null 2>&1 && echo "[hit-wifi $i $(date +%T)]" >>"$LOG"
  # read-back check
  V=$(timeout 3 adb shell "settings get global adb_enabled" 2>/dev/null | tr -d '\r\n')
  VW=$(timeout 3 adb -s $IP shell "settings get global adb_enabled" 2>/dev/null | tr -d '\r\n')
  if [ "$V" = "1" ] || [ "$VW" = "1" ]; then
    WIN=$((WIN+1))
    echo "[confirm $i $(date +%T)] usb=$V wifi=$VW stable=$WIN" >>"$LOG"
    # once confirmed stable over several reads, lock in tcpip + stop
    if [ "$WIN" -ge 5 ]; then
      timeout 4 adb tcpip 5555 >>"$LOG" 2>&1
      echo "[DONE $(date +%T)] adb_enabled sticking" >>"$LOG"
      break
    fi
  else
    WIN=0
  fi
done
echo "[*] loop end $(date +%T)" >>"$LOG"
echo "=== final state ===" >>"$LOG"
adb devices -l >>"$LOG" 2>&1
adb connect $IP >>"$LOG" 2>&1
