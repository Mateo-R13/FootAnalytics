; Installeur Windows de FootAnalytics (Inno Setup 6).
; Installation par utilisateur : aucun droit administrateur requis.
; Compilé par build.ps1 :  ISCC /DAppVersion=x.y.z installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F2C1B7E-3E8A-4F7D-9C5B-FA0A1C2D3E4F}
AppName=FootAnalytics
AppVersion={#AppVersion}
AppPublisher=Mateo-R13
AppPublisherURL=https://github.com/Mateo-R13/FootAnalytics
AppSupportURL=https://github.com/Mateo-R13/FootAnalytics/issues
DefaultDirName={localappdata}\Programs\FootAnalytics
DefaultGroupName=FootAnalytics
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=FootAnalytics-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\FootAnalytics.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "dist\FootAnalytics\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FootAnalytics"; Filename: "{app}\FootAnalytics.exe"
Name: "{group}\Désinstaller FootAnalytics"; Filename: "{uninstallexe}"
Name: "{userdesktop}\FootAnalytics"; Filename: "{app}\FootAnalytics.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FootAnalytics.exe"; Description: "Lancer FootAnalytics"; Flags: nowait postinstall skipifsilent
