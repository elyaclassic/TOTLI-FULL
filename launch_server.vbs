' Server ni oynasiz (yashirin) ishga tushiradi — hech qanday oyna ochilmaydi
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' O'zgaruvchilar (start.bat dan o'tkaziladi yoki default)
bindHost = CreateObject("WScript.Shell").Environment("Process")("BIND_HOST")
If bindHost = "" Then bindHost = "0.0.0.0"
port = CreateObject("WScript.Shell").Environment("Process")("PORT")
If port = "" Then port = "8080"
pythonCmd = CreateObject("WScript.Shell").Environment("Process")("PYTHON_CMD")
If pythonCmd = "" Then pythonCmd = "python"

' python yo'li bo'shliq bo'lsa qo'shtirnoqda
If InStr(pythonCmd, " ") > 0 And Left(pythonCmd, 1) <> """" Then
    pythonCmd = """" & pythonCmd & """"
End If

cmdLine = "cmd /c cd /d " & Chr(34) & scriptDir & Chr(34) & " && " & pythonCmd & " -m uvicorn main:app --host " & bindHost & " --port " & port & " --reload"
WshShell.Run cmdLine, 0, False
' 0 = oyna yashirin, False = kutmasdan davom etadi
