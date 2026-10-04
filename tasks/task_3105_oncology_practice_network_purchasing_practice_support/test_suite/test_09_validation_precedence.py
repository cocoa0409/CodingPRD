"""Validation precedence where two rules are violated at once."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, create_draft_agreement,
    make_practice_admin_headers, create_affiliation_contract_payload,
    create_pricing_agreement_submit_payload, create_pricing_agreement_payload,
    DEFAULT_CLOCK,
)


def test_pricing_window_overlap_beats_state_precondition(api, network_admin_headers):
    """PRD §2.6: "for a given practice and a given `tier_level`, no two
    agreements may hold intersecting windows while either is in
    `PENDING_APPROVAL` or `ACTIVE`; a submission that would create such an
    intersection is refused with `ERR_PRICING_WINDOW_OVERLAP`, and this is
    checked before the state and affiliation conditions that would otherwise
    guard the submission."
    PRD §2.11: "Where a workflow below names a specific ordering between two
    checks — as the departure cascade does, checking open management agreements
    before the active-contract condition, or as the pricing-window overlap does,
    running ahead of the state and affiliation checks — that named ordering
    governs."

    Design: Difficulty/priority_pair_validation_conflict/pricing_window_overlap_beats_state_precondition
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=180)
    create_activated_contract(practice["id"])
    practice_headers = make_practice_admin_headers(practice["id"])

    first = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.05,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z")
    validate_success(
        api.submit_pricing_agreement(
            first["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)
    validate_success(api.approve_pricing_agreement(first["id"], network_admin_headers), 200)

    second = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.07,
        effective_from="2026-09-01T00:00:00Z", effective_to="2027-03-31T00:00:00Z")
    version = get_practice(practice["id"])["version"]

    # A fresh DRAFT that overlaps the incumbent's window is refused for the window
    # conflict and left untouched. The temporal check is pinned ahead of the
    # state and affiliation conditions, so it is the conflict — not any state
    # defect — that a caller sees first.
    res_second = api.submit_pricing_agreement(
        second["id"], create_pricing_agreement_submit_payload(version), practice_headers)
    validate_error(res_second, "ERR_PRICING_WINDOW_OVERLAP", expected_status=409)

    untouched = validate_success(
        api.get_pricing_agreement(second["id"], network_admin_headers), 200)
    assert untouched["status"] == "DRAFT"


def test_terms_freeze_beats_referential_contract_check(api, network_admin_headers):
    """PRD §2.10: "While `is_commercial_terms_frozen` is true, no new pricing
    agreement may be created or submitted — attempts are refused with
    `ERR_TERMS_FROZEN`".
    PRD §2.11: "then the commercial-terms freeze, then the shortage-eligibility
    and threshold rules, then cross-entity referential integrity, and finally
    field presence and typing."

    Design: Difficulty/priority_pair_validation_conflict/terms_freeze_beats_referential_contract_check
    """
    set_clock("2026-07-01T00:00:00Z")
    frozen_network = create_network(name="Corner Case Oncology Network",
                                    network_agreement_code="GPO-CC-101")
    practice = create_practice(frozen_network["id"])
    validate_success(
        api.create_affiliation_contract(
            practice["id"], create_affiliation_contract_payload(), network_admin_headers),
        201)
    validate_success(
        api.freeze_commercial_terms(frozen_network["id"], network_admin_headers), 200)

    res = api.create_pricing_agreement(
        practice["id"], create_pricing_agreement_payload(), network_admin_headers)
    validate_error(res, "ERR_TERMS_FROZEN", expected_status=403)

    rows = get_success_data(api.list_pricing_agreements(
        network_admin_headers, params={"practice_id": practice["id"]}))
    assert rows == []