@echo off
setlocal
rem Streams this PC's desktop to the projector: Sunshine (PC) -> Moonlight (projector), started over wifi adb.
rem The stream runs while this window is open. Press a key or close the window to stop it.
rem Usage: cast_to_projector.bat         start streaming
rem        cast_to_projector.bat stop    end a stream left running, projector goes back to its home screen

set SSID=YOUR_WIFI_SSID
set PROJ_IP=PROJECTOR_IP
set PROJ_MAC=PROJECTOR_MAC
set SUBNET=192.168.1
set HOST_UUID=SUNSHINE_HOST_UUID

netsh wlan show interfaces | findstr /r /c:" SSID *: %SSID%$" >nul || (echo Not connected to %SSID%. & goto :fail)

adb connect %PROJ_IP%:5555 | find "connected to" >nul || call :find_projector
adb -s %PROJ_IP%:5555 get-state >nul 2>&1 || (echo Projector not found. Is it on and connected to %SSID%? & goto :fail)
set ADB=adb -s %PROJ_IP%:5555

if /i "%1"=="stop" goto :stop

sc query SunshineService | find "RUNNING" >nul || (echo Sunshine is not running. Start "SunshineService" in services.msc. & goto :fail)

%ADB% shell input keyevent KEYCODE_WAKEUP
%ADB% shell am force-stop com.limelight
%ADB% shell am start -n com.limelight/.ShortcutTrampoline --es UUID %HOST_UUID% --es AppName Desktop >nul || (echo Could not start Moonlight. & goto :fail)

rem Closing the window with X kills this script before it reaches :stop, so a hidden watcher
rem waits for this cmd.exe to exit and then stops the stream.
powershell -NoProfile -c "$me=(Get-CimInstance Win32_Process -Filter \"ProcessId=$PID\").ParentProcessId; Start-Process powershell -WindowStyle Hidden -ArgumentList \"-NoProfile -c Wait-Process -Id $me; %ADB% shell am force-stop com.limelight; %ADB% shell input keyevent KEYCODE_HOME\""

echo Projecting to %PROJ_IP%. Press any key or close this window to stop.
pause >nul

:stop
%ADB% shell am force-stop com.limelight
%ADB% shell input keyevent KEYCODE_HOME
echo Stream stopped.
exit /b 0

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
