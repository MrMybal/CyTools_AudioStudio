"""Real product runtime through native Free/Protected HTTP and MCP."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import urllib.request

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from tool import create_runtime
from cytools_core import CyToolError
from cytools_core.transports.http import make_server, HTTPClient

REVISION='34d4bcae126bc83d1a2925b5047dac36e3d09d92'

class LocalMCPProfileTests(unittest.TestCase):
 def setUp(self):
  self.previous_token=os.environ.pop('CYTOOLS_TOKEN',None)
 def tearDown(self):
  os.environ.pop('CYTOOLS_TOKEN',None)
  if self.previous_token is not None:os.environ['CYTOOLS_TOKEN']=self.previous_token
 def wait(self,client,job):
  for _ in range(250):
   value=client.call('GetJob',jobId=job['jobId'])
   if value['state'] in ('Completed','Failed','Cancelled'):break
   time.sleep(.02)
  self.assertEqual(value['state'],'Completed',value.get('error'))
  return value

 def test_free_product_read_export_write_and_argument_validation(self):
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp)
   with create_runtime(base/'jobs') as runtime:
    server=make_server(runtime)
    try:
     self.assertEqual(server.access['accessProfile'],'free')
     client=HTTPClient(f'http://127.0.0.1:{server.server_port}/v1')
     self.assertEqual(client.call('DescribeTool')['id'],runtime.descriptor['id'])
     task=client.call('CreateSession')['sessionId']
     source=base/'source.txt';source.write_text('temporary input copy','utf-8')
     imported=client.call('ImportFile',sessionId=task,source=str(source))
     copy=Path(imported['path'])
     self.assertNotEqual(copy,source)
     self.assertEqual(copy.read_text('utf-8'),'temporary input copy')
     job=client.call('SubmitJob',sessionId=task,operationId='ai_communication_status',parameters={'includeOperations':True})
     done=self.wait(client,job)
     self.assertEqual(done['outputs']['native']['cymcpRevision'],REVISION)
     self.assertEqual(done['outputs']['operations'],runtime.descriptor['operations'])
     exported=client.call('ExportJob',jobId=job['jobId'],destination=str(base/'retained'))
     self.assertTrue(Path(exported['directory']).is_dir())
     with self.assertRaises(CyToolError) as invalid:
      client.call('SubmitJob',sessionId=task,operationId='ai_communication_status',parameters={'includeOperations':'invalid'})
     self.assertEqual(invalid.exception.code,'InvalidParameters')
     client.call('FinishTask',sessionId=task)
     self.assertTrue(client.call('GetJob',jobId=job['jobId'])['artifactsDeleted'])
     self.assertFalse(copy.exists())
     self.assertEqual(source.read_text('utf-8'),'temporary input copy')
     self.assertTrue(Path(exported['directory']).is_dir())
    finally:server.shutdown();server.server_close()

 def test_explicit_protected_product_profile_preserved_and_requires_token(self):
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp);jobs=base/'jobs';jobs.mkdir()
   config=jobs/'communication.json'
   config.write_text(json.dumps({'schemaVersion':1,'accessProfile':'protected_access'}),'utf-8')
   with create_runtime(jobs) as runtime:
    credential=runtime.create_client('Protected test')
    server=make_server(runtime)
    try:
     self.assertEqual(server.access['accessProfile'],'protected_access')
     self.assertEqual(json.loads(config.read_text())['accessProfile'],'protected_access')
     url=f'http://127.0.0.1:{server.server_port}/v1'
     with self.assertRaises(CyToolError) as denied:HTTPClient(url).call('DescribeTool')
     self.assertEqual(denied.exception.code,'AuthenticationRequired')
     self.assertEqual(HTTPClient(url,credential['token']).call('DescribeTool')['id'],runtime.descriptor['id'])
    finally:server.shutdown();server.server_close()

 def test_real_product_mcp_http_without_token(self):
  with tempfile.TemporaryDirectory() as temp:
   with create_runtime(Path(temp)/'jobs') as runtime:
    server=make_server(runtime);session_headers={}
    def call(method,params):
     payload={'jsonrpc':'2.0','id':1,'method':method,'params':params}
     headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream',**session_headers}
     request=urllib.request.Request(server.mcp_url,data=json.dumps(payload).encode(),headers=headers)
     with urllib.request.urlopen(request,timeout=15) as response:
      if response.headers.get('Mcp-Session-Id'):
       session_headers.update({'Mcp-Session-Id':response.headers['Mcp-Session-Id'],'MCP-Protocol-Version':'2025-11-25'})
      reply=json.load(response)
     self.assertNotIn('error',reply,reply)
     return reply['result']
    def tool(name,args):
     reply=call('tools/call',{'name':name,'arguments':args})
     self.assertFalse(reply.get('isError',False),reply)
     return json.loads(reply['content'][0]['text'])
    try:
     call('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'product-test','version':'1'}})
     self.assertEqual(tool('cy_describe',{})['id'],runtime.descriptor['id'])
     job=tool('op_ai_communication_status',{'parameters':{'includeOperations':True}})
     for _ in range(250):
      done=tool('cy_get_job',{'jobId':job['jobId']})
      if done['state'] in ('Completed','Failed','Cancelled'):break
      time.sleep(.02)
     self.assertEqual(done['state'],'Completed',done.get('error'))
     self.assertEqual(done['outputs']['native']['cymcpRevision'],REVISION)
     tool('cy_finish_task',{'sessionId':job['sessionId']})
     self.assertTrue(tool('cy_get_job',{'jobId':job['jobId']})['artifactsDeleted'])
    finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
