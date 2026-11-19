; Instalador de Windows (Inno Setup 6) del gestor de la traducción al español de Star Citizen.
; Compilar desde la raíz del repositorio, después de PyInstaller:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 installer\setup.iss
; Resultado: Output\StarCitizen_Traduccion_ES_Setup.exe

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "SCTraduccionES.exe"

[Setup]
AppId={{8C1B4A52-7E1D-4F57-9C3E-5A2B6F0D9E11}
AppName=Traducción al español de Star Citizen
AppVersion={#AppVersion}
AppVerName=Traducción al español de Star Citizen {#AppVersion}
AppPublisher=0zzyt0 (proyecto de la comunidad)
AppPublisherURL=https://github.com/0zzyt0/StarCitizen-Traduccion-ES
AppSupportURL=https://github.com/0zzyt0/StarCitizen-Traduccion-ES/issues
AppUpdatesURL=https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases
; Instalación por usuario, sin permisos de administrador (%LOCALAPPDATA%\Programs\SC-Traduccion-ES)
PrivilegesRequired=lowest
DefaultDirName={autopf}\SC-Traduccion-ES
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\Output
OutputBaseFilename=StarCitizen_Traduccion_ES_Setup
SetupIconFile=..\assets\icono.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName=Traducción al español de Star Citizen
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; El gestor crea este mutex: el instalador pedirá cerrarlo antes de actualizarlo.
AppMutex=SCTraduccionES_Mutex
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Instalador de la traducción al español de Star Citizen

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
es.WelcomeLabel2=Se instalará el gestor de la traducción al español de Star Citizen.%n%nAl terminar se abrirá un asistente que detecta el juego, instala la traducción y, si quieres, la mantiene actualizada automáticamente.%n%nProyecto de la comunidad, no oficial de Cloud Imperium Games.

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[InstallDelete]
; Limpia restos de una versión anterior del gestor (no toca la configuración ni el juego).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\SCTraduccionES\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Traducción Star Citizen"; Filename: "{app}\{#AppExe}"; Comment: "Instalar, actualizar o desinstalar la traducción al español"
Name: "{autoprograms}\Desinstalar traducción Star Citizen"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Traducción Star Citizen"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir el asistente de la traducción"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Elimina la tarea programada y pregunta si quitar también la traducción del juego.
Filename: "{app}\{#AppExe}"; Parameters: "--uninstall-cleanup"; RunOnceId: "LimpiezaTraduccionSC"; Flags: waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
