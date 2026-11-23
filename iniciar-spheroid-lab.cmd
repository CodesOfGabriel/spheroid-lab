@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0src"
python -m esferoides revisar --sem-aquecer %*
set "resultado=%ERRORLEVEL%"
popd
exit /b %resultado%
