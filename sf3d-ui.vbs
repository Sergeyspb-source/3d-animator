' Double-click to start 3d-animator (the interface) with no console windows.
' Closing the app window also stops the server and frees GPU memory.
' For debugging with a visible console use sf3d-ui.bat instead.
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\tool\launch_ui.ps1""", 0, False
