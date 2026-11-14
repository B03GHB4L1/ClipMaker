; Before the rename, the app was clipmaker.exe and the engine
; backend\clipmaker-server.exe, in the same install folder. An upgrade installs
; the new names beside them, so remove the old programs; uninstall does the same
; in case an older upgrade left them. Projects live elsewhere and are untouched.

!macro VIZORPLAY_REMOVE_PRE_RENAME_FILES
  Delete "$INSTDIR\clipmaker.exe"
  Delete "$INSTDIR\backend\clipmaker-server.exe"
!macroend

; Windows keeps its own copy of each program's icon and keeps showing it after an
; update changes the icon (the shortcuts still point at the same vizorplay.exe).
; SHCNE_ASSOCCHANGED (0x08000000) tells Explorer to drop that copy and redraw.
!macro VIZORPLAY_REFRESH_ICONS
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend

!macro NSIS_HOOK_POSTINSTALL
  !insertmacro VIZORPLAY_REMOVE_PRE_RENAME_FILES
  !insertmacro VIZORPLAY_REFRESH_ICONS
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  !insertmacro VIZORPLAY_REMOVE_PRE_RENAME_FILES
!macroend
