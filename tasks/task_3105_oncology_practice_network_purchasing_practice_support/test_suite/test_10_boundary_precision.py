"""Boundary precision: strict thresholds, half-open windows, zero counts."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, ApiErrorId, set_clock, create_network, create_practice,
    create_product, get_practice, create_activated_contract,
    create_approved_agreement, create_draft_agreement, setup_denial_ratio_scenario,
    make_practice_admin_headers, create_treatment_payload,
    create_administer_payload, get_practice_version, DEFAULT_CLOCK,
    create_pricing_agreement_submit_payload,
)


def test_denial_ratio_strict_greater_than_boundary_at_equality(api, network_admin_headers):
    """PRD §3.9: "Pricing is suspended only when the ratio strictly exceeds the
    practice's `denial_ratio_threshold_pct`, which defaults to 0.20. The boundary
    is strict and not inclusive: a ratio of exactly 0.20 does not suspend, while
    0.25 does."
    PRD §3.9: "With a lifetime numerator of one, the suspension first fires at a
    denominator of four, where one divided by four is 0.25, and not at a
    denominator of five, where one divided by five is 0.20."

    Design: Difficulty/boundary_precision_check/denial_ratio_strict_greater_than_boundary
    """
    # One denial over five settled claims is exactly 0.2000 -> no suspension.
    ctx = setup_denial_ratio_scenario(denied_count=1, paid_count=4,
                                      denial_ratio_threshold_pct=0.20)
    practice = validate_success(
        api.get_practice(ctx["practice"]["id"], network_admin_headers), 200)
    assert practice["denied_claim_count"] == 1
    assert practice["settled_claim_count"] == 5
    assert practice["denied_claim_count"] / practice["settled_claim_count"] == pytest.approx(0.20)

    agreement = validate_success(
        api.get_pricing_agreement(ctx["agreement"]["id"], network_admin_headers), 200)
    assert agreement["status"] == "ACTIVE", (
        "a ratio of exactly 0.20 does not strictly exceed the 0.20 threshold")


def test_denial_ratio_strict_greater_than_boundary_above(api, network_admin_headers):
    """PRD §3.9: "The boundary is strict and not inclusive: a ratio of exactly
    0.20 does not suspend, while 0.25 does. With a lifetime numerator of one, the
    suspension first fires at a denominator of four, where one divided by four is
    0.25".
    PRD §3.9: "When the ratio breaches, every `ACTIVE` pricing agreement of the
    practice becomes `SUSPENDED` with `status_changed_by` set to
    `DENIAL_RATIO_BREACH`".

    Design: Difficulty/boundary_precision_check/denial_ratio_strict_greater_than_boundary
    """
    # One denial over four settled claims is 0.2500 -> suspension fires.
    ctx = setup_denial_ratio_scenario(denied_count=1, paid_count=3,
                                      denial_ratio_threshold_pct=0.20)
    practice = validate_success(
        api.get_practice(ctx["practice"]["id"], network_admin_headers), 200)
    assert practice["denied_claim_count"] == 1
    assert practice["settled_claim_count"] == 4

    agreement = validate_success(
        api.get_pricing_agreement(ctx["agreement"]["id"], network_admin_headers), 200)
    assert agreement["status"] == "SUSPENDED"
    assert agreement["status_changed_by"] == "DENIAL_RATIO_BREACH"


def test_zero_quantity_administration_is_rejected(api, network_admin_headers):
    """PRD §3.7: "an `administered_units` of 0 is refused with
    `ERR_INVALID_REQUEST` and produces neither a draw nor wastage".

    Design: Difficulty/boundary_precision_check/zero_quantity_and_empty_collection_boundaries
    """
    from test_helpers import setup_operational_practice

    ctx = setup_operational_practice(stock_units=100,
                                     product_overrides={"unit_type": "VIAL"})
    practice_id = ctx["practice"]["id"]
    practice_headers = make_practice_admin_headers(practice_id)

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice_id, ctx["provider"]["id"],
                                     ctx["product"]["id"], ctx["protocol"]["id"],
                                     patient_reference="PT-ZERO-1",
                                     administered_units=0, dose_count=1,
                                     vial_yield_units=100,
                                     administered_at="2026-09-02T00:00:00Z"),
            practice_headers),
        201)

    res = api.administer_treatment(
        treatment["id"],
        create_administer_payload(get_practice_version(practice_id)),
        practice_headers)
    assert res.status_code == 400, res.text
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_INVALID_REQUEST, ApiErrorId.ERR_INSUFFICIENT_STOCK])


def test_zero_supply_shortage_cannot_be_allocated(api, network_admin_headers):
    """PRD §3.4: "Allocation is refused with `ERR_THRESHOLD_NOT_MET` when
    `supply_available_units` is zero, since a shortage with no supply cannot be
    allocated, and refused with `ERR_NO_ELIGIBLE_PRACTICES` when no practice in
    the network is `AFFILIATED`."

    Design: Difficulty/boundary_precision_check/zero_quantity_and_empty_collection_boundaries
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    product = create_product(network["id"], unit_type="VIAL",
                             is_shortage_candidate=True)

    shortage = validate_success(
        api.report_shortage(
            network["id"],
            {"drug_product_id": product["id"], "reported_at": DEFAULT_CLOCK,
             "supply_available_units": 0, "allocation_method": "PRO_RATA_BASELINE"},
            network_admin_headers),
        201)

    res = api.allocate_shortage(
        shortage["id"], {"practice_consumption_authorization_cents": {}},
        network_admin_headers)
    validate_error(res, ApiErrorId.ERR_THRESHOLD_NOT_MET, expected_status=409)


def test_allocation_with_no_affiliated_practice_is_refused(api, network_admin_headers):
    """PRD §3.4: "refused with `ERR_NO_ELIGIBLE_PRACTICES` when no practice in
    the network is `AFFILIATED`. Only affiliated practices receive grants;
    `PROSPECTIVE`, `DEPARTING`, `DEPARTED`, and `SUSPENDED` practices receive
    nothing."

    Design: Difficulty/boundary_precision_check/zero_quantity_and_empty_collection_boundaries
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    create_practice(network["id"])  # PROSPECTIVE, so not eligible
    product = create_product(network["id"], unit_type="VIAL",
                             is_shortage_candidate=True)

    shortage = validate_success(
        api.report_shortage(
            network["id"],
            {"drug_product_id": product["id"], "reported_at": DEFAULT_CLOCK,
             "supply_available_units": 100, "allocation_method": "PRO_RATA_BASELINE"},
            network_admin_headers),
        201)

    res = api.allocate_shortage(
        shortage["id"], {"practice_consumption_authorization_cents": {}},
        network_admin_headers)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_PRACTICES, expected_status=409)


def test_pricing_window_half_open_adjacency_is_accepted(api, network_admin_headers):
    """PRD §2.6: "A `PracticePricingAgreement` governs the half-open interval
    that begins at its `effective_from` and ends at its `effective_to`, so the
    instant `effective_from` is inside the window and the instant `effective_to`
    is outside it."
    PRD §2.6: "for a given practice and a given `tier_level`, no two agreements
    may hold intersecting windows while either is in `PENDING_APPROVAL` or
    `ACTIVE`; a submission that would create such an intersection is refused with
    `ERR_PRICING_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/pricing_agreement_half_open_window_overlap
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=140)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-12-31T00:00:00Z")
    practice_headers = make_practice_admin_headers(practice["id"])

    incumbent = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.06,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z")
    validate_success(
        api.submit_pricing_agreement(
            incumbent["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)
    validate_success(
        api.approve_pricing_agreement(incumbent["id"], network_admin_headers), 200)

    adjacency = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.07,
        effective_from="2026-12-31T00:00:00Z", effective_to=None)
    version = get_practice(practice["id"])["version"]
    accepted = validate_success(
        api.submit_pricing_agreement(
            adjacency["id"], create_pricing_agreement_submit_payload(version),
            practice_headers),
        200)
    assert accepted["status"] == "PENDING_APPROVAL"


def test_pricing_window_one_second_early_intersects(api, network_admin_headers):
    """PRD §2.6: "no two agreements may hold intersecting windows while either is
    in `PENDING_APPROVAL` or `ACTIVE`; a submission that would create such an
    intersection is refused with `ERR_PRICING_WINDOW_OVERLAP`".
    PRD §2.6: "the instant `effective_to` is outside it".

    Design: Difficulty/resource_temporal_overlap/pricing_agreement_half_open_window_overlap
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=140)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-12-31T00:00:00Z")
    practice_headers = make_practice_admin_headers(practice["id"])

    incumbent = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.06,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z")
    validate_success(
        api.submit_pricing_agreement(
            incumbent["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)
    validate_success(
        api.approve_pricing_agreement(incumbent["id"], network_admin_headers), 200)

    overlapping = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.07,
        effective_from="2026-12-30T23:59:59Z", effective_to=None)
    version = get_practice(practice["id"])["version"]
    res = api.submit_pricing_agreement(
        overlapping["id"], create_pricing_agreement_submit_payload(version),
        practice_headers)
    validate_error(res, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP, expected_status=409)

    incumbent_after = validate_success(
        api.get_pricing_agreement(incumbent["id"], network_admin_headers), 200)
    assert incumbent_after["status"] == "ACTIVE"


def test_effective_to_absent_means_the_window_never_closes(api, network_admin_headers):
    """PRD §2.6: "An `effective_to` left null means the window never closes."
    PRD §2.6: "An `effective_to` that is present must be strictly later than
    `effective_from`; otherwise the agreement is refused with
    `ERR_INVALID_EFFECTIVE_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/pricing_agreement_half_open_window_overlap
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=140)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-12-31T00:00:00Z")
    practice_headers = make_practice_admin_headers(practice["id"])

    open_ended = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.06,
        effective_from="2026-06-01T00:00:00Z", effective_to=None)
    submitted = validate_success(
        api.submit_pricing_agreement(
            open_ended["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)
    assert submitted["status"] == "PENDING_APPROVAL"
    assert submitted["effective_to"] is None

    # An inverted explicit window is refused outright.
    inverted = create_draft_agreement(
        practice["id"], tier_level="TIER_3", discount_pct=0.04,
        effective_from="2026-12-31T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    res = api.submit_pricing_agreement(
        inverted["id"],
        create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
        practice_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_EFFECTIVE_WINDOW, expected_status=400)


def test_management_term_blackout_with_closed_intervals(api, network_admin_headers):
    """PRD §2.6: "Because the intervals are closed, two engagements for the same
    `service_line` at the same practice may not merely abut — a new engagement
    must begin at least 30 days after the previous engagement's `term_end`, and a
    shorter separation is refused with `ERR_MANAGEMENT_TERM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/management_term_blackout_with_closed_intervals
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=140)
    create_activated_contract(practice["id"],
                              contract_type="MANAGEMENT_SERVICES_ONLY",
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-12-31T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")

    first = validate_success(
        api.create_management_agreement(
            {"practice_id": practice["id"], "service_line": "REVENUE_CYCLE",
             "fee_basis": "PERCENT_OF_NET_COLLECTIONS", "fee_rate": 0.05,
             "fixed_fee_cents": 0, "per_fte_fee_cents": 0, "per_claim_fee_cents": 0,
             "fte_count": 0, "term_start": "2026-01-01T00:00:00Z",
             "term_end": "2026-06-30T00:00:00Z"},
            network_admin_headers),
        201)
    validate_success(
        api.activate_management_agreement(first["id"], network_admin_headers), 200)

    import test_helpers
    too_soon = validate_success(
        api.create_management_agreement(
            test_helpers.create_management_agreement_payload(
                practice["id"], fee_rate=0.06,
                term_start="2026-07-29T00:00:00Z", term_end="2026-12-31T00:00:00Z"),
            network_admin_headers),
        201)
    res = api.activate_management_agreement(too_soon["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_MANAGEMENT_TERM_OVERLAP, expected_status=409)


def test_management_term_blackout_boundary_exactly_thirty_days(api, network_admin_headers):
    """PRD §2.6: "a new engagement must begin at least 30 days after the previous
    engagement's `term_end`".

    Design: Difficulty/resource_temporal_overlap/management_term_blackout_with_closed_intervals
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=140)
    create_activated_contract(practice["id"],
                              contract_type="MANAGEMENT_SERVICES_ONLY",
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-12-31T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")

    first = validate_success(
        api.create_management_agreement(
            {"practice_id": practice["id"], "service_line": "REVENUE_CYCLE",
             "fee_basis": "PERCENT_OF_NET_COLLECTIONS", "fee_rate": 0.05,
             "fixed_fee_cents": 0, "per_fte_fee_cents": 0, "per_claim_fee_cents": 0,
             "fte_count": 0, "term_start": "2026-01-01T00:00:00Z",
             "term_end": "2026-06-30T00:00:00Z"},
            network_admin_headers),
        201)
    validate_success(
        api.activate_management_agreement(first["id"], network_admin_headers), 200)

    import test_helpers
    exactly = validate_success(
        api.create_management_agreement(
            test_helpers.create_management_agreement_payload(
                practice["id"], fee_rate=0.06,
                term_start="2026-07-30T00:00:00Z", term_end="2026-12-31T00:00:00Z"),
            network_admin_headers),
        201)
    activated = validate_success(
        api.activate_management_agreement(exactly["id"], network_admin_headers), 200)
    assert activated["status"] == "ACTIVE"

    # A different service line is not constrained by the same blackout.
    other_line = validate_success(
        api.create_management_agreement(
            {"practice_id": practice["id"], "service_line": "TECHNOLOGY",
             "fee_basis": "FIXED_MONTHLY", "fee_rate": 0.0,
             "fixed_fee_cents": 100000, "per_fte_fee_cents": 0,
             "per_claim_fee_cents": 0, "fte_count": 0,
             "term_start": "2026-07-05T00:00:00Z",
             "term_end": "2026-12-31T00:00:00Z"},
            network_admin_headers),
        201)
    activated_other = validate_success(
        api.activate_management_agreement(other_line["id"], network_admin_headers), 200)
    assert activated_other["status"] == "ACTIVE"