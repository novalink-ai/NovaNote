; ============================================================================
;  NovaNote · 星笺 —— Windows 安装包脚本（Inno Setup 6）
;
;  编译：ISCC.exe installer.iss
;  或：  python build_exe.py --installer
;
;  产物：dist\NovaNote-1.0.0-setup.exe
; ============================================================================

#define AppName        "NovaNote"
#define AppNameCN      "星笺"
#define AppVersion     "1.0.0"
#define AppPublisher   "NovaLab"
#define AppExeName     "NovaNote.exe"
#define AppURL         "https://github.com/novalab/novanote"

[Setup]
; —— 应用标识（升级安装靠它识别，切勿更改）——
AppId={{61E8FC4D-069E-525A-9BC8-62A31A89E028}
AppName={#AppName} · {#AppNameCN}
AppVersion={#AppVersion}
AppVerName={#AppName} · {#AppNameCN} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}

; —— 安装位置：默认装到当前用户目录，无需管理员权限 ——
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName} · {#AppNameCN}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes

; —— 权限：默认「仅为我安装」，也允许用户选择「为所有用户安装」——
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; —— 平台 ——
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=6.1sp1

; —— 输出 ——
OutputDir=dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile=novanote\assets\logo.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} · {#AppNameCN}

; —— 外观 ——
WizardStyle=modern
WizardSizePercent=110
WizardImageFile=installer\wizard-large.bmp
WizardSmallImageFile=installer\wizard-small.bmp
WizardImageStretch=no

; —— 压缩 ——
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4

; —— 安装时自动关闭正在占用文件的程序（Restart Manager）——
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no

[Languages]
Name: "chinese"; MessagesFile: "installer\languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName} · {#AppNameCN}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName} · {#AppNameCN}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName} · {#AppNameCN}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 安装目录内的运行期残留（若应用曾把日志写到此处）
Type: filesandordirs; Name: "{app}\logs"

; ============================================================================
;  安装 / 卸载逻辑
; ============================================================================
[Code]
var
  RemoveUserData: Boolean;

{ —— 安装前：若程序正在运行，请用户先关闭 —— }
function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
  TmpFile: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := False;
  TmpFile := ExpandConstant('{tmp}\nnprocs.txt');
  if Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq {#AppExeName}" /NH > "' + TmpFile + '"',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    if LoadStringsFromFile(TmpFile, Lines) then
      for I := 0 to GetArrayLength(Lines) - 1 do
        if Pos(LowerCase('{#AppExeName}'), LowerCase(Lines[I])) > 0 then
          Result := True;
  end;
  DeleteFile(TmpFile);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  { 静默安装（如批量部署）时不打扰用户 }
  if WizardSilent() then
    Exit;
  while IsAppRunning() do
  begin
    if MsgBox('检测到 {#AppName} · {#AppNameCN} 正在运行。' + #13#10 + #13#10 +
              '请先关闭程序再继续安装，否则部分文件可能无法更新。' + #13#10 +
              '关闭后可点击「重试」，或点击「取消」退出安装。',
              mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

{ —— 卸载前：询问是否一并删除个人配置 —— }
function InitializeUninstall(): Boolean;
begin
  Result := True;
  { 静默卸载时保留用户数据（更安全，避免误删） }
  if UninstallSilent() then
  begin
    RemoveUserData := False;
    Exit;
  end;
  RemoveUserData := MsgBox('是否同时删除 NovaNote 的个人配置与偏好设置？' + #13#10 + #13#10 +
                           '位置：' + ExpandConstant('{userappdata}\NovaNote') + #13#10 + #13#10 +
                           '注意：您的工作空间（笔记与文献数据）存放在另外的目录，' + #13#10 +
                           '不会被删除。',
                           mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
    DelTree(ExpandConstant('{userappdata}\NovaNote'), True, True, True);
end;
