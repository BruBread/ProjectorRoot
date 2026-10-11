#!/usr/bin/env bash
# Snapshot the projector's performance state to a timestamped file, for
# before/after comparison. Usage: ./baseline.sh [adb-serial]  (default: wifi)
export MSYS_NO_PATHCONV=1
S="${1:-192.168.1.10:5555}"
OUT="baseline_$(date +%Y%m%d_%H%M%S).txt"
adb connect "$S" >/dev/null 2>&1
sh() { echo "### $* ###"; adb -s "$S" shell "$@" 2>&1; echo; }
{
  echo "=== baseline $(date) | $S ==="
  sh getprop ro.build.fingerprint
  sh getprop ro.build.version.release
  sh getprop ro.config.low_ram
  sh id
  echo ">>> MEMORY"
  sh free -m
  sh cat /proc/meminfo
  echo ">>> STORAGE"
  sh df -h /data /cache
  echo ">>> CPU"
  sh cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
  sh cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors
  sh cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
  sh cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
  sh cat /sys/class/thermal/thermal_zone0/temp
  echo ">>> RUNNING PROCS (top RAM)"
  sh dumpsys meminfo
  echo ">>> AUTOSTART / RUNNING PACKAGES"
  sh dumpsys activity processes
  echo ">>> ANIMATION SCALES"
  sh settings get global window_animation_scale
  sh settings get global transition_animation_scale
  sh settings get global animator_duration_scale
  echo ">>> LMK / HEAP PROPS"
  sh "getprop | grep -iE 'boottime|lowmem|lmk|dalvik.vm.heap|ro.config'"
  echo ">>> PACKAGE COUNTS"
  sh "pm list packages | wc -l"
  sh "pm list packages -3 | wc -l"
  sh "pm list packages -d | wc -l"
} | tee "$OUT"
echo
echo "saved -> $OUT"
