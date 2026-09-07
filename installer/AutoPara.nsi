; Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
; NSIS installer for AutoPara.
;
; Per-user install by default: it goes to %LOCALAPPDATA%\Programs\AutoPara, needs no administrator
; rights, and triggers no UAC prompt. That matters because autostart lives in HKCU anyway, so a
; machine-wide install would buy nothing and make testing on a borrowed PC harder.
;
; Build with:  makensis installer\AutoPara.nsi
; Expects the PyInstaller output in dist\AutoPara\ (see AutoPara.spec).

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define APP_NAME     "AutoPara"
!define APP_DISPLAY  "AutoPara - Class Auto-Launcher"
!define APP_VERSION  "1.2.0"
!define APP_PUBLISHER "AutoPara"
!define APP_EXE      "AutoPara.exe"
!define UNINST_KEY   "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define RUN_KEY      "Software\Microsoft\Windows\CurrentVersion\Run"

Name "${APP_DISPLAY}"
OutFile "..\dist\AutoPara-${APP_VERSION}-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName"     "${APP_DISPLAY}"
VIAddVersionKey "FileDescription" "${APP_DISPLAY}"
VIAddVersionKey "FileVersion"     "${APP_VERSION}"
VIAddVersionKey "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright"  ""

; ---------------------------------------------------------------- UI

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Start AutoPara now"
!define MUI_FINISHPAGE_TEXT "AutoPara is installed.$\r$\n$\r$\nOn first launch it will ask for your \
timetable .docx, then your course and group."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------- install

Section "AutoPara (required)" SEC_CORE
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; Replace, never merge. A leftover module or DLL from an earlier build is loadable and wins
  ; over nothing, which is how a reinstall used to keep the old behaviour. Everything the
  ; installer owns goes first; %APPDATA%\AutoPara\schedules (the imported .docx) is untouched.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\${APP_EXE}"

  File /r "..\dist\AutoPara\*.*"

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Appear in Settings -> Apps / Add or Remove Programs.
  WriteRegStr   HKCU "${UNINST_KEY}" "DisplayName"     "${APP_DISPLAY}"
  WriteRegStr   HKCU "${UNINST_KEY}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr   HKCU "${UNINST_KEY}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr   HKCU "${UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr   HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr   HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Desktop shortcut" SEC_DESKTOP
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section "Start automatically with Windows" SEC_AUTOSTART
  ; Selected by default: the app also defaults autostart_enabled to 1, and the two must agree --
  ; a mismatch made autostart.sync() delete this entry on the first launch.
  ;
  ; Must match autostart.startup_command() in the frozen app exactly, so the app's own Settings
  ; screen sees this entry as already-enabled and can toggle it off later.
  WriteRegStr HKCU "${RUN_KEY}" "${APP_NAME}" '"$INSTDIR\${APP_EXE}" --hidden'
SectionEnd

LangString DESC_CORE      ${LANG_ENGLISH} "The AutoPara application and its runtime."
LangString DESC_DESKTOP   ${LANG_ENGLISH} "Put a shortcut on the desktop."
LangString DESC_AUTOSTART ${LANG_ENGLISH} "On by default. Launch AutoPara hidden in the system \
tray when Windows starts, so classes open even if you forget to start it. You can change this \
later in Settings."

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE}      $(DESC_CORE)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP}   $(DESC_DESKTOP)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_AUTOSTART} $(DESC_AUTOSTART)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  ; Refuse to install over a running copy: the files would be locked and the install would
  ; half-succeed.
  IfSilent skip_running_check
  FindWindow $0 "" "AutoPara - Class Auto-Launcher"
  ${If} $0 != 0
    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \
      "AutoPara is currently running.$\r$\n$\r$\nQuit it from the system tray, then press OK." \
      IDOK continue
    Abort
    continue:
  ${EndIf}
  skip_running_check:
FunctionEnd

; -------------------------------------------------------------- uninstall

Section "Uninstall"
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR"

  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"
  Delete "$DESKTOP\${APP_NAME}.lnk"

  DeleteRegValue HKCU "${RUN_KEY}" "${APP_NAME}"
  DeleteRegKey   HKCU "${UNINST_KEY}"
  DeleteRegKey   HKCU "Software\${APP_NAME}"

  ; Uninstalling removes everything the app ever wrote, the imported timetable included.
  ; (Reinstalling is the case that keeps the .docx -- see the install section.)
  RMDir /r "$APPDATA\${APP_NAME}"
SectionEnd
