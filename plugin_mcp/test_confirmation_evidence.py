import unittest
from datetime import datetime, timedelta, timezone
from plugin_mcp.confirmation_evidence import confirmation_evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.row = {'status': 'PENDING', 'expires_at': self.now + timedelta(minutes=5)}

    def test_pending_does_not_invent_auth_or_platform_failure(self):
        result = confirmation_evidence(self.row, self.now)
        self.assertIsNone(result['confirmationRecorded'])
        self.assertIsNone(result['platformRejectionReason'])
        self.assertFalse(result['executionClaimed'])
        self.assertTrue(result['canConfirm'])

    def test_expired_proposal_cannot_be_presented_as_confirmable(self):
        self.row['expires_at'] = self.now - timedelta(seconds=1)
        result = confirmation_evidence(self.row, self.now)
        self.assertEqual(result['effectiveStatus'], 'EXPIRED')
        self.assertFalse(result['canConfirm'])
        self.assertEqual(self.row['status'], 'PENDING')

    def test_recorded_validation_failure_is_distinct_from_no_delivery(self):
        self.row.update(confirmation_received_at=self.now,
                        last_confirmation_outcome={'status': 'REVALIDATION_FAILED'})
        result = confirmation_evidence(self.row, self.now)
        self.assertTrue(result['confirmationRecorded'])
        self.assertEqual(result['lastConfirmationOutcome']['status'], 'REVALIDATION_FAILED')
        self.assertFalse(result['executionClaimed'])

    def test_old_success_without_new_audit_fields_is_still_success(self):
        self.row['status'] = 'APPLIED'
        result = confirmation_evidence(self.row, self.now)
        self.assertEqual(result['effectiveStatus'], 'APPLIED')
        self.assertTrue(result['executionClaimed'])
        self.assertFalse(result['canConfirm'])
        self.assertIn('never submit', result['diagnostic'])

    def test_cancel_timestamp_is_not_an_execution_claim(self):
        self.row.update(status='DECLINED', confirmed_at=self.now)
        self.assertFalse(confirmation_evidence(self.row, self.now)['executionClaimed'])


if __name__ == '__main__':
    unittest.main()
