Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
strPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPython = strPath & "\.venv\Scripts\pythonw.exe"
strMain = strPath & "\main.py"
objShell.Run """" & strPython & """ """ & strMain & """", 0, False
