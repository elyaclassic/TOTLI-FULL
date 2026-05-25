@echo off
REM ============================================================
REM  server2220 - 24/7 power config (no sleep / no hibernate).
REM  RDP into server2220, right-click this file ->
REM  "Run as administrator". Tier A: zero service impact,
REM  no restart needed. Re-run after Windows updates if needed.
REM  ASCII-only on purpose (cmd.exe + cyrillic + chcp = broken).
REM ============================================================
setlocal

echo.
echo === server2220 24/7 power setup ===
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Run this as ADMINISTRATOR.
    echo         Right-click the file -^> Run as administrator.
    echo.
    pause
    exit /b 1
)

echo --- BEFORE ---
powercfg /getactivescheme
echo.
powercfg /a
echo.

echo --- APPLY ---
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change disk-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /change hibernate-timeout-dc 0
powercfg /change disk-timeout-dc 0
powercfg /hibernate off
echo [OK] standby/hibernate/disk = 0 (never), hibernate disabled
echo.

echo --- AFTER (verify) ---
echo powercfg /a  (Hibernate must be in the UNAVAILABLE list):
powercfg /a
echo.
echo Active scheme sleep settings (AC index must be 0x00000000):
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
echo.
echo === DONE. server2220 will no longer sleep. ===
echo.
pause
endlocal
