Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strScriptDir

' Check for virtualenv pythonw first, else fallback to system pythonw
If fso.FileExists(strScriptDir & "\.venv\Scripts\pythonw.exe") Then
    pythonwExe = """" & strScriptDir & "\.venv\Scripts\pythonw.exe"""
ElseIf fso.FileExists(strScriptDir & "\venv\Scripts\pythonw.exe") Then
    pythonwExe = """" & strScriptDir & "\venv\Scripts\pythonw.exe"""
Else
    pythonwExe = "pythonw.exe"
End If

WshShell.Run pythonwExe & " bot.py", 0, False
