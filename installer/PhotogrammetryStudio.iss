; Inno Setup script for Photogrammetry Studio (Windows).
;
; Build the app first, then compile this installer:
;     pyinstaller PhotogrammetryStudio-win.spec --noconfirm
;     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\PhotogrammetryStudio.iss
;
; Output: installer\Output\PhotogrammetryStudio-Setup.exe
;
; Note: this packages the APP only. Reconstruction needs RealityScan (free,
; realityscan.com) or Meshroom (needs an NVIDIA GPU) installed separately.

#define MyAppName "Photogrammetry Studio"
#define MyAppVersion "0.3.0"
#define MyAppPublisher "Team Oceanus / GNC"
#define MyAppExe "PhotogrammetryStudio.exe"

[Setup]
AppId={{7C2A9E1B-6F3D-4A2C-9E8B-PHOTOGRAMMETRY}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Photogrammetry Studio
DefaultGroupName=Photogrammetry Studio
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=PhotogrammetryStudio-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Install per-user so no admin/UAC prompt is required.
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The entire PyInstaller onedir output.
Source: "..\dist\PhotogrammetryStudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
