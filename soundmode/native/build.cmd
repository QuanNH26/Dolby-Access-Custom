@echo off
rem Build audiohelper.exe with the C# compiler that ships with Windows (.NET Framework 4.x). No downloads.
cd /d "%~dp0"
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize /platform:x64 /out:audiohelper.exe audiohelper.cs
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize /platform:x64 /out:play71.exe play71.cs
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize /platform:x64 /out:bridge.exe bridge.cs
