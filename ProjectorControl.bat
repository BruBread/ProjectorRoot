@echo off
setlocal
rem Projector controller: starts Sunshine, streams this PC's desktop to the projector (Moonlight, started
rem over wifi adb) and serves the keystone page (keystone\keystone.py --stream).
rem In this window: C opens the keystone page, Q stops. Closing the window also stops the stream and Sunshine.
rem On the page, the grid button switches the projector between the alignment grid and the stream.
rem Usage: ProjectorControl.bat         start streaming
rem        ProjectorControl.bat stop    end a stream left running and stop Sunshine

set SSID=secretwifi
set PROJ_IP=192.168.1.10
set PROJ_MAC=cc-f3-05-8f-10-d2
set SUBNET=192.168.1
set HOST_UUID=FBB9EECB-D643-7C0B-9004-EF550DB36751

netsh wlan show interfaces | findstr /r /c:" SSID *: %SSID%$" >nul || (echo Not connected to %SSID%. & goto :fail)

adb connect %PROJ_IP%:5555 | find "connected to" >nul || call :find_projector
adb -s %PROJ_IP%:5555 get-state >nul 2>&1 || (echo Projector not found. Is it on and connected to %SSID%? & goto :fail)
set ADB=adb -s %PROJ_IP%:5555

if /i "%1"=="stop" goto :stop

rem Closing the window with X kills this script before it reaches :stop, so a hidden watcher
rem waits for this cmd.exe to exit and then stops the stream and Sunshine.
powershell -NoProfile -c "$me=(Get-CimInstance Win32_Process -Filter \"ProcessId=$PID\").ParentProcessId; Start-Process powershell -WindowStyle Hidden -ArgumentList \"-NoProfile -c Wait-Process -Id $me; %ADB% shell am force-stop com.limelight; %ADB% shell input keyevent KEYCODE_HOME; sc.exe stop SunshineService\""

rem Sunshine runs only while projecting. Only admins may start a service, so the first run asks once (UAC)
rem to let logged-in users start and stop SunshineService, and stops it starting with Windows.
sc start SunshineService >nul
if %errorlevel%==5 (
  echo One-time setup: allow starting and stopping Sunshine without admin. Accept the admin prompt.
  powershell -NoProfile -c "Start-Process cmd -Verb RunAs -Wait -ArgumentList '/c sc sdset SunshineService D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWRPWPLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU) & sc config SunshineService start= demand'"
  sc start SunshineService >nul || (echo Could not start Sunshine. & goto :fail)
)

rem Moonlight gives up on a host that is not answering yet, so wait for Sunshine's port to open.
for /L %%i in (1,1,30) do (
  netstat -an | find ":47989 " | find "LISTENING" >nul && goto :sunshine_up
  timeout /t 1 >nul
)
echo Sunshine did not start. & goto :fail
:sunshine_up

rem Starts the stream and serves the keystone page until Q. On an error, pause so it can be read.
python "%~dp0keystone\keystone.py" --device %PROJ_IP%:5555 --stream %HOST_UUID% || pause

:stop
%ADB% shell am force-stop com.limelight
%ADB% shell input keyevent KEYCODE_HOME
sc stop SunshineService >nul
echo Stream and Sunshine stopped.
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
