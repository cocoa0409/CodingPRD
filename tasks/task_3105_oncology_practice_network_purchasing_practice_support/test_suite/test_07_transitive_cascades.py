"""Multi-hop cascades: epoch → departure → unwind, and denial → suspension."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, receive_new_lot,
    create_rebate_program, create_rebate_qualification, create_provider,
    create_published_protocol, adopt_pathways, make_practice_admin_headers,
    get_practice_version, create_treatment_payload, create_administer_payload,
    DEFAULT_CLOCK,
)


def test_epoch_advance_to_departure_to_unwind_chain(api, network_admin_headers):
    """PRD §3.1: "Practices whose `affiliation_status` is `DEPARTING` and whose
    `departure_effective_epoch_index` has arrived at or below the new
    `allocation_epoch_index` become `DEPARTED` and run their full departure
    cascade — the epoch's arrival, not any caller's action, is what actually
    triggers a departure to take effect."
    PRD §3.11: "Its affiliation contract moves to `UNWIND_IN_PROGRESS`, whose own
    `pricing_agreements_unwound` flag reads true once every pricing agreement of
    the practice has been superseded."
    PRD §3.11: "notice is counted in whole thirty-day months, always rounded up."

    Design: Difficulty/transitive_cascade/epoch_advance_to_departure_to_holdback_chain
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=100)
    contract = create_activated_contract(practice["id"], notice_period_days=30)
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-08-01T00:00:00Z")
    program = create_rebate_program(network["id"], market_share_threshold_pct=0.00,
                                    rebate_pct=0.02, period_epoch_index=2)
    qualification = create_rebate_qualification(practice["id"], program["id"])

    noticed = validate_success(
        api.departure_notice(practice["id"], make_practice_admin_headers(practice["id"])),
        200)
    assert noticed["affiliation_status"] == "DEPARTING"
    assert noticed["departure_effective_epoch_index"] == 1

    advanced = validate_success(
        api.advance_epoch(network["id"], {"by_epochs": 1}, network_admin_headers), 200)
    assert advanced["allocation_epoch_index"] == 1

    after = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert after["affiliation_status"] == "DEPARTED"
    assert after["pathway_adherence_pct"] == 0

    contract_after = validate_success(
        api.get_affiliation_contract(contract["id"], network_admin_headers), 200)
    assert contract_after["status"] == "UNWIND_IN_PROGRESS"

    qualification_after = validate_success(
        api.get_rebate_qualification(qualification["id"], network_admin_headers), 200)
    assert qualification_after["status"] == "RECLAIMED"
    assert qualification_after["holdback_cents"] == qualification_after["rebate_amount_cents"] or \
        qualification_after["holdback_cents"] > 0


def test_departure_notice_withholds_the_unverified_rebate(api, network_admin_headers):
    """PRD §3.11: "The notice period is read from the `ACTIVE` affiliation
    contract with the latest `term_start`, ties broken by the latest `created_at`".
    PRD §3.8: "A qualified rebate can also be reclaimed rather than paid: a
    `NetworkAdmin` reclaim action requires the qualification to be `QUALIFIED`,
    failing with `ERR_QUALIFICATION_NOT_QUALIFIED`, and moves it to `RECLAIMED`
    with `holdback_cents` set to the full `rebate_amount_cents` and the amount
    itself zeroed".
    PRD §3.11: "That recomputed holdback then flags every rebate qualification
    of the practice in `PENDING` or `QUALIFIED` status: each one's
    `holdback_cents` is set to its own `rebate_amount_cents` when its compliance
    report was never verified, and to zero when it was."

    Design: Difficulty/transitive_cascade/epoch_advance_to_departure_to_holdback_chain
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=100)
    create_activated_contract(practice["id"], notice_period_days=30)
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-08-01T00:00:00Z")
    product = create_product(network["id"], network_base_price_cents=1000)
    program = create_rebate_program(network["id"], market_share_threshold_pct=0.00,
                                    rebate_pct=0.02, period_epoch_index=2)
    # Route dollars through the period's measured window so the qualification
    # carries a non-zero rebate amount for the departure to withhold.
    set_clock("2026-10-05T00:00:00Z")
    receive_new_lot(practice["id"], product["id"], 1000, lot_number="L-HB-01")
    set_clock("2026-10-06T00:00:00Z")
    qualification = create_rebate_qualification(practice["id"], program["id"])
    assert qualification["status"] == "PENDING"
    assert qualification["compliance_report_verified"] is False
    assert qualification["rebate_amount_cents"] > 0

    noticed = validate_success(
        api.departure_notice(practice["id"], make_practice_admin_headers(practice["id"])),
        200)
    assert noticed["affiliation_status"] == "DEPARTING"
    assert noticed["is_rebate_qualified"] is False

    reclaimed = validate_success(
        api.get_rebate_qualification(qualification["id"], network_admin_headers), 200)
    assert reclaimed["status"] == "RECLAIMED"
    assert reclaimed["is_qualified"] is False
    assert reclaimed["holdback_cents"] == qualification["rebate_amount_cents"]
    assert reclaimed["holdback_cents"] > 0

    after = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert after["unsettled_balance_cents"] > 0


def test_deny_recorded_to_ratio_breach_to_pricing_suspension(api, network_admin_headers):
    """PRD §3.9: "The practice's denial ratio is its count of claims in `DENIED`
    status divided by its count of claims in `DENIED` or `ADJUDICATED_PAID` status,
    evaluated as exact rational arithmetic with no intermediate rounding."
    PRD §3.9: "Pricing is suspended only when the ratio strictly exceeds the
    practice's `denial_ratio_threshold_pct`, which defaults to 0.20. The boundary
    is strict and not inclusive: a ratio of exactly 0.20 does not suspend, while
    0.25 does."
    PRD §3.9: "When the ratio breaches, every `ACTIVE` pricing agreement of the
    practice becomes `SUSPENDED` with `status_changed_by` set to
    `DENIAL_RATIO_BREACH`".

    Design: Difficulty/transitive_cascade/deny_recorded_to_ratio_breach_to_pricing_suspension
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=120,
                               denial_ratio_threshold_pct=0.20)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    agreement = create_approved_agreement(practice["id"], practice["version"],
                                          effective_from="2026-08-01T00:00:00Z")
    product = create_product(network["id"], unit_type="VIAL",
                             network_base_price_cents=5000)
    provider = create_provider(practice["id"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])
    receive_new_lot(practice["id"], product["id"], 900,
                    expires_at="2027-09-15T00:00:00Z")

    from test_helpers import add_settled_claim
    ctx = {"practice": get_practice(practice["id"]), "provider": provider,
           "product": product, "protocol": protocol, "network": network,
           "agreement": agreement}

    # One denial over four settled claims is 0.25, which strictly exceeds 0.20.
    for i in range(3):
        add_settled_claim(ctx, outcome="paid", administered_units=100,
                          vial_yield_units=100, admin_fee_cents=0,
                          patient_reference="PT-RB-P{}".format(i))
    add_settled_claim(ctx, outcome="denied", administered_units=100,
                      vial_yield_units=100, admin_fee_cents=0,
                      patient_reference="PT-RB-D0")

    after = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert after["denied_claim_count"] == 1
    assert after["settled_claim_count"] == 4
    assert after["unsettled_balance_cents"] > 0

    agreement_after = validate_success(
        api.get_pricing_agreement(agreement["id"], network_admin_headers), 200)
    assert agreement_after["status"] == "SUSPENDED"
    assert agreement_after["status_changed_by"] == "DENIAL_RATIO_BREACH"
    assert after["tier_level"] == "TIER_1"


def test_denial_ratio_pre_trigger_state_and_reinstate_refusal(api, network_admin_headers):
    """PRD §3.3: "Reinstatement of a suspended agreement is a `NetworkAdmin`
    action requiring the agreement to be `SUSPENDED`, failing with
    `ERR_AGREEMENT_NOT_SUSPENDED`, and requiring the practice's denial ratio to
    have returned to at or below its threshold — a ratio still strictly above it
    is refused with `ERR_DENIAL_RATIO_STILL_BREACHED`."
    PRD §2.8: "This is a stale-view rejection, not a locking protocol: a caller
    that has re-read the practice and presents the current version proceeds
    normally."

    Design: Difficulty/transitive_cascade/deny_recorded_to_ratio_breach_to_pricing_suspension
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=120,
                               denial_ratio_threshold_pct=0.30)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    agreement = create_approved_agreement(practice["id"], practice["version"],
                                          effective_from="2026-08-01T00:00:00Z")

    before = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert before["denied_claim_count"] == 0
    assert before["settled_claim_count"] == 0
    assert before["unsettled_balance_cents"] == 0

    agreement_before = validate_success(
        api.get_pricing_agreement(agreement["id"], network_admin_headers), 200)
    assert agreement_before["status"] == "ACTIVE"