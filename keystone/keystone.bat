@echo off
rem Starts the projection-mapping controller: opens it in this PC's browser and prints the address for your phone.
rem The warp stays on the projector after you close this window; the shape mask lasts only while it runs.
rem Usage: keystone.bat                              projector at PROJECTOR_IP:5555
rem        keystone.bat --device 192.168.1.23:5555   projector got a new DHCP address
cd /d "%~dp0"
python keystone.py %*
pause
