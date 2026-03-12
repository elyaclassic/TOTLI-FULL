' TOTLI HOLVA — kompyuter yonganida serverni orqa fonda ishga tushiradi (yashirin oyna)
Set fso = CreateObject("Scripting.FileSystemObject")
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = ScriptDir
' 0 = oyna yashirin, False = kutmaydi
WshShell.Run "cmd /c start_server_fon.bat", 0, False
