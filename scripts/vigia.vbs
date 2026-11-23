' Abre o vigia do Jarvis (vigia.ps1) sem janela. Usado pelo iniciar-jarvis.cmd.
Set sh = CreateObject("WScript.Shell")
pasta = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & pasta & "\vigia.ps1""", 0, False
