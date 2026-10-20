"""Read-only confirmation diagnostics; absence of evidence is not a rejection."""
from datetime import datetime, timezone


def confirmation_evidence(row, now=None):
    now = now or datetime.now(timezone.utc)
    status = row['status']
    expired = status in {'PENDING', 'DRAFT'} and row['expires_at'] <= now
    received = row.get('confirmation_received_at')
    outcome = row.get('last_confirmation_outcome')
    return {
        'effectiveStatus': 'EXPIRED' if expired else status,
        'confirmationRecorded': True if received else None,
        'confirmationReceivedAt': received.isoformat() if received else None,
        'lastConfirmationOutcome': outcome,
        'decisionAt': row.get('confirmed_at').isoformat() if row.get('confirmed_at') else None,
        'executionClaimed': status in {'EXECUTING', 'APPLIED', 'FAILED_NEEDS_REVIEW'},
        'executionFinishedAt': row.get('executed_at').isoformat() if row.get('executed_at') else None,
        'canConfirm': status == 'PENDING' and not expired,
        'platformRejectionReason': None,
        'diagnostic': (
            'Operation is APPLIED; use its stored result, never submit it again.' if status == 'APPLIED' else
            'Confirmation reached the server; inspect the recorded outcome.' if received else
            'No confirmation arrival is recorded. This does not identify an OAuth, transport or platform approval failure; do not invent a reason or retry a write automatically.'
        ),
    }
