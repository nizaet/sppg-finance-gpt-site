# SPPG Plugin Skill Map from GPTS Schema v0.18.6

The current GPTS schema exposes technical operations. The plugin should not mirror those one-for-one as skills.
Skills are user workflows; MCP tools remain the technical capability layer.

## 1. Control Tower & Operational Audit
**Purpose:** answer "apa yang perlu saya urus hari ini?" and investigate anomalies.
Uses reads:
- DASHBOARD
- PO_CALENDAR
- PO_REMINDERS
- RECEIVING_VARIANCE
- VENDOR_PAYMENTS
- AUDIT_LOG
- pending review queue

May later use writes:
- REVIEW_EVENT

## 2. Purchase Order
**Purpose:** build, review, edit, finalize, revise and send PO using the same application engine.
Uses reads:
- PLANNING_SNAPSHOTS
- PURCHASE_ORDERS
- PO_CALENDAR
- PO_REMINDERS
- VENDORS
- warehouse stock / PO projection
- final PO WhatsApp message

Uses writes:
- CREATE_PURCHASE_ORDER
- EDIT_DRAFT_PURCHASE_ORDER
- REVISE_PURCHASE_ORDER
- CANCEL_PURCHASE_ORDER
- FINALIZE_PURCHASE_ORDER
- MARK_PURCHASE_ORDER_SENT
- SET_VENDOR_WHATSAPP
- SET_VENDOR_LEAD_TIME

## 3. Receiving / Barang Datang
**Purpose:** parse a forwarded goods-arrival message, match PO, show partial/reject/over-receipt, then record after approval.
Uses reads:
- PURCHASE_ORDERS
- GOODS_RECEIPTS
- RECEIVING_VARIANCE

Uses writes:
- RECORD_GOODS_RECEIPT_MANUAL

Existing read-only MCP:
- receiving_preview

## 4. Stock Opname & Warehouse
**Purpose:** normalize messy SO text, map names/units, confirm ambiguous lines, save one physical baseline, and explain available-for-PO stock.
Uses reads:
- STOCK_OPNAMES
- INVENTORY_ITEM_MASTER
- inventory balances/projection
- ACTUAL_USAGE

Uses writes:
- VOID_STOCK_OPNAME
- UPSERT_INVENTORY_ITEM_MASTER
- RECORD_ACTUAL_USAGE

Existing read-only MCP:
- stock_opname_preview

## 5. Vendor Invoice & Payable
**Purpose:** parse Holil/Wikian invoice text, reconcile with PO + receipt, calculate reject deduction and net payable, then save after approval.
Uses:
- vendor invoice parser
- PO/receipt lookup
- payable preview/list
- payment status

Later writes:
- payable commit
- vendor payment confirmation

Existing read-only MCP:
- vendor_invoice_parse_preview
- vendor_payable_preview
- vendor_payables_list

## 6. Accountant / Finance
**Purpose:** search, create and correct verified MAJA/CEMPLANG finance transactions and maintain sync status.
Uses reads:
- ACCOUNTANT_FLOW
- accountant bridge status
- finance transaction search

Uses writes:
- create finance transactions
- update finance transaction
- CREATE_ACCOUNTANT_SUBMISSION
- MARK_ACCOUNTANT_SUBMISSION_SENT
- CREATE_ACCOUNTANT_INVOICE

Admin/migration-only capability:
- Firestore history backfill

## 7. Calculator & Planning Data
**Purpose:** preview/import calculator masters and daily plans, and sync finalized planning into operations.
Uses reads:
- PLANNING_SNAPSHOTS
- calculator daily-plan preview

Uses writes:
- CREATE_PLANNING_SNAPSHOT
- SYNC_CALCULATOR_PLANNING
- calculator master/data import

## 8. BGN Payment Workflow
**Purpose:** carry BGN payment workflow from maker through approval, receipt and settlement.
Uses reads:
- BGN_FLOW

Uses writes:
- CREATE_BGN_MAKER
- CREATE_BGN_APPROVAL
- CREATE_BGN_RECEIPT
- CREATE_SETTLEMENT

## 9. Review, History & Recovery
**Purpose:** operator review queue, historical import/backfill, and audit/recovery workflows.
Uses:
- historical operations import
- staged WhatsApp activity review
- pending review list
- Firestore backfill preview/import
- AUDIT_LOG
- REVIEW_EVENT

## Not a separate skill
These remain MCP tools/supporting capabilities, not user-facing skills:
- bridge health/status
- raw item-master search
- raw vendor list lookup
- generic operational read gateway
- generic operational execute gateway

## Rollout priority
1. Receiving / Barang Datang
2. Stock Opname & Warehouse
3. Vendor Invoice & Payable
4. Purchase Order
5. Control Tower & Operational Audit
6. Accountant / Finance
7. Calculator & Planning Data
8. BGN Payment Workflow
9. Review, History & Recovery

LPDH is not part of the legacy GPTS schema and should be added later as a separate new plugin skill, not treated as migration parity.
