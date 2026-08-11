# Domain Invariant Test Matrix v0.5

These scenarios must be preserved by future implementation/tests.

1. Text: `nanti saya transfer`
   - candidate: PAYMENT_INTENT
   - expected domain payment status: no PAID row created

2. Text: `sudah ditransfer` without amount/evidence match
   - candidate: PAYMENT_EVIDENCE_CANDIDATE
   - expected: reconciliation required; no automatic finalization

3. PO revision changes wortel from 80 kg to 75 kg
   - expected: revision 2 created; revision 1 remains queryable with 80 kg

4. Ordered 100 kg, received 96 kg, rejected 4 kg
   - expected: ordered/received/rejected/accepted remain distinct

5. Koperasi sends 20 L oil to Maja
   - expected: inventory movement KOPERASI -> MAJA
   - expected expense created at transfer: false

6. Cash purchase eggs via Mungki
   - expected: internal reimbursement pending may be created
   - expected BGN reimbursement record created merely from cash purchase: false

7. Approval list sent to Malik
   - expected: Cemplang approval PENDING
   - expected APPROVED: false until confirmation resolving to maker/reference

8. Funds move Yayasan/Koperasi -> BCA Operational
   - expected: settlement entry
   - expected additional expense: false

9. Vendor invoice price differs from claim price
   - expected: vendor_cost_price and claim_price both retained independently

10. Same WhatsApp webhook/message delivered twice
    - expected: same event_key/idempotency key
    - expected duplicate candidate/domain action: false
