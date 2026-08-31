"""Payload factories — one per resource, client-supplied input fields only."""

import itertools

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def _digits4(seed: int) -> str:
    return f"{seed % 10000:04d}"


def create_customer_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "legal_name": f"Depositor {n}",
        "tin_last4": _digits4(1000 + n),
    }
    payload.update(overrides)
    return payload


def create_account_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_type": "CHECKING",
        "open_channel": "BRANCH",
    }
    payload.update(overrides)
    return payload


def create_funding_source_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "source_type": "EXTERNAL_ACH",
        "routing_last4": _digits4(2000 + n),
    }
    payload.update(overrides)
    return payload


def verification_attempt_payload(micro_deposit_cents: int) -> dict:
    return {"micro_deposit_cents": micro_deposit_cents}


def create_account_link_payload(from_account_id: str, to_account_id: str, **overrides) -> dict:
    payload = {
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "link_type": "SHARED_DEVICE",
        "confidence_bps": 9000,
    }
    payload.update(overrides)
    return payload


def create_deposit_item_payload(**overrides) -> dict:
    payload = {
        "item_type": "CHECK",
        "amount_cents": 30000,
    }
    payload.update(overrides)
    return payload


def settle_payload(outcome: str, return_reason: str = None) -> dict:
    payload = {"outcome": outcome}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return payload


def create_override_review_payload(expected_check_hold_version: int, **overrides) -> dict:
    payload = {
        "requested_release_cents": 7500,
        "release_effective_at": "2026-08-01T00:00:00Z",
        "release_window_end_at": "2026-08-02T00:00:00Z",
        "justification": "Established relationship, funds needed today",
        "expected_check_hold_version": expected_check_hold_version,
    }
    payload.update(overrides)
    return payload


def decide_review_payload(decision: str, decision_note: str = None) -> dict:
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def access_review_payload(indicator_codes, reset_posture: bool = None) -> dict:
    payload = {"indicator_codes": list(indicator_codes)}
    if reset_posture is not None:
        payload["reset_posture"] = reset_posture
    return payload


def step_up_response_payload(challenge_answer: str) -> dict:
    return {"challenge_answer": challenge_answer}


def kiting_scan_payload(mode: str, window_start_at: str, window_end_at: str) -> dict:
    return {
        "mode": mode,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }


def create_fraud_case_payload(primary_account_id: str, case_type: str = "MULE") -> dict:
    return {"primary_account_id": primary_account_id, "case_type": case_type}


def disposition_payload(decision: str, disposition_note: str = None) -> dict:
    payload = {"decision": decision}
    if disposition_note is not None:
        payload["disposition_note"] = disposition_note
    return payload


def create_bsa_referral_payload(**overrides) -> dict:
    payload = {
        "narrative": "Rapid pass-through of third-party deposits across counterparties.",
        "suspected_activity_code": "MULE_ACTIVITY",
    }
    payload.update(overrides)
    return payload


def adjudicate_referral_payload(decision: str, return_reason: str = None) -> dict:
    payload = {"decision": decision}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return payload


def create_charge_off_payload(expected_account_version: int, **overrides) -> dict:
    payload = {
        "gross_loss_cents": 120000,
        "collateral_offset_cents": 20000,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def recovery_posting_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def reverse_charge_off_payload(reversal_reason: str = "Drawer paid in full; write-off rescinded") -> dict:
    return {"reversal_reason": reversal_reason}


def create_subpoena_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "issuing_agency": "Federal Bureau of Investigation",
        "docket_number": f"26-FBI-{n:04d}",
        "response_due_at": "2026-09-30T00:00:00Z",
        "preservation_start_at": "2026-08-01T00:00:00Z",
        "preservation_end_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def respond_subpoena_payload(disposition: str, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
