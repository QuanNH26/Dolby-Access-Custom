@echo off
rem Build "Dolby Access Custom.exe" (portable launcher) with the C# compiler that ships with Windows. No downloads.
cd /d "%~dp0"
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize /target:winexe /win32icon:app.ico /r:System.Windows.Forms.dll /out:"..\Dolby Access Custom.exe" launcher.cs
