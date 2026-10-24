import unittest
from unittest.mock import AsyncMock,patch
from plugin_mcp.whatsapp_queue import matches_report,saved_result,pending_whatsapp_reports,complete_whatsapp_reports

REPORT={'id':'one','site':'MAJA','reportType':'STOCK_OPNAME','text':'#SO MAJA\nGula 5 kg','contentHash':'abc'}
APPROVAL={'id':'test','site':'MAJA','action':'RECORD_STOCK_OPNAME','status':'APPLIED','proposed_payload':{'text':REPORT['text']},'result_data':{'stockOpnameId':25,'committed':True}}
class QueueTests(unittest.IsolatedAsyncioTestCase):
 def test_evidence_and_saved_result(self):
  self.assertTrue(matches_report(REPORT,APPROVAL));self.assertTrue(saved_result(APPROVAL))
  for change in [{'site':'CEMPLANG'},{'action':'RECORD_GOODS_RECEIPT'},{'proposed_payload':{'text':'other'}}]:
   self.assertFalse(matches_report(REPORT,{**APPROVAL,**change}))
  self.assertFalse(matches_report({**REPORT,'revisions':[{'text':'Gula 9 kg'}]},APPROVAL))
  for change in [{'status':'PENDING'},{'result_data':{}},{'result_data':{'stockOpnameId':25,'committed':False}}]:self.assertFalse(saved_result({**APPROVAL,**change}))
 async def test_read_excludes_saved_but_retains_pending(self):
  with patch('plugin_mcp.whatsapp_queue.bridge_request',new=AsyncMock(return_value={'items':[REPORT]})) as http,patch('plugin_mcp.whatsapp_queue.approvals_for',return_value=[APPROVAL]):
   self.assertEqual((await pending_whatsapp_reports())['items'],[]);self.assertEqual(http.await_count,1)
  with patch('plugin_mcp.whatsapp_queue.bridge_request',new=AsyncMock(return_value={'items':[REPORT]})),patch('plugin_mcp.whatsapp_queue.approvals_for',return_value=[{**APPROVAL,'status':'PENDING'}]):
   rows=(await pending_whatsapp_reports())['items'];self.assertEqual(rows[0]['originalText'],REPORT['text']);self.assertEqual(rows[0]['existingApproval']['status'],'PENDING')
 async def test_ack_only_verified_applied_report(self):
  for approval,count in [(APPROVAL,2),({**APPROVAL,'status':'PENDING'},1),({**APPROVAL,'site':'CEMPLANG'},1)]:
   with patch('plugin_mcp.whatsapp_queue.bridge_request',new=AsyncMock(return_value={'items':[REPORT]})) as http,patch('plugin_mcp.whatsapp_queue.approvals_for',return_value=[approval]):
    result=await complete_whatsapp_reports('approval');self.assertEqual(http.await_count,count);self.assertEqual(bool(result),count==2)
