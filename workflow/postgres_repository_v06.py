from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Protocol

from workflow.workflow_service_v06 import CandidateEvent, DomainCommand


class DBConnection(Protocol):
    def execute(self, query: str, params: Mapping[str, Any] | None = None): ...
    def fetchone(self): ...


INSERT_CANDIDATE_SQL = """
INSERT INTO candidate_events (
    idempotency_key,
    source_type,
    source_id,
    source_message_id,
    event_type,
    site,
    actor,
    vendor,
    confidence,
    requires_confirmation,
    payload,
    status
) VALUES (
    %(idempotency_key)s,
    %(source_type)s,
    %(source_id)s,
    %(source_message_id)s,
    %(event_type)s,
    %(site)s,
    %(actor)s,
    %(vendor)s,
    %(confidence)s,
    %(requires_confirmation)s,
    %(payload)s,
    'PENDING'
)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING id;
"""


INSERT_ACTION_SQL = """
INSERT INTO workflow_actions (
    candidate_event_id,
    action_type,
    aggregate_type,
    payload,
    status
) VALUES (
    %(candidate_event_id)s,
    %(action_type)s,
    %(aggregate_type)s,
    %(payload)s,
    'READY'
)
RETURNING id;
"""


class PostgresWorkflowRepository:
    def __init__(self, connection: DBConnection):
        self.connection = connection

    def store_candidate(self, event: CandidateEvent) -> Any | None:
        params = asdict(event)
        params["idempotency_key"] = event.idempotency_key
        self.connection.execute(INSERT_CANDIDATE_SQL, params)
        row = self.connection.fetchone()
        if not row:
            return None
        return row[0] if isinstance(row, (tuple, list)) else row.get("id")

    def queue_domain_command(self, candidate_event_id: Any, command: DomainCommand) -> Any:
        params = {
            "candidate_event_id": candidate_event_id,
            "action_type": command.command_type,
            "aggregate_type": command.aggregate_type,
            "payload": dict(command.payload),
        }
        self.connection.execute(INSERT_ACTION_SQL, params)
        row = self.connection.fetchone()
        if not row:
            raise RuntimeError("workflow_action_not_created")
        return row[0] if isinstance(row, (tuple, list)) else row.get("id")
