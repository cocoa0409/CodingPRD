"""Payload factories — one per entity, input fields only."""

from . import constants as C


def create_license_payload(**overrides) -> dict:
    payload = {
        "grantor_name": "Major League Baseball Players Association",
        "exclusivity_scope": "EXCLUSIVE",
        "term_starts_on": C.LICENSE_ACTIVE_START,
        "term_ends_on": C.LICENSE_ACTIVE_END,
        "approval_window_days": C.DEFAULT_APPROVAL_WINDOW_DAYS,
    }
    payload.update(overrides)
    return payload


def create_product_line_payload(**overrides) -> dict:
    payload = {
        "license_id": overrides.pop("license_id", None),
        "line_name": "2026 Flagship Baseball",
        "line_kind": "BASE",
        "packs_per_box": C.DEFAULT_BOX_CONFIG["packs_per_box"],
        "cards_per_pack": C.DEFAULT_BOX_CONFIG["cards_per_pack"],
        "boxes_per_case": C.DEFAULT_BOX_CONFIG["boxes_per_case"],
        "cases_printed": C.DEFAULT_CASES_PRINTED,
        "run_planned_on": C.DEFAULT_RUN_PLANNED_ON,
    }
    payload.update(overrides)
    return payload


def create_card_set_payload(**overrides) -> dict:
    payload = {
        "product_line_id": overrides.pop("product_line_id", None),
        "set_name": "Flagship Base",
        "set_tier": "BASE",
        "announced": True,
        "serial_numbered": False,
        "autograph_planned_count": 0,
        "print_run_quantity": 500,
    }
    payload.update(overrides)
    return payload


def create_pack_configuration_payload(**overrides) -> dict:
    payload = {
        "card_set_id": overrides.pop("card_set_id", None),
        "config_serial": 1,
        "base_packs": 10,
        "insert_packs": 0,
        "premium_packs": 0,
    }
    payload.update(overrides)
    return payload


def create_signing_session_payload(**overrides) -> dict:
    payload = {
        "signer_name": C.DEFAULT_SIGNER_NAME,
        "signer_kind": "PLAYER_ASSOCIATION",
        "license_id": overrides.pop("license_id", None),
        "scheduled_on": "2026-10-05T00:00:00Z",
        "allocation_lines": overrides.pop("allocation_lines", []),
    }
    payload.update(overrides)
    return payload


def create_artwork_approval_payload(**overrides) -> dict:
    payload = {
        "artwork_code": "ART-BASE-001",
        "approver_id": overrides.pop("approver_id", None),
        "submitted_on": "2026-08-25T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_print_run_decision_payload(**overrides) -> dict:
    payload = {
        "card_set_id": overrides.pop("card_set_id", None),
        "authority": "BRAND_DIRECTIVE",
        "proposed_against_line_version": overrides.pop(
            "proposed_against_line_version", None
        ),
        "demand_multiplier": 1.0,
        "declared_quantity": 12000,
        "announced": True,
        "proposed_on": "2026-09-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_redemption_payload(**overrides) -> dict:
    payload = {
        "redemption_code": "RDM-0001",
        "signer_name": C.DEFAULT_SIGNER_NAME,
        "estimated_value_cents": 400000,
        "opened_on": C.CLOCK_START,
    }
    payload.update(overrides)
    return payload


def create_notification_payload(**overrides) -> dict:
    payload = {
        "notice_code": "SUBST-90",
        "opened_on": C.CLOCK_START,
    }
    payload.update(overrides)
    return payload


def create_allocation_payload(**overrides) -> dict:
    payload = {
        "product_line_id": overrides.pop("product_line_id", None),
        "channel": "HOBBY",
        "quantity_allocated": 10,
        "effective_price_cents": 72000,
    }
    payload.update(overrides)
    return payload


def create_quality_claim_payload(**overrides) -> dict:
    payload = {
        "claim_type": "MISPRINT",
        "severity": "MINOR",
        "affected_quantity": 10,
        "filed_on": C.CLOCK_START,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(**overrides) -> dict:
    payload = {
        "complaint_label": "Replacement policy absent",
        "breach_reason": "NO_REPLACEMENT_POLICY",
        "claim_quantity": 250,
    }
    payload.update(overrides)
    return payload


def allocation_line(card_set_id, player_id="kgj", quantity_delivered=100) -> dict:
    return {
        "card_set_id": card_set_id,
        "player_id": player_id,
        "quantity_delivered": quantity_delivered,
    }