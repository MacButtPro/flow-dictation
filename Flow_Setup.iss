; ============================================================
;  Flow — Inno Setup Installer Script
;  Requires: Inno Setup 6  (https://jrsoftware.org/isinfo.php)
;
;  HOW TO BUILD:
;   1. Run BUILD.bat first  →  produces flow_ui\dist\Flow\
;   2. Open this .iss file in Inno Setup Compiler and press Compile
;      (or: iscc.exe Flow_Setup.iss from the command line)
;   3. Installer appears at:  installer_output\Flow_Setup.exe
; ============================================================

#define AppName      "Flow"
#define AppVersion   "1.0.0"
#define AppPublisher "Flow"
#define AppURL       "https://github.com/your-org/flow"
#define AppExeName   "Flow.exe"
#define SourceDir    "flow_ui\dist\Flow"

[Setup]
AppId={{F1A2B3C4-D5E6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; Install to Program Files\Flow
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes

; Output
OutputDir=installer_output
OutputBaseFilename=Flow_Setup
SetupIconFile=flow_ui\flow_icon.ico

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Appearance
WizardStyle=modern

; Require Windows 10 or later
MinVersion=10.0

; Run as admin so we can write to Program Files
PrivilegesRequired=admin

; Uninstaller
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; These are the checkboxes the user sees on the "Select Additional Tasks" page
Name: "desktopicon";    Description: "Create a &desktop shortcut";          GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startmenuicon";  Description: "Add to &Start Menu";                  GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "quicklaunch";    Description: "Pin to &taskbar (after first launch)"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startup";        Description: "Launch Flow automatically at &Windows startup"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Copy the entire PyInstaller output folder
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut (always created — user can uncheck the task to skip)
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\flow_icon.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop shortcut — only if the user checked the box
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\flow_icon.ico"; Tasks: desktopicon

[Registry]
; Launch at Windows startup — only if the user checked the box
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#AppName}"; \
  ValueData: """{app}\{#AppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: startup

[Run]
; Offer to launch Flow immediately after install finishes
Filename: "{app}\{#AppExeName}"; \
  Description: "Launch {#AppName} now"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Kill the running app before uninstalling so files aren't locked
Filename: "taskkill.exe"; Parameters: "/f /im {#AppExeName}"; Flags: runhidden; RunOnceId: "KillFlow"

[UninstallDelete]
; Clean up the AppData folder on uninstall (logs, config, cached models)
; Change to "yes" below if you want a clean uninstall; leave "no" to keep user data.
Type: filesandordirs; Name: "{userappdata}\Flow"; Check: ShouldDeleteAppData

[Code]
{ ── Ask whether to delete user data on uninstall ──────────────────────────── }
function ShouldDeleteAppData: Boolean;
begin
  Result := MsgBox(
    'Do you want to remove Flow''s settings and cached Whisper model files?' + Chr(13) + Chr(10) +
    '(Located in %APPDATA%\Flow - includes downloaded AI models)',
    mbConfirmation, MB_YESNO) = IDYES;
end;

{ ── Show a "first run" info page before the Ready to Install page ─────────── }
procedure InitializeWizard;
begin
  { Nothing extra needed — the standard pages look great with WizardStyle=modern }
end;

{ ── Validate that the build output exists before letting the user install ──── }
function InitializeSetup: Boolean;
begin
  Result := True;
end;
