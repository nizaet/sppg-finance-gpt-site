import unittest
from plugin_mcp.receipt_fastpath import normalize_receipt_input, compact_knowledge

REPORT='''barang datang ke cemplang Rekap Kedatangan Ayam Filet
📅 Sabtu, 17 Oktober 2026
47,06 kg
60,38 kg
61,04 kg
60,94 kg
61,80 kg
57,34 kg
58,96 kg
Jumlah kedatangan: 7 data
Total berat: 407,52 kg'''

class ReceiptInputTests(unittest.TestCase):
    def test_original_report_becomes_one_exact_weight_with_source_preserved(self):
        original={'text':REPORT}
        out=normalize_receipt_input(original)
        self.assertEqual(out['text'],'Ayam Fillet - 407.52 kg')
        self.assertEqual(out['source_raw_text'],REPORT)
        self.assertEqual(out['receipt_input_summary']['weighingCount'],7)
        self.assertEqual(out['receipt_input_summary']['actualQty'],407.52)
        self.assertEqual(out['received_at'],'2026-10-17T00:00:00+07:00')
        self.assertEqual(out['received_time_precision'],'DATE')
        self.assertEqual(original,{'text':REPORT})

    def test_inconsistent_count_total_and_mixed_items_are_not_guessed(self):
        for raw in [REPORT.replace('7 data','8 data'),REPORT.replace('407,52 kg','408 kg'),REPORT+'\nAyam Potong - 20 kg',REPORT.replace('Ayam Filet','Ayam Fillet + Ayam Potong')]:
            with self.subTest(raw=raw),self.assertRaises(ValueError): normalize_receipt_input({'text':raw})

    def test_structured_items_and_date_only_no_long_validation_retry(self):
        out=normalize_receipt_input({'items':[{'item_name':'Wortel','received_qty':'50,68','unit':'kg'}],'received_date':'2026-10-17'})
        self.assertEqual(out['text'],'Wortel - 50.68 kg')
        self.assertEqual(out['received_at'],'2026-10-17T00:00:00+07:00')
        self.assertNotIn('received_date',out)

    def test_named_mixed_report_passes_through_without_merging_or_double_count(self):
        raw='• *Gula Merah* - 5,04 kg\n• *Jeruk Medan* - 186,88 kg\n• *Wortel* - 50,68 kg'
        out=normalize_receipt_input({'text':raw,'received_at':'2026-10-18T02:35:00+07:00'})
        self.assertEqual(out['text'],raw)
        self.assertNotIn('receipt_input_summary',out)
        self.assertNotIn('received_time_precision',out)

    def test_nonfinite_negative_and_missing_quantities_cannot_be_submitted(self):
        for qty in ['NaN','Infinity',-1,None]:
            with self.subTest(qty=qty),self.assertRaises(ValueError):
                normalize_receipt_input({'items':[{'item_name':'Ayam','received_qty':qty,'unit':'kg'}]})

    def test_compact_knowledge_keeps_confirmed_rules_not_unrelated_ledgers(self):
        out=compact_knowledge({'databaseReady':True,'canonicalKnowledge':{'version':'v6','canonicalFacts':{'alias':'muncang=kemiri'},'conversationLearningPolicy':['obsolete']},'liveContext':{'learnedKnowledge':[{'status':'CONFIRMED','statement':'Rule A'},{'status':'CANDIDATE','statement':'Guess'}],'vendorRules':[{'vendor_code':'WIKIAN'}],'openPayables':[{'private':'not needed'}],'conversationMemory':['long raw chats']}})
        self.assertTrue(out['loaded']);self.assertEqual(len(out['confirmedKnowledge']),1)
        self.assertEqual(out['canonicalFacts']['alias'],'muncang=kemiri')
        self.assertNotIn('openPayables',out);self.assertNotIn('conversationLearningPolicy',out)

if __name__=='__main__': unittest.main()
