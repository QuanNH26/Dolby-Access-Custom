# hesuvi-control

- `golden/` - the HeSuVi / Equalizer APO config files the app installs (`soundmode/native/install.ps1`).
- `livecheck.py` - plays ~5 s of quiet noise and checks the live audio path (Activity > *Live check*).
- `hesuvi.ps1` - command-line control kept for the optional logon check task (`tools/setup-tasks.ps1`):
  `powershell -ExecutionPolicy Bypass -File hesuvi.ps1 <status|on|off|dyn-on|dyn-off|repair|rebind|save-golden>`.
