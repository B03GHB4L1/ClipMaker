; Before the rename, the app was clipmaker.exe and the engine
; backend\clipmaker-server.exe, in the same install folder. An upgrade installs
; the new names beside them, so remove the old programs; uninstall does the same
; in case an older upgrade left them. Projects live elsewhere and are untouched.

!macro VIZORPLAY_REMOVE_PRE_RENAME_FILES
  Delete "$INSTDIR\clipmaker.exe"
  Delete "$INSTDIR\backend\clipmaker-server.exe"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  !insertmacro VIZORPLAY_REMOVE_PRE_RENAME_FILES
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  !insertmacro VIZORPLAY_REMOVE_PRE_RENAME_FILES
!macroend
