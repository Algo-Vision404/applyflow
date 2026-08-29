Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = folder & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then
  pyw = "pythonw.exe"
End If
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = folder
sh.Run """" & pyw & """ -m applyflow gui", 0, False
