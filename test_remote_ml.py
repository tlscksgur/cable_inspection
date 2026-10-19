import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from remote_ml import RemoteBackend, RemoteProcess, parse_gpu_csv


class RemoteProgressTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).parent/'.verification';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.proc=object.__new__(RemoteProcess)
        self.proc.folder=Path(self.temp.name)
        self.proc.status_lock=threading.Lock();self.proc.latest_status={};self.proc.code=None

    def tearDown(self):self.temp.cleanup()

    def test_windows_replace_denial_does_not_fail_job_or_lose_live_progress(self):
        with patch.object(Path,'replace',side_effect=PermissionError(5,'Access denied')):
            self.proc.status(step=720,total_steps=1013,progress=0,message='uploading')
        self.assertIsNone(self.proc.poll())
        self.assertEqual(self.proc.progress_snapshot()['step'],720)
        self.assertFalse(list(self.proc.folder.glob('*.tmp')))
        self.proc.status(step=721,message='uploading')
        self.assertEqual(json.loads((self.proc.folder/'status.json').read_text())['step'],721)

    def test_snapshot_is_a_copy(self):
        self.proc.status(step=5)
        snapshot=self.proc.progress_snapshot();snapshot['step']=99
        self.assertEqual(self.proc.progress_snapshot()['step'],5)

    def test_server_gpu_metrics_and_unavailable_values(self):
        rows=parse_gpu_csv('0, NVIDIA RTX PRO 6000 Blackwell, 12, 2093, 97887, 45\n1, Other GPU, N/A, 100, 24000, N/A')
        self.assertEqual(rows[0]['utilization'],12)
        self.assertEqual(rows[0]['memory_total_mib'],97887)
        self.assertEqual(rows[0]['temperature'],45)
        self.assertIsNone(rows[1]['utilization'])
        self.assertIsNone(rows[1]['temperature'])


class ResumeCheckpointTests(unittest.TestCase):
    def test_latest_complete_epoch_is_selected_without_accepting_other_paths(self):
        from types import SimpleNamespace as NS
        from unittest.mock import MagicMock
        backend=object.__new__(RemoteBackend);backend.client=MagicMock()
        sftp=backend.client.open_sftp.return_value.__enter__.return_value
        sftp.normalize.side_effect=lambda path:path
        sftp.listdir_attr.return_value=[NS(filename='epoch_2.pth',st_size=100),NS(filename='epoch_10.pth',st_size=100),NS(filename='epoch_11.pth',st_size=0),NS(filename='best_coco_segm_mAP_50_epoch_12.pth',st_size=100)]
        path,epoch=backend.training_checkpoint('0123456789abcdef')
        self.assertEqual(epoch,10);self.assertTrue(path.endswith('/epoch_10.pth'))
        with self.assertRaises(ValueError):backend.training_checkpoint('../other-account')
        sftp.normalize.side_effect=lambda path:'/different/path'
        with self.assertRaises(ValueError):backend.training_checkpoint('0123456789abcdef')

if __name__=='__main__':unittest.main()
