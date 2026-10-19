# Use an existing MMDetection CUDA environment. No packages are installed by the app.
# Paths below are examples; fill in real paths before launching.
$env:STUDIO_ML_PYTHON = 'C:\path\to\mmdet-env\python.exe'
$env:STUDIO_MMDET_ROOT = 'C:\path\to\mmdetection'
# Optional separate writable storage for this app only:
# $env:STUDIO_DATA_DIR = 'C:\path\to\studio-data'
python "$PSScriptRoot\server.py" --port 8898
