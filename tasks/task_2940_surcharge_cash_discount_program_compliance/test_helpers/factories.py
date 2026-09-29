"""Payload factories — one per entity, input fields only."""
from .constants import (
    CONTENT_HASH_A,
    CLOCK_AUG_01,
    CLOCK_DEC_31,
)

# Statutory profiles used across the suite. Each entry is a complete
# jurisdiction registration body.
JURISDICTION_PROFILES = {
    # Surcharging permitted with a statutory ceiling well above the network
    # ceiling, no disclosure mandates at all, permissive attorney general.
    "AZ": {
        "state_code": "AZ",
        "surcharge_permitted": True,
        "surcharge_cap_pct": 4.0,
        "cash_discount_permitted": True,
        "price_posting_required": False,
        "disclosure_signage_required": False,
        "receipt_line_item_required": False,
        "ag_enforcement_posture": "PERMISSIVE",
    },
    # Every disclosure mandate switched on, monitored attorney general.
    "NY": {
        "state_code": "NY",
        "surcharge_permitted": True,
        "surcharge_cap_pct": 4.0,
        "cash_discount_permitted": True,
        "price_posting_required": True,
        "disclosure_signage_required": True,
        "receipt_line_item_required": True,
        "ag_enforcement_posture": "MONITORED",
    },
    # A statutory ceiling below the network ceiling, so the state cap binds.
    "TX": {
        "state_code": "TX",
        "surcharge_permitted": True,
        "surcharge_cap_pct": 2.0,
        "cash_discount_permitted": True,
        "price_posting_required": False,
        "disclosure_signage_required": False,
        "receipt_line_item_required": False,
        "ag_enforcement_posture": "PERMISSIVE",
    },
    # Surcharging prohibited outright, cash discount permitted, restrictive
    # attorney general.
    "CT": {
        "state_code": "CT",
        "surcharge_permitted": False,
        "surcharge_cap_pct": None,
        "cash_discount_permitted": True,
        "price_posting_required": True,
        "disclosure_signage_required": True,
        "receipt_line_item_required": False,
        "ag_enforcement_posture": "RESTRICTIVE",
    },
    # Cash-discount structures prohibited, surcharging permitted at 3.5.
    "MA": {
        "state_code": "MA",
        "surcharge_permitted": True,
        "surcharge_cap_pct": 3.5,
        "cash_discount_permitted": False,
        "price_posting_required": False,
        "disclosure_signage_required": False,
        "receipt_line_item_required": False,
        "ag_enforcement_posture": "PERMISSIVE",
    },
}


def jurisdiction_payload(profile="AZ", **overrides) -> dict:
    """Body for registering a jurisdiction, seeded from a named statutory profile."""
    payload = dict(JURISDICTION_PROFILES[profile])
    payload.update(overrides)
    return payload


def law_change_payload(surcharge_permitted: bool, **overrides) -> dict:
    """Body for a statutory law change; surcharge_permitted is always restated."""
    payload = {"surcharge_permitted": surcharge_permitted}
    payload.update(overrides)
    return payload


def merchant_payload(jurisdiction_id, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "legal_name": "Sonoran Supply Co",
        "mcc": "5734",
    }
    payload.update(overrides)
    return payload


# Documented-cost profiles. Against the default average ticket of 5000 cents
# docA yields documented_cost_pct 2.1900 and docB yields 3.0500.
COST_DOC_PROFILES = {
    "docA": {"base_mdr_pct": 1.85, "assessment_pct": 0.14, "per_item_fee_cents": 10},
    "docB": {"base_mdr_pct": 2.55, "assessment_pct": 0.20, "per_item_fee_cents": 15},
}


def cost_documentation_payload(expected_merchant_version, profile="docA", **overrides) -> dict:
    payload = dict(COST_DOC_PROFILES[profile])
    payload["evidence_uri"] = "s3://acq/statements/2026-07.pdf"
    payload["expected_merchant_version"] = expected_merchant_version
    payload.update(overrides)
    return payload


def program_payload(
    merchant_id,
    jurisdiction_id,
    cost_documentation_id,
    program_type="SURCHARGE",
    consistency_scope="BRAND_LEVEL",
    **overrides,
) -> dict:
    payload = {
        "merchant_id": merchant_id,
        "jurisdiction_id": jurisdiction_id,
        "cost_documentation_id": cost_documentation_id,
        "program_type": program_type,
        "consistency_scope": consistency_scope,
    }
    payload.update(overrides)
    return payload


def rate_rule_payload(
    expected_program_version,
    brand="VISA",
    product_tier="ALL",
    rate_pct=2.19,
    effective_from=CLOCK_AUG_01,
    effective_to=CLOCK_DEC_31,
    **overrides,
) -> dict:
    payload = {
        "brand": brand,
        "product_tier": product_tier,
        "rate_pct": rate_pct,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def network_registration_payload(network="VISA", registration_ref="VS-2940-0001", **overrides) -> dict:
    payload = {"network": network, "registration_ref": registration_ref}
    payload.update(overrides)
    return payload


def registration_decision_payload(decision="ACKNOWLEDGE", **overrides) -> dict:
    payload = {"decision": decision, "decision_note": "accepted"}
    payload.update(overrides)
    return payload


def disclosure_artifact_payload(artifact_type="ENTRY_SIGNAGE", content_hash=CONTENT_HASH_A, **overrides) -> dict:
    payload = {"artifact_type": artifact_type, "content_hash": content_hash}
    payload.update(overrides)
    return payload


def attestation_payload(effective_from, expires_at, **overrides) -> dict:
    payload = {"effective_from": effective_from, "expires_at": expires_at}
    payload.update(overrides)
    return payload


def terminal_payload(serial_number="TRM-0001", **overrides) -> dict:
    payload = {"serial_number": serial_number}
    payload.update(overrides)
    return payload


def terminal_configuration_payload(
    program_id, debit_exclusion_enabled=True, bin_table_version="BIN-2026.08", **overrides
) -> dict:
    payload = {
        "program_id": program_id,
        "debit_exclusion_enabled": debit_exclusion_enabled,
        "bin_table_version": bin_table_version,
    }
    payload.update(overrides)
    return payload


def terminal_action_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def program_status_action_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def transaction_payload(
    terminal_id,
    program_id,
    card_brand="VISA",
    card_funding="CREDIT",
    product_tier="CONSUMER_CREDIT",
    base_amount_cents=10000,
    requested_surcharge_cents=219,
    receipt_line_present=True,
    **overrides,
) -> dict:
    payload = {
        "terminal_id": terminal_id,
        "program_id": program_id,
        "card_brand": card_brand,
        "card_funding": card_funding,
        "product_tier": product_tier,
        "base_amount_cents": base_amount_cents,
        "requested_surcharge_cents": requested_surcharge_cents,
        "receipt_line_present": receipt_line_present,
    }
    payload.update(overrides)
    return payload


def complaint_case_payload(
    program_id,
    source="NETWORK",
    allegation_type="UNDISCLOSED_SURCHARGE",
    narrative="The merchant collected a surcharge that was never disclosed at the door.",
    **overrides,
) -> dict:
    payload = {
        "program_id": program_id,
        "source": source,
        "allegation_type": allegation_type,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def investigation_action_payload(action, **overrides) -> dict:
    payload = {"action": action, "note": "reviewed the filed evidence"}
    payload.update(overrides)
    return payload


def remediation_action_payload(action, **overrides) -> dict:
    payload = {"action": action}
    if action == "SUBMIT_PLAN":
        payload["plan_summary"] = "Refund the disputed surcharge and re-train the front counter."
    payload.update(overrides)
    return payload


def refund_payload(transaction_id, refund_amount_cents, **overrides) -> dict:
    payload = {
        "transaction_id": transaction_id,
        "refund_amount_cents": refund_amount_cents,
    }
    payload.update(overrides)
    return payload


def void_payload(reason="cardholder was made whole by the acquirer instead", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
