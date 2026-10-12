"""No live financial mutation: contracts for dual evidence destinations."""
import hashlib
import unittest
from unittest.mock import patch, Mock
import test_generated_document_api
from backend import bgn_evidence
from backend.generated_document_logic import document_rows, merge_final_documents
from backend.lpdh_approval import attach_approval


class EvidenceTests(unittest.TestCase):
    def document(self, **extra):
        return {'id':7,'status':'FINAL','site':'MAJA','serviceDate':'2026-10-12',
            'documentType':'OPERASIONAL','documentNumber':'INV-7','header':{'evidenceLink':'https://internal/manual'},
            'driveUri':'https://internal/pdf','bgnRequired':True,'bgnDriveUri':'https://drive.google.com/file/d/bgn/view',
            'items':[{'itemName':'Gas','category':'Gas','quantity':1,'unit':'tabung','unitPrice':10,'lineTotal':10,'metadata':{}}],**extra}

    def test_bgn_overrides_old_internal_evidence_without_changing_amount(self):
        doc=self.document()
        _, rows=document_rows(doc)
        old={'operations':[{**rows[0],'evidenceLink':'https://internal/old','paymentReference':'transfer-7'}]}
        result=merge_final_documents(old,[doc])
        self.assertEqual(result['operations'][0]['evidenceLink'],doc['bgnDriveUri'])
        self.assertEqual(result['operations'][0]['paymentReference'],'transfer-7')
        self.assertEqual(result['operations'][0]['price'],10)
        self.assertEqual(doc['driveUri'],'https://internal/pdf')

    def test_failed_bgn_never_falls_back_to_internal(self):
        doc=self.document(bgnDriveUri=None)
        self.assertEqual(document_rows(doc)[1][0]['evidenceLink'],'')
        self.assertEqual(merge_final_documents({},[doc])['operations'][0]['evidenceLink'],'')

    def test_historical_unmanaged_document_keeps_legacy_link(self):
        doc=self.document(bgnRequired=False)
        self.assertEqual(document_rows(doc)[1][0]['evidenceLink'],'https://internal/manual')

    def test_mitra_uses_bgn_and_approval_preserves_internal_separately(self):
        doc=self.document(documentType='INSENTIF_MITRA')
        self.assertEqual(merge_final_documents({},[doc])['incentive']['evidenceLink'],doc['bgnDriveUri'])
        result=attach_approval({}, {'driveUri':doc['bgnDriveUri'],'internalDriveUri':doc['driveUri']},'hash','MAJA','now')
        self.assertEqual(result['_approval']['pdfLink'],doc['bgnDriveUri'])
        self.assertEqual(result['_approval']['internalPdfLink'],doc['driveUri'])

    def test_verified_upload_checks_parent_size_checksum_and_site(self):
        content=b'pdf-test';cur=Mock()
        record={'file_id':'file','folder_id':'day','drive_uri':'https://drive.google.com/file/d/file/view'}
        saved={'email':bgn_evidence.drive.SITES['MAJA'][0],'folder_id':bgn_evidence.drive.SITES['MAJA'][1]}
        meta={'mimeType':'application/pdf','parents':['day'],'size':str(len(content)), 'md5Checksum':hashlib.md5(content).hexdigest()}
        api=Mock();api.files.return_value.get.return_value.execute.return_value=meta
        for field, value in [(None,None),('parents',['wrong']),('size','1'),('md5Checksum','wrong'),('trashed',True)]:
            cur.fetchone.side_effect=[record,saved]
            api.files.return_value.get.return_value.execute.return_value={**meta,**({field:value} if field else {})}
            with patch.object(bgn_evidence.drive,'upload') as upload, patch.object(bgn_evidence.drive,'service',return_value=api):
                args=(cur,'MAJA','2026-10-12','immutable-snapshot','file.pdf',content,'application/pdf')
                if field:
                    with self.assertRaises(ValueError):bgn_evidence.upload_verified(*args)
                else:self.assertEqual(bgn_evidence.upload_verified(*args),record['drive_uri'])
                self.assertEqual(upload.call_args.args[1:4],('MAJA','2026-10-12','immutable-snapshot'))


if __name__=='__main__':unittest.main()
