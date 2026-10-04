"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_office_payload(**overrides) -> dict:
    defaults = {"name": f"Office {_n()}", "region_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_preparer_payload(office_id: str, **overrides) -> dict:
    defaults = {
        "office_id": office_id,
        "full_name": f"Preparer {_n()}",
        "tier": "ASSOCIATE",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    n = _n()
    defaults = {"full_name": f"Client {n}", "email": f"client{n}@example.com"}
    defaults.update(overrides)
    return defaults


def create_return_payload(client_id: str, office_id: str, preparer_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "office_id": office_id,
        "preparer_id": preparer_id,
        "tax_year": 2025,
        "components": ["1040_SIMPLE"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(return_id: str, **overrides) -> dict:
    defaults = {"return_id": return_id, "tier": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_notice_payload(return_id: str, **overrides) -> dict:
    defaults = {
        "return_id": return_id,
        "authority_type": "STATE",
        "notice_reference": f"N-{_n()}",
        "tax_delta_cents": 1000,
        "penalty_cents": 0,
        "issued_at": "2026-09-10T00:00:00Z",
        "due_at": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(return_id: str, notice_id: str, expected_return_version: int, **overrides) -> dict:
    defaults = {
        "return_id": return_id,
        "notice_id": notice_id,
        "expected_return_version": expected_return_version,
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Agent {n}",
        "license_number": f"EA-{n:06d}",
        "max_parallel": 3,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(agent_id: str, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "window_start": "2026-09-12T00:00:00Z",
        "window_end": "2026-12-12T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_poa_payload(agent_id: str, **overrides) -> dict:
    defaults = {"agent_id": agent_id, "expires_at": "2027-06-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_remediation_payload(preparer_id: str, **overrides) -> dict:
    defaults = {"preparer_id": preparer_id, "due_at": "2027-01-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_escrow_payload(office_id: str, **overrides) -> dict:
    defaults = {"office_id": office_id, "funded_cents": 100_000_000}
    defaults.update(overrides)
    return defaults


def create_quality_close_payload(**overrides) -> dict:
    defaults = {
        "period_month": "2026-09",
        "returns_examined": 100,
        "returns_with_defects": 0,
    }
    defaults.update(overrides)
    return defaults
