@echo off
setlocal
rem Sets the projector's picture brightness and keeps it across reboots.
rem Usage: brightness.bat <0-100>   50 = factory picture, higher = brighter
rem        brightness.bat           show the saved level
rem The LED runs at a fixed current that software cannot change (no PWM on the backlight), so this
rem reshapes the gamma curve: higher levels lift dark and mid tones. No level can harm the hardware;
rem very high levels just look washed out.
rem First run appends brightness.rc to /vendor/etc/init/hw/init.rk3326.rc (backup: /cust/init.rk3326.rc.pre-brightness)
rem so /data/brightness.sh runs after the factory testgamma service at every boot.

set PROJ_IP=PROJECTOR_IP
set PROJ_MAC=PROJECTOR_MAC
set SUBNET=192.168.1

adb connect %PROJ_IP%:5555 | find "connected to" >nul || call :find_projector
adb -s %PROJ_IP%:5555 get-state >nul 2>&1 || (echo Projector not found. Is it on and on the same wifi? & goto :fail)
set ADB=adb -s %PROJ_IP%:5555

rem adb root restarts adbd after a reboot, which drops the wifi connection: reconnect.
%ADB% root | find "restarting" >nul && (timeout /t 3 >nul & adb connect %PROJ_IP%:5555 >nul)

if "%1"=="" (
  %ADB% shell "sed -n 's/.*# level /Saved level: /p' /data/brightness.sh 2>/dev/null || echo Saved level: 50, factory"
  exit /b 0
)
echo %1| findstr /r /x "0 [1-9][0-9]*" >nul || goto :usage
if %1 GTR 100 goto :usage

rem target gamma = 2.9 - level*0.022: 0 = native panel curve (2.9), 50 = factory (1.8), 100 = 0.7
set /a T=2900-%1*22, F=T%%1000+1000
set /a I=T/1000
set G=%I%.%F:~1%

%ADB% push "%~dp0brightness.rc" /data/local/tmp/brightness.rc >nul || (echo brightness.rc must sit next to this script. & goto :fail)
%ADB% shell "f=/vendor/etc/init/hw/init.rk3326.rc; grep -q 'service brightness' $f || { cp $f /cust/init.rk3326.rc.pre-brightness && mount -o rw,remount /vendor && cat /data/local/tmp/brightness.rc >> $f && echo Installed boot hook in $f; sync; mount -o ro,remount /vendor; }"

rem Same line as the factory /system/bin/testgammatx.sh except --target_gamma. On this LVDS panel only the
rem gamma curve and white balance reach the hardware; --brightness/--contrast/--hue/--saturation are no-ops.
%ADB% shell "echo 'testgamma --wb_r 1.0 --wb_g 0.96 --wb_b 0.95 --contrast 58 --brightness 30 --saturation 80 --hue 35 --target_gamma %G% --native_gamma 2.9 # level %1' > /data/brightness.sh && sh /data/brightness.sh >/dev/null 2>&1" || (echo Could not apply. & goto :fail)
echo Brightness level %1 set (gamma %G%). It stays after reboot.
exit /b 0

:usage
echo Usage: brightness.bat ^<0-100^>   50 = factory, higher = brighter. No argument shows the saved level.
goto :fail

rem The projector's DHCP address changed: ping the subnet to fill the ARP table, then look it up by MAC.
:find_projector
for /L %%i in (1,1,254) do start /b "" ping -n 1 -w 300 %SUBNET%.%%i >nul
timeout /t 3 >nul
for /f "tokens=1" %%a in ('arp -a ^| find /i "%PROJ_MAC%"') do set PROJ_IP=%%a
adb connect %PROJ_IP%:5555 >nul
exit /b 0

:fail
pause
exit /b 1
