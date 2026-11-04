$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
python -m venv --system-site-packages .venv-openvoice
if ($LASTEXITCODE -ne 0) { throw 'Could not create OpenVoice environment' }
if (Test-Path -LiteralPath '.venv-audio/Lib/site-packages') {
    $sharedAudio = (Resolve-Path -LiteralPath '.venv-audio/Lib/site-packages').Path
    $escapedAudio = $sharedAudio.Replace('\','\\').Replace("'","\'")
    Set-Content -LiteralPath '.venv-openvoice/Lib/site-packages/audio_runtime.pth' -Value "import sys; sys.path.insert(0, '$escapedAudio')"
}
& '.\.venv-openvoice\Scripts\python.exe' -m pip install --timeout 60 -r requirements-openvoice.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install OpenVoice dependencies' }
& '.\.venv-openvoice\Scripts\python.exe' scripts/download_openvoice_models.py
if ($LASTEXITCODE -ne 0) { throw 'Could not verify OpenVoice model files' }
Write-Output 'OpenVoice V2 installed. Run scripts/check_openvoice.py before enabling OPENVOICE_ENABLED=true.'
