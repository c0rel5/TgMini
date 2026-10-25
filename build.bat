@echo off
chcp 65001 >nul
echo === Сборка TgMini ===
python -m pip install -r requirements.txt || goto :err
python -m PyInstaller --noconfirm --clean --onedir --noconsole --name TgMini ^
  --icon icon.ico --add-data "plugins;plugins" ^
  --hidden-import socks --collect-submodules telethon tgmini.py || goto :err
rem --- портативная версия ---
if exist portable rmdir /s /q portable
mkdir portable\TgMini
xcopy /e /i /y dist\TgMini portable\TgMini >nul
echo.>portable\TgMini\portable.flag
copy /y portable_readme.txt portable\TgMini\ПРОЧТИ.txt >nul
powershell -NoProfile -Command "Compress-Archive -Force -Path portable\TgMini -DestinationPath TgMini-Portable.zip"
echo Портативная версия: TgMini-Portable.zip
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ISCC%" (
  "%ISCC%" installer.iss || goto :err
  echo.
  echo Готово: installer\TgMini-Setup.exe
) else (
  echo.
  echo Программа собрана: dist\TgMini\TgMini.exe
  echo Для установщика поставьте Inno Setup 6 ^(jrsoftware.org^) и запустите build.bat снова.
)
pause
exit /b 0
:err
echo Ошибка сборки. Нужен Python 3.10+ ^(python.org, галочка "Add to PATH"^).
pause
exit /b 1
