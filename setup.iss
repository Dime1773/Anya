[Setup]
AppName=File Distributor
AppVersion=1.10.6
DefaultDirName={pf}\File Distributor
DefaultGroupName=File Distributor
OutputBaseFilename=FileDistributorSetup
; SetupIconFile=... (если нужно)

[Files]
Source: "C:\Users\prosvirnin.ds\dist\main.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Users\prosvirnin.ds\Desktop\Vbros\file_distributor\ver_v1.10.6\vnesh_ip\*"; DestDir: "{app}\vnesh_ip"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\File Distributor"; Filename: "{app}\main.exe"
Name: "{autodesktop}\File Distributor"; Filename: "{app}\main.exe"
