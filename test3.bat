for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "Write-Output 'IR=abc'"`) do set "%%A"
echo %IR%
