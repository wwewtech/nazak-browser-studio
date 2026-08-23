Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

exePath = currentDir & "\dist\NazakBrowserStudio\NazakBrowserStudio.exe"

If fso.FileExists(exePath) Then
    WshShell.Run Chr(34) & exePath & Chr(34), 0, False
Else
    WshShell.Run "pythonw -m nazak.main --mode gui", 0, False
End If
