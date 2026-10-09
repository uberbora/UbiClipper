; UbiClipper installer (Inno Setup 6). Built by packaging\build_windows.ps1:
;   iscc /DAppVersion=1.8.0 /DStageDir=...\dist\UbiClipper /DOutDir=...\dist ubiclipper.iss
;
; Installs for the current user only (no admin prompt) into
; %LOCALAPPDATA%\Programs\UbiClipper. Settings and the downloaded AI models
; live in %USERPROFILE%\.ubiclipper and survive updates; uninstalling asks
; whether to remove them too.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\dist\UbiClipper"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{61DDA2C9-7889-4995-8A0A-79D38E410B94}
AppName=UbiClipper
AppVersion={#AppVersion}
AppVerName=UbiClipper {#AppVersion}
AppPublisher=UbiClipper
AppPublisherURL=https://github.com/uberbora/UbiClipper
AppSupportURL=https://github.com/uberbora/UbiClipper/issues
AppUpdatesURL=https://github.com/uberbora/UbiClipper/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\UbiClipper
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=UbiClipper-Setup-{#AppVersion}
SetupIconFile=..\assets\ubiclipper.ico
UninstallDisplayIcon={app}\assets\ubiclipper.ico
UninstallDisplayName=UbiClipper
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[CustomMessages]
en.DesktopIcon=Create a desktop shortcut
tr.DesktopIcon=Masaüstü kısayolu oluştur
en.StartNow=Start UbiClipper
tr.StartNow=UbiClipper'ı başlat
en.RemoveData=Also delete your UbiClipper settings and the downloaded AI models (several GB)?%n%nChoose No to keep them for a later reinstall.
tr.RemoveData=UbiClipper ayarlarınız ve indirilen AI modelleri (birkaç GB) de silinsin mi?%n%nDaha sonra yeniden kurarsanız kullanmak için Hayır'ı seçin.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"

[InstallDelete]
; a clean Python and app on every update (old packages must not linger)
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\clipper"
Type: filesandordirs; Name: "{app}\ffmpeg"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\UbiClipper"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\ubiclipper.ico"; AppUserModelID: "UbiClipper.App"
Name: "{userdesktop}\UbiClipper"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\ubiclipper.ico"; AppUserModelID: "UbiClipper.App"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; Description: "{cm:StartNow}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; files Python writes next to the app at run time
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{%USERPROFILE}\.ubiclipper');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox(CustomMessage('RemoveData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
