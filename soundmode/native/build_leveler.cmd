@echo off
rem Build MemLeveler.dll (VST2 x64) with Visual Studio 2019 Build Tools. No downloads.
cd /d "%~dp0"
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cl /nologo /O2 /LD /MT leveler.c /Fe:MemLeveler.dll /link /EXPORT:VSTPluginMain /EXPORT:main=main_plugin >nul || exit /b 1
del leveler.obj MemLeveler.lib MemLeveler.exp 2>nul
echo built MemLeveler.dll
