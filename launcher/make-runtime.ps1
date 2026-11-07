# Build the portable Python runtime in ..\runtime (Python 3.12 embeddable + GUI/measure packages).
# Run once on any PC with internet; afterwards the whole folder works on PCs without Python.
# Downloads: python-3.12.10-embed-amd64.zip (python.org, ~11 MB) and wheels from PyPI (~80 MB).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Rt = Join-Path $Root "runtime"
$Ver = "3.12.10"
$Zip = Join-Path $env:TEMP "python-$Ver-embed-amd64.zip"
$Pkgs = @("pywebview", "numpy", "scipy", "soundcard")

if (-not (Test-Path (Join-Path $Rt "python.exe"))) {
  Write-Host "Downloading Python $Ver embeddable..."
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest "https://www.python.org/ftp/python/$Ver/python-$Ver-embed-amd64.zip" -OutFile $Zip -UseBasicParsing
  Expand-Archive $Zip $Rt -Force
  Remove-Item $Zip
}
# enable site-packages in the embeddable build
$pth = Get-ChildItem $Rt -Filter "python3*._pth" | Select-Object -First 1
$lines = @("python312.zip", ".", "Lib\site-packages", "import site")
[IO.File]::WriteAllLines($pth.FullName, $lines)
$Site = Join-Path $Rt "Lib\site-packages"
New-Item -ItemType Directory -Force $Site | Out-Null

# install wheels with the PC's own Python 3.12 (same ABI) (the embeddable build has no pip)
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "Need a Python 3.12 with pip on PATH to fill runtime\ (only for this one-time build)." }
& $py -m pip install --no-warn-script-location --upgrade --target $Site @Pkgs
if ($LASTEXITCODE -ne 0) { throw "pip failed" }

& (Join-Path $Rt "python.exe") -c "import webview, numpy, scipy, soundcard; print('runtime OK', webview.__name__, numpy.__version__, scipy.__version__)"
