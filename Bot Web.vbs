' ============================================================================
'  Bot Web - abrir SIN ventana negra  (v4.0)
'  ---------------------------------------------------------------------------
'  Esto es lo que hay que abrir con doble clic.  Llama a "iniciar_oculto.cmd"
'  en una ventana escondida; ese archivo comprueba las dependencias y arranca
'  el programa con pythonw.exe, que no abre ninguna consola.
'
'  Los mensajes del programa (lo que antes se leia en la ventana negra) quedan
'  en  registros\consola.log  y los del arranque en  registros\arranque.log.
'  Para VERLOS mientras se abre, usa "iniciar.bat" en vez de este archivo.
' ============================================================================
Option Explicit
Dim fso, sh, carpeta, orden, codigo
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
carpeta = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(carpeta & "\iniciar_oculto.cmd") Then
    MsgBox "No se encuentra iniciar_oculto.cmd junto a este archivo." & vbCrLf & _
           "Copia la carpeta completa de Bot Web.", 16, "Bot Web"
    WScript.Quit 1
End If

sh.CurrentDirectory = carpeta
orden = "cmd /c """"" & carpeta & "\iniciar_oculto.cmd"""
Dim i
For i = 0 To WScript.Arguments.Count - 1
    orden = orden & " """ & WScript.Arguments(i) & """"
Next
orden = orden & """"

' 0 = ventana escondida;  True = esperar (asi se puede avisar si algo falla)
codigo = sh.Run(orden, 0, True)

If codigo <> 0 Then
    MsgBox "Bot Web no se pudo abrir (codigo " & codigo & ")." & vbCrLf & vbCrLf & _
           "Mira el archivo:" & vbCrLf & carpeta & "\registros\arranque.log" & vbCrLf & vbCrLf & _
           "O abre ""iniciar.bat"" para ver los mensajes en pantalla.", 48, "Bot Web"
End If
