"""Example deployment settings. Override with environment variables before launch."""
import os
HOST=os.environ.get('CABLE_SSH_HOST','gpu.example.internal')
USER=os.environ.get('CABLE_SSH_USER','cable')
ROOT=os.environ.get('CABLE_REMOTE_ROOT','/srv/cable/cable_rtmdet/studio_rebuild')
PYTHON=os.environ.get('CABLE_REMOTE_PYTHON','/srv/cable/cable_rtmdet/env/bin/python')
MMDET_ROOT=os.environ.get('CABLE_MMDET_ROOT','/srv/cable/cable_rtmdet/mmdetection')
