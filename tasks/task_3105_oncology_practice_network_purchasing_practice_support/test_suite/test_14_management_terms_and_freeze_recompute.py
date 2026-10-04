"""Management-term validity and the recomputed commercial-terms freeze flag."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, create_draft_agreement,
    make_practice_admin_headers, create_management_agreement_payload,
    create_pricing_agreement_submit_payload, DEFAULT_CLOCK,
)


def test_inverted_management_term_is_refused(api, network_admin_headers):
    """PRD §2.6: "`PracticeManagementAgreement` terms are closed intervals: both
    `term_start` and `term_end` are inside the engagement. A `term_end` earlier
    than `term_start` is refused with `ERR_INVALID_MANAGEMENT_TERM`."
    PRD §3.10: "Activation requires the agreement to be `DRAFT`, failing with
    `ERR_MANAGEMENT_AGREEMENT_NOT_DRAFT`; requires the practice to be
    `AFFILIATED` or `SUSPENDED`, failing with `ERR_PRACTICE_NOT_AFFILIATED`;
    requires `term_end` to be at or after `term_start`, failing with
    `ERR_INVALID_MANAGEMENT_TERM`".

    Design: Difficulty/resource_temporal_overlap/management_term_blackout_with_closed_intervals
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=140)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")

    inverted = validate_success(
        api.create_management_agreement(
            create_management_agreement_payload(
                practice["id"], term_start="2026-06-30T00:00:00Z",
                term_end="2026-01-01T00:00:00Z"),
            network_admin_headers),
        201)

    res = api.activate_management_agreement(inverted["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_MANAGEMENT_TERM, expected_status=400)


def test_activatable_management_term_is_pinned_and_accrued(api, network_admin_headers):
    """PRD §3.10: "On activation `active_month_count` is pinned as the whole
    calendar months between `term_start` and the earlier of `term_end` and the
    logical clock, inclusive of the month containing `term_start`, and
    `accrued_fee_cents` is computed as described below."
    PRD §3.10: "A term is counted in whole calendar months from `term_start` to
    the earlier of `term_end` and the logical clock, inclusive of the month
    containing `term_start`; a term spanning the first of January to the
    thirtieth of June is six months."

    Design: Difficulty/resource_temporal_overlap/management_term_blackout_with_closed_intervals
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=140)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")

    agreement = validate_success(
        api.create_management_agreement(
            create_management_agreement_payload(
                practice["id"], term_start="2026-01-01T00:00:00Z",
                term_end="2026-06-30T00:00:00Z"),
            network_admin_headers),
        201)
    activated = validate_success(
        api.activate_management_agreement(agreement["id"], network_admin_headers), 200)

    assert activated["status"] == "ACTIVE"
    assert activated["active_month_count"] == 6
    assert activated["accrued_fee_cents"] >= 0


def test_freeze_flag_is_recomputed_from_departing_practices(api, network_admin_headers):
    """PRD §2.10: "The flag is recomputed rather than merely toggled — it reads
    true while at least one practice of the network is `DEPARTED` or `DEPARTING`."
    PRD §3.11: "The network's freeze flag is recomputed and the practice's
    `version` advances."

    Design: Difficulty/priority_pair_validation_conflict/terms_freeze_beats_referential_contract_check
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=100)
    create_activated_contract(practice["id"], notice_period_days=30)
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-08-01T00:00:00Z")

    before = validate_success(api.get_network(network["id"], network_admin_headers), 200)
    assert before["is_commercial_terms_frozen"] is False

    validate_success(
        api.departure_notice(practice["id"], make_practice_admin_headers(practice["id"])),
        200)

    after = validate_success(api.get_network(network["id"], network_admin_headers), 200)
    assert after["is_commercial_terms_frozen"] is True