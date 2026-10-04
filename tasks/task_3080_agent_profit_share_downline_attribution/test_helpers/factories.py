"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "CENTER_NAME": "MC Alpha",
    "REGION_CODE": "SW-TX",
    "JOIN_DATE": "2026-09-01T00:00:00Z",
    "GROSS_COMMISSION": 1000.00,
    "OCCURRED_ON": "2026-09-10T00:00:00Z",
    "PERIOD_MONTH": "2026-09",
    "EFFECTIVE_DATE": "2026-10-01T00:00:00Z",
}


def _suffix() -> str:
    return str(next(_counter))


def create_market_center_payload(**overrides) -> dict:
    defaults = {
        "name": f"{DEFAULTS['CENTER_NAME']} {_suffix()}",
        "region_code": DEFAULTS["REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    n = _suffix()
    defaults = {
        "full_name": f"Agent {n}",
        "email": f"agent{n}@example.com",
        "join_date": DEFAULTS["JOIN_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(document_type, **overrides) -> dict:
    defaults = {
        "document_type": document_type,
        "document_ref": f"doc-{_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(sponsored_agent_id, evidence_document_id, **overrides) -> dict:
    defaults = {
        "sponsored_agent_id": sponsored_agent_id,
        "evidence_document_id": evidence_document_id,
        "reason": "The attestation names me as sponsor",
    }
    defaults.update(overrides)
    return defaults


def create_commission_event_payload(agent_id, expected_agent_version, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "gross_commission": DEFAULTS["GROSS_COMMISSION"],
        "occurred_on": DEFAULTS["OCCURRED_ON"],
        "external_ref": f"ref-{_suffix()}",
        "expected_agent_version": expected_agent_version,
    }
    defaults.update(overrides)
    return defaults


def create_period_payload(**overrides) -> dict:
    defaults = {"period_month": DEFAULTS["PERIOD_MONTH"]}
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(entry_type, amount, **overrides) -> dict:
    defaults = {"entry_type": entry_type, "amount": amount}
    defaults.update(overrides)
    return defaults


def create_resolution_payload(**overrides) -> dict:
    defaults = {"resolution_type": "FINAL_CLOSE_RATIFICATION"}
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(to_market_center_id, expected_agent_version,
                                    **overrides) -> dict:
    defaults = {
        "to_market_center_id": to_market_center_id,
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expected_agent_version": expected_agent_version,
    }
    defaults.update(overrides)
    return defaults


def create_departure_payload(**overrides) -> dict:
    defaults = {"departure_date": "2026-09-10T00:00:00Z"}
    defaults.update(overrides)
    return defaults
