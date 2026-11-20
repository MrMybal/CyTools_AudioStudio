"""The delivered native stack exposes the effective complete Tool catalogue."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from tool import create_runtime
from cytools_core.transports._native import NativeHost
from cytools_core.transports.api import LocalClient
class NativeCommunicationTests(unittest.TestCase):
 def test_native_discovery_and_task_cleanup(self):
  with tempfile.TemporaryDirectory() as temp:
   with create_runtime(Path(temp)/'jobs') as runtime:
    actor=runtime.authenticate(runtime.create_client('Native test')['token'])
    with NativeHost(client=LocalClient(runtime,actor)) as host:
     catalogue=host.call('sdk',request={'method':'describe'})
     names={x['name'] for x in catalogue['operations']}
     self.assertIn('cy_submit_job',names)
     self.assertIn('cy_export_job',names)
     job=host.call('sdk',request={'method':'invoke','name':'op_ai_communication_status','arguments':{'parameters':{'includeOperations':True}}})['result']
     result=runtime.wait(actor,job['jobId'])
     self.assertEqual(result['state'],'Completed',result.get('error'))
     status=result['outputs']
     self.assertEqual(status['native'],{'abi':1,'version':'0.12.0','cymcp':'0.7.1','cymcpRevision':'34d4bcae126bc83d1a2925b5047dac36e3d09d92'})
     self.assertEqual(status['operations'],runtime.descriptor['operations'])
     self.assertTrue(status['taskFiles']['exportBeforeFinish'])
    self.assertTrue(runtime.get_job(actor,job['jobId'])['artifactsDeleted'])
if __name__=='__main__':unittest.main()
