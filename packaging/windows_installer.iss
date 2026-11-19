; Inno Setup 脚本：把 PyInstaller 单目录产物封装为 Windows 安装程序。
; 先执行：powershell -File packaging/build_windows.ps1 -Clean
; 再执行：ISCC packaging/windows_installer.iss

#define AppName "Caos BioGuard Kiosk"
#define AppVersion "0.2.0"
#define AppPublisher "Caos BioGuard"
#define BuildDir "dist\CaosBioGuardKiosk"

[Setup]
AppId={{CAOSBIOGUARD-KIOSK-EDGE-001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\CaosBioGuardKiosk
DefaultGroupName={#AppName}
OutputDir=dist\installer
OutputBaseFilename=CaosBioGuardKioskSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\CaosBioGuardKiosk.exe
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"
Name: "english"; MessagesFile: "compiler:Languages\English.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面图标"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\CaosBioGuardKiosk.exe"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Caos BioGuard"; Filename: "{app}\CaosBioGuardKiosk.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CaosBioGuardKiosk.exe"; Description: "启动 Caos BioGuard Kiosk"; Flags: nowait postinstall skipifsilent
