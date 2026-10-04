"""Parallel state axes, cyclic revision loops, optimistic concurrency and
immediate-visibility consistency."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, set_clock, create_network, create_practice, create_product,
    get_practice, create_activated_contract, create_approved_agreement,
    create_draft_agreement, create_published_protocol, create_provider,
    receive_new_lot, adopt_pathways, make_practice_admin_headers,
    get_practice_version, create_purchase_order_payload,
    create_pricing_agreement_submit_payload, create_treatment_payload,
    create_administer_payload, create_claim_submit_payload,
    REVENUE_CYCLE_MANAGER, create_rebate_program, create_rebate_qualification,
    find_draft_claim, DEFAULT_CLOCK,
)


def test_practice_parallel_affiliation_and_pathway_axes(api, network_admin_headers):
    """PRD §3.2: "Two state axes then evolve on the same practice row, and they
    never consult each other."
    PRD §3.2: "the action requires the practice to currently be `AFFILIATED`,
    failing with `ERR_PRACTICE_NOT_AFFILIATED`, and it is reason-agnostic in one
    respect — if the practice's `pathway_steering_status` was `ACTIVE`, it becomes
    `SUSPENDED` as well."
    PRD §3.2: "Reinstatement does not restore the pathway axis —
    `pathway_steering_status` remains `NOT_ADOPTED` or `SUSPENDED` exactly as it
    was."

    Design: Difficulty/non_linear_state_machine/practice_parallel_affiliation_and_pathway_axes
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=250)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")
    create_published_protocol(network["id"])
    practice_headers = make_practice_admin_headers(practice["id"])

    adopted = validate_success(api.adopt_pathways(practice["id"], practice_headers), 200)
    assert adopted["affiliation_status"] == "AFFILIATED"
    assert adopted["pathway_steering_status"] == "ACTIVE"

    suspended = validate_success(
        api.suspend_practice(practice["id"], network_admin_headers), 200)
    assert suspended["affiliation_status"] == "SUSPENDED"
    assert suspended["pathway_steering_status"] == "SUSPENDED"

    reinstated = validate_success(
        api.reinstate_practice(practice["id"], network_admin_headers), 200)
    assert reinstated["affiliation_status"] == "AFFILIATED"
    assert reinstated["pathway_steering_status"] == "SUSPENDED"

    readopted = validate_success(api.adopt_pathways(practice["id"], practice_headers), 200)
    assert readopted["pathway_steering_status"] == "ACTIVE"
    assert readopted["affiliation_status"] == "AFFILIATED"

    withdrawn = validate_success(api.withdraw_pathways(practice["id"], practice_headers), 200)
    assert withdrawn["pathway_steering_status"] == "NOT_ADOPTED"
    assert withdrawn["affiliation_status"] == "AFFILIATED"
    assert withdrawn["pathway_adherence_pct"] == 0


def test_pricing_agreement_draft_pending_revert_cycle(api, network_admin_headers):
    """PRD §3.3: "A `NetworkAdmin` may return it to `DRAFT`, which clears
    `approved_by_user_id` to null; may reject it outright, moving it to
    `REJECTED`; or, once it is `ACTIVE`, may return it to `DRAFT` again — but
    that last path is refused with `ERR_AGREEMENT_IN_USE` if any purchase order
    priced under the agreement has already reached `CONFIRMED`, `SHIPPED`, or
    `RECEIVED`."

    Design: Difficulty/non_linear_state_machine/pricing_agreement_draft_pending_revert_cycle
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=150)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    practice_headers = make_practice_admin_headers(practice["id"])

    agreement = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.08,
        effective_from="2026-06-01T00:00:00Z")
    validate_success(
        api.submit_pricing_agreement(
            agreement["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)

    back = validate_success(
        api.return_agreement_to_draft(agreement["id"], network_admin_headers), 200)
    assert back["status"] == "DRAFT"
    assert back.get("approved_by_user_id") is None

    resubmitted = validate_success(
        api.submit_pricing_agreement(
            agreement["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)
    assert resubmitted["status"] == "PENDING_APPROVAL"
    assert resubmitted["id"] == agreement["id"]

    approved = validate_success(
        api.approve_pricing_agreement(agreement["id"], network_admin_headers), 200)
    assert approved["status"] == "ACTIVE"

    reverted = validate_success(
        api.return_agreement_to_draft(agreement["id"], network_admin_headers), 200)
    assert reverted["status"] == "DRAFT"


def test_stale_practice_version_on_claim_submit_is_precondition_failed(api, network_admin_headers):
    """PRD §2.8: "Submitting a pricing agreement, administering a treatment, and
    submitting a payer claim each require the caller to present the practice
    version it last observed, supplied as `expected_practice_version`. If the
    value presented does not equal the practice's current `version`, the request
    is refused with `ERR_VERSION_MISMATCH` and HTTP status 412".
    PRD §3.9: "It carries the stale-version field of §2.8, so the request supplies
    `expected_practice_version` matching the practice's current `version` and is
    refused with `ERR_VERSION_MISMATCH` at 412 otherwise."

    Design: Corner/cross_cutting_complexity_layers/stale_practice_version_on_claim_submit_is_precondition_failed
    """
    from test_helpers import setup_operational_practice

    ctx = setup_operational_practice(
        stock_units=400, product_overrides={"unit_type": "VIAL"},
        agreement_overrides={"effective_from": "2026-08-01T00:00:00Z"})
    practice_id = ctx["practice"]["id"]
    practice_headers = make_practice_admin_headers(practice_id)

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice_id, ctx["provider"]["id"],
                                     ctx["product"]["id"], ctx["protocol"]["id"],
                                     patient_reference="PT-OCC-1",
                                     administered_units=100, dose_count=1,
                                     vial_yield_units=100,
                                     administered_at="2026-09-02T00:00:00Z"),
            practice_headers),
        201)
    validate_success(
        api.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(practice_id)),
            practice_headers),
        200)
    claim = find_draft_claim(treatment["id"])

    observed = get_practice_version(practice_id)

    # A second receipt advances the practice's version.
    receive_new_lot(practice_id, ctx["product"]["id"], 100,
                    expires_at="2027-09-15T00:00:00Z", lot_number="L-OCC-2")
    assert get_practice_version(practice_id) > observed

    res = api.submit_claim(claim["id"], create_claim_submit_payload(observed),
                           REVENUE_CYCLE_MANAGER)
    validate_error(res, ApiErrorId.ERR_VERSION_MISMATCH, expected_status=412)

    current = validate_success(api.get_payer_claim(claim["id"], network_admin_headers), 200)
    assert current["status"] == "DRAFT"


def test_stale_practice_version_on_claim_submit_is_precondition_failed_recovery(api, network_admin_headers):
    """PRD §2.8: "This is a stale-view rejection, not a locking protocol: a
    caller that has re-read the practice and presents the current version
    proceeds normally."

    Design: Corner/cross_cutting_complexity_layers/stale_practice_version_on_claim_submit_is_precondition_failed
    """
    from test_helpers import setup_operational_practice

    ctx = setup_operational_practice(
        stock_units=400, product_overrides={"unit_type": "VIAL"},
        agreement_overrides={"effective_from": "2026-08-01T00:00:00Z"})
    practice_id = ctx["practice"]["id"]
    practice_headers = make_practice_admin_headers(practice_id)

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice_id, ctx["provider"]["id"],
                                     ctx["product"]["id"], ctx["protocol"]["id"],
                                     patient_reference="PT-OCC-2",
                                     administered_units=100, dose_count=1,
                                     vial_yield_units=100,
                                     administered_at="2026-09-02T00:00:00Z"),
            practice_headers),
        201)
    validate_success(
        api.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(practice_id)),
            practice_headers),
        200)
    claim = find_draft_claim(treatment["id"])
    stale = get_practice_version(practice_id)
    receive_new_lot(practice_id, ctx["product"]["id"], 100,
                    expires_at="2027-09-15T00:00:00Z", lot_number="L-OCC-3")

    validate_error(
        api.submit_claim(claim["id"], create_claim_submit_payload(stale),
                         REVENUE_CYCLE_MANAGER),
        ApiErrorId.ERR_VERSION_MISMATCH, expected_status=412)

    # Re-read and retry.
    fresh = get_practice_version(practice_id)
    retried = validate_success(
        api.submit_claim(claim["id"], create_claim_submit_payload(fresh),
                         REVENUE_CYCLE_MANAGER),
        200)
    assert retried["status"] == "SUBMITTED"


def test_derived_fields_reconcile_after_bounded_reversal(api, network_admin_headers):
    """PRD §3.11: "the affiliation contract returns to `ACTIVE` with
    `rebate_holdback_cents` recomputed to zero, and every rebate qualification
    previously reclaimed has its holdback zeroed, its `is_qualified` restored to
    true, and its status returned to `QUALIFIED`, with each restored amount
    subtracted back out of the practice's `unsettled_balance_cents`."

    Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_after_bounded_reversal
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=100)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-08-01T00:00:00Z")
    product = create_product(network["id"], network_base_price_cents=1000)
    program = create_rebate_program(network["id"], market_share_threshold_pct=0.00,
                                    rebate_pct=0.02, period_epoch_index=2)
    # Route dollars through the period's measured window so the reclaim carries
    # a non-zero amount that the withdrawal can reverse.
    set_clock("2026-10-05T00:00:00Z")
    receive_new_lot(practice["id"], product["id"], 1000, lot_number="L-DR-01")
    set_clock("2026-10-06T00:00:00Z")
    qualification = create_rebate_qualification(practice["id"], program["id"])
    assert qualification["rebate_amount_cents"] > 0

    practice_headers = make_practice_admin_headers(practice["id"])
    noticed = validate_success(api.departure_notice(practice["id"], practice_headers), 200)
    assert noticed["unsettled_balance_cents"] > 0

    withdrawn = validate_success(api.withdraw_departure(practice["id"], practice_headers), 200)
    assert withdrawn["affiliation_status"] == "AFFILIATED"
    assert withdrawn["unsettled_balance_cents"] == 0
    assert withdrawn["departure_effective_epoch_index"] is None

    restored = validate_success(
        api.get_rebate_qualification(qualification["id"], network_admin_headers), 200)
    assert restored["holdback_cents"] == 0
    assert restored["status"] == "QUALIFIED"
    assert restored["is_qualified"] is True


def test_immediate_visibility_of_state_change_in_the_same_response(api, network_admin_headers, network_analyst_headers):
    """PRD §3.11: "The practice returns to `AFFILIATED` with
    `departure_effective_epoch_index` back to null, the affiliation contract
    returns to `ACTIVE` with `rebate_holdback_cents` recomputed to zero".

    Design: Corner/consistency_model/immediate_visibility_of_state_change_in_the_same_response
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=100)
    contract = create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-08-01T00:00:00Z")
    program = create_rebate_program(network["id"], market_share_threshold_pct=0.00,
                                    rebate_pct=0.02, period_epoch_index=2)
    create_rebate_qualification(practice["id"], program["id"])

    practice_headers = make_practice_admin_headers(practice["id"])
    validate_success(api.departure_notice(practice["id"], practice_headers), 200)

    withdrawn = validate_success(api.withdraw_departure(practice["id"], practice_headers), 200)
    assert withdrawn["affiliation_status"] == "AFFILIATED"
    assert withdrawn["departure_effective_epoch_index"] is None
    assert withdrawn["unsettled_balance_cents"] == 0

    contract_after = validate_success(
        api.get_affiliation_contract(contract["id"], network_analyst_headers), 200)
    assert contract_after["status"] == "ACTIVE"
    assert contract_after["rebate_holdback_cents"] == 0