# Cable Inspection — RTMDet-Ins

RTMDet-Ins S/M/L/X 기반 케이블 검사·라벨링·학습·모델 관리 웹입니다.
별도 이미지 테스트 화면에서 서버 CUDA 또는 로컬 ONNX CPU 추론을 선택합니다.

## 실행

Python 3.10 이상:

```powershell
python -m pip install -r requirements-client.txt
python server.py --data-dir data --port 8898
```

학습·관리 웹: http://127.0.0.1:8898/
DB는 빈 상태로 시작합니다. 모델을 등록하거나 `import_backup.py` / `import_models.py`로
별도 자료를 복원합니다. 촬영 자료·DB·가중치·운영 기록은 이 저장소에 포함하지 않습니다.

## 서버 설정과 이미지 검사

`server_settings.py`는 예시값을 사용합니다. 실제 접속 정보는 다음 환경변수로 지정합니다.
SSH 호스트 키는 사전에 확인하여 known_hosts에 등록해야 합니다.

```powershell
$env:CABLE_SSH_HOST = 'your-gpu-server'
$env:CABLE_SSH_USER = 'your-account'
$env:CABLE_REMOTE_ROOT = '/your/workspace/studio_rebuild'
$env:CABLE_REMOTE_PYTHON = '/your/env/bin/python'
$env:CABLE_MMDET_ROOT = '/your/mmdetection'
python test_service.py --data-dir data
```

검사 웹: http://127.0.0.1:8899/
SSH 비밀번호는 실행 시 입력하며 저장하지 않습니다. 현재 검사 서비스는
로컬 CPU 실행을 선택해도 모델 준비를 위해 승인된 GPU 서버 연결이 필요합니다.
서버의 CUDA·PyTorch·MMCV·MMDetection 환경은 별도로 구성해야 합니다.
모델 설정의 기존 절대 경로는 새 환경에서 맞춰야 합니다.

물방울·시리얼은 정상 클래스입니다. 이미지의 실제 높이를 유지하고
결과에 원본 좌표의 박스·마스크 윤곽·종류·점수·실행 장치를 표시합니다.
점수는 이미지 전체의 결함 확률이 아닙니다.

## 검증

```powershell
$env:PYTHONUTF8 = '1'
python -m unittest discover -s . -p "test_*.py" -v
```

이 저장소의 테스트는 임시 데이터·모의 ML 환경을 사용합니다.
실제 GPU 추론·성능 평가는 모델과 데이터가 준비된 환경에서 별도로 수행해야 합니다.
