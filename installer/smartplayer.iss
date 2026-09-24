; SmartPlayer Windows 安装脚本（Inno Setup 6）
; 由 GitHub Actions 在构建时调用 ISCC.exe 编译
#define MyAppName "SmartPlayer"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SmartPlayer"
#define MyAppExeName "SmartPlayer.exe"

[Setup]
AppId={{125B1B25-D380-48FA-ABCE-C3528609B9FE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=installer-out
OutputBaseFilename=SmartPlayer-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName={#MyAppName}
DisableProgramGroupPage=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
; 主程序（PyInstaller 打包产物，路径相对于本脚本所在目录）
Source: "..\dist\SmartPlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 中文配音语音（Piper TTS），装到用户数据目录，免去手动放置
Source: "assets\tts\*"; DestDir: "{userappdata}\SmartPlayer\models\tts"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
