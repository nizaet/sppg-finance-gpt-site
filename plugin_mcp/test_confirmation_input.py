import unittest
from plugin_mcp.confirmation_input import confirmation_choice

ID='8301ba70-ead6-4f69-9dd6-e388a1aeb609'
EXACT=f'Konfirmasi penerimaan Holil CEMPLANG 18 Oktober 2026 sesuai preview approvalId {ID}, termasuk alokasi otomatis ke PO #433 dan #439.'

class ConfirmationInputTests(unittest.TestCase):
    def test_actual_detailed_operator_approval_and_short_choices(self):
        self.assertEqual(confirmation_choice(ID,EXACT),'CONFIRM')
        for text in ['Konfirmasi','commit true','masukan','Simpan']:
            self.assertEqual(confirmation_choice(ID,text),'CONFIRM')
        self.assertEqual(confirmation_choice(ID,'Batalkan'),'CANCEL')

    def test_negation_conditional_questions_and_other_proposals_do_not_execute(self):
        for text in [EXACT.replace(ID,'00000000-0000-0000-0000-000000000000'),EXACT.replace(ID,''),'Jangan '+EXACT,EXACT+' Belum sesuai',EXACT+'?',EXACT+' jika cocok',EXACT+' setelah edit',EXACT+' 00000000-0000-0000-0000-000000000000','Barang datang 344.68 kg']:
            with self.subTest(text=text),self.assertRaises(ValueError): confirmation_choice(ID,text)
