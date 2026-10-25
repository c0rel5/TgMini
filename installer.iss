; Установщик TgMini (Inno Setup 6). Ставится в профиль пользователя, права администратора не нужны.
#define AppName "TgMini"
#define AppVer "2.0"

[Setup]
AppId={{9B7C2D1E-4F6A-4C0B-8E3D-2A5B7C9D1E44}
AppName={#AppName}
AppVersion={#AppVer}
DefaultDirName={localappdata}\Programs\TgMini
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=TgMini-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\TgMini.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; Flags: unchecked

[Files]
Source: "dist\TgMini\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\TgMini"; Filename: "{app}\TgMini.exe"
Name: "{autodesktop}\TgMini"; Filename: "{app}\TgMini.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TgMini.exe"; Description: "Запустить TgMini"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM TgMini.exe"; Flags: runhidden; RunOnceId: "KillTgMini"

[UninstallDelete]
; программа, а также все данные: сессия, настройки, плагины, временные файлы
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{userappdata}\TgMini"
