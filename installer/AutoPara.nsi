; NSIS installer for AutoPara -- the only installer in this project.
;
; It ships the frozen PyInstaller bundle, so the target machine needs nothing at all: no Python,
; no PySide6, no network. That is the whole argument for it over an install-from-source script,
; which has to find or install Python and then download ~100 MB of wheels before the app can run.
;
; Per-user by design: it installs to %LOCALAPPDATA%\Programs\AutoPara, needs no administrator
; rights and raises no UAC prompt. Autostart lives in HKCU anyway, so a machine-wide install would
; buy nothing while making it harder to try on a borrowed PC.
;
; Build with:  .\build.cmd        (or: makensis installer\AutoPara.nsi)
; Expects the PyInstaller output in dist\AutoPara\ (see AutoPara.spec).
;
; This file is UTF-8 with BOM on purpose: `Unicode true` plus a BOM is what lets makensis read the
; Ukrainian strings below. Without the BOM it falls back to the system code page and mangles them.

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define APP_NAME     "AutoPara"
; Must stay identical to MainWindow.setWindowTitle(), or the "is it running?" check below silently
; never matches and the install writes over locked files. tests/test_installer.py asserts this.
!define APP_DISPLAY  "AutoPara — автозапуск пар"
!define APP_VERSION  "1.5.0"
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

; ---------------------------------------------------------------- UI

; The same .ico the executable carries, so a downloaded Setup.exe is recognisable before it has
; installed anything. build.ps1 renders it from ui/tray.write_ico before calling makensis; the
; guard is here because makensis can also be run on its own, and a missing icon should cost the
; NSIS default rather than the whole build.
!if /FileExists "..\build\AutoPara.ico"
  !define MUI_ICON   "..\build\AutoPara.ico"
  !define MUI_UNICON "..\build\AutoPara.ico"
!endif

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Запустити AutoPara"
!define MUI_FINISHPAGE_TEXT "AutoPara встановлено.$\r$\n$\r$\nПри першому запуску перетягніть \
у вікно файл розкладу (.docx), а потім оберіть свій курс і групу."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Ukrainian"

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=${LANG_UKRAINIAN} "ProductName"     "${APP_DISPLAY}"
VIAddVersionKey /LANG=${LANG_UKRAINIAN} "FileDescription" "${APP_DISPLAY}"
VIAddVersionKey /LANG=${LANG_UKRAINIAN} "FileVersion"     "${APP_VERSION}"
VIAddVersionKey /LANG=${LANG_UKRAINIAN} "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey /LANG=${LANG_UKRAINIAN} "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=${LANG_UKRAINIAN} "LegalCopyright"  "${APP_PUBLISHER}"

; ---------------------------------------------------------------- install

Section "AutoPara (обов'язково)" SEC_CORE
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; Replace, never merge. A PyInstaller bundle changes between builds, and a module left behind
  ; from an older one stays importable -- which is exactly why a "reinstall and check" can keep
  ; showing the old behaviour.
  RMDir /r "$INSTDIR\_internal"

  File /r "..\dist\AutoPara\*.*"

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

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
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Видалити ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Ярлик на робочому столі" SEC_DESKTOP
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section "Запускати разом із Windows" SEC_AUTOSTART
  ; Must match autostart.startup_command() for a frozen build exactly, so the app's own settings
  ; screen sees this entry as already enabled instead of rewriting it on the next launch.
  ; tests/test_installer.py asserts the two stay identical.
  WriteRegStr HKCU "${RUN_KEY}" "${APP_NAME}" '"$INSTDIR\${APP_EXE}" --hidden'
SectionEnd

LangString DESC_CORE      ${LANG_UKRAINIAN} "Програма AutoPara та все, що їй потрібно для роботи."
LangString DESC_DESKTOP   ${LANG_UKRAINIAN} "Створити ярлик на робочому столі."
LangString DESC_AUTOSTART ${LANG_UKRAINIAN} "Запускати AutoPara у трей разом із Windows, щоб пари \
відкривалися навіть тоді, коли ви забули увімкнути програму. Це можна змінити в налаштуваннях."

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE}      $(DESC_CORE)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP}   $(DESC_DESKTOP)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_AUTOSTART} $(DESC_AUTOSTART)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  ; Installing over a running copy locks the files and half-succeeds. A silent install skips the
  ; prompt rather than blocking on an invisible message box.
  IfSilent skip_running_check
  FindWindow $0 "" "${APP_DISPLAY}"
  ${If} $0 != 0
    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \
      "AutoPara зараз працює.$\r$\n$\r$\nЗакрийте її через значок у треї та натисніть OK." \
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
  Delete "$SMPROGRAMS\${APP_NAME}\Видалити ${APP_NAME}.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"
  Delete "$DESKTOP\${APP_NAME}.lnk"

  DeleteRegValue HKCU "${RUN_KEY}" "${APP_NAME}"
  DeleteRegKey   HKCU "${UNINST_KEY}"
  DeleteRegKey   HKCU "Software\${APP_NAME}"

  ; The imported timetable and settings live in %APPDATA%\AutoPara. Keep them unless the user says
  ; otherwise, so reinstalling does not lose the schedule. A silent uninstall always keeps them
  ; rather than blocking on a prompt.
  IfSilent keep_data
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Видалити також збережений розклад і налаштування?$\r$\n$\r$\n$APPDATA\${APP_NAME}" \
    IDNO keep_data
  RMDir /r "$APPDATA\${APP_NAME}"
  keep_data:
SectionEnd
