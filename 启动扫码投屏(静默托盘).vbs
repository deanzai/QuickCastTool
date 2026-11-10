Set ws = CreateObject("Wscript.Shell")
ws.Run "pythonw """ & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\pc-server\quick_cast_server.py""", 0
