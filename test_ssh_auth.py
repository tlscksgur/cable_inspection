import tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import ssh_auth
class SSHAuthTests(unittest.TestCase):
 def test_no_credential_is_saved_or_guessed(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.verification') as folder:
   lib=MagicMock();client=lib.SSHClient.return_value
   with patch.object(ssh_auth,'KEY_FILE',Path(folder)/'missing'):
    with self.assertRaises(RuntimeError):ssh_auth.open_client(lib)
   client.connect.assert_not_called()
 def test_key_connection_uses_only_explicit_key_and_known_host_check(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.verification') as folder:
   key=Path(folder)/'key';key.write_text('mock path only');lib=MagicMock()
   with patch.object(ssh_auth,'KEY_FILE',key):ssh_auth.open_client(lib)
   client=lib.SSHClient.return_value;client.load_system_host_keys.assert_called_once();client.set_missing_host_key_policy.assert_called_once_with(lib.RejectPolicy.return_value)
   args=client.connect.call_args.kwargs;self.assertEqual(args['key_filename'],str(key));self.assertNotIn('password',args);self.assertFalse(args['allow_agent']);self.assertFalse(args['look_for_keys'])
 def test_manual_password_remains_available_in_memory(self):
  lib=MagicMock()
  with patch.object(ssh_auth,'auto_available',return_value=False):ssh_auth.open_client(lib,'session-only-example')
  self.assertEqual(lib.SSHClient.return_value.connect.call_args.kwargs['password'],'session-only-example')
if __name__=='__main__':unittest.main()
