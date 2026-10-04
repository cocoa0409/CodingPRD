"""Claims: admissibility, the cash-settlement arithmetic and the settlement cascade."""
from test_helpers import (
    add_approved_appraisal,
    add_approved_scheduled_item,
    add_verified_mitigation,
    api_client,
    assert_claim,
    attach_enrollment,
    create_agency,
    create_enrollment,
    create_property,
    create_zone,
    get_success_data,
    make_agency_producer_headers,
    reload_property,
    report_claim,
    run_posture_eval,
    setup_active_zone_mitigation_required,
    setup_active_zone_underwritable,
    setup_approved_enrollment,
    setup_attached_enrollment,
    setup_bound_claim,
    setup_reviewed_claim,
    submit_enrollment,
    validate_error,
    validate_success,
)


def test_settlement_ceiling_and_scarcity_factor_compose(api, underwriter_headers,
                                                        claims_adjuster_headers):
    """PRD 3.8: "The applicable ceiling follows the enrollment's `replacement_provision`:
    it is unlimited when the provision is `GUARANTEED`, the extended replacement limit
    when the provision is `EXTENDED`, and the enrollment's `dwelling_coverage_cents` in
    every other case."
    PRD 3.8: "The `settlement_amount_cents` is the capped figure multiplied by the
    scarcity factor, rounded half up, and `deductible_applied_cents` is the lesser of
    the raw deductible and that settlement value."

    Design: Difficulty/combinatorial_formula/settlement_formula_circular_dependency_pinned_by_evaluation_order
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZD1C", agency_code="AG3C", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band="CLEARED")
    assert enroll["replacement_provision"] == "EXTENDED"

    claim = report_claim(enroll["id"], cause_of_loss="WILDFIRE",
                         reported_indemnity_cents=250_000_000,
                         adjuster_override=True)
    reviewed = validate_success(
        api_client.review_claim(claim["id"], claims_adjuster_headers), 200)
    assert reviewed["status"] == "UNDER_REVIEW"

    settled = validate_success(
        api_client.approve_claim(claim["id"], claims_adjuster_headers), 200)
    assert settled["status"] == "APPROVED"
    # 250000000 capped by the 300000000 extended limit, then scaled by 1.20.
    assert settled["settlement_amount_cents"] == 300_000_000
    assert settled["deductible_applied_cents"] == 6_000_000
    assert settled["cash_settlement_eligible"] is False


def test_specialty_restoration_override_is_what_scales_the_loss(
        api, underwriter_headers, claims_adjuster_headers):
    """PRD 3.8: "A scarcity factor then applies — 1.20 when the adjuster has set
    `adjuster_override` for a specialty restoration vendor, and 1.0 otherwise."
    PRD 3.8: "otherwise the lesser of the reported indemnity and the ceiling"

    Design: Difficulty/combinatorial_formula/settlement_formula_circular_dependency_pinned_by_evaluation_order
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZD1D", agency_code="AG3D", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band="CLEARED")

    claim = report_claim(enroll["id"], cause_of_loss="WIND",
                         reported_indemnity_cents=250_000_000,
                         adjuster_override=False)
    validate_success(api_client.review_claim(claim["id"], claims_adjuster_headers), 200)
    plain = validate_success(
        api_client.approve_claim(claim["id"], claims_adjuster_headers), 200)
    # Without the override the capped loss passes through unscaled.
    assert plain["settlement_amount_cents"] == 250_000_000
    assert plain["deductible_applied_cents"] == 3_000_000


def test_a_loss_above_the_extended_limit_is_refused(api, underwriter_headers,
                                                    claims_adjuster_headers):
    """PRD 3.8: "The reported indemnity must not exceed the applicable replacement-cost
    limit — the check is skipped when the provision is `GUARANTEED` because that limit
    is unlimited, and when it fires it is refused with `ERR_COVERAGE_ABOVE_APPRAISAL`,
    whose condition is that the provision is `EXTENDED` or `NONE`."

    Design: Difficulty/combinatorial_formula/settlement_formula_circular_dependency_pinned_by_evaluation_order
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZD1E", agency_code="AG3E", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band="CLEARED")
    claim = report_claim(enroll["id"], cause_of_loss="WILDFIRE",
                         reported_indemnity_cents=350_000_000,
                         adjuster_override=True)
    validate_success(api_client.review_claim(claim["id"], claims_adjuster_headers), 200)

    res = api_client.approve_claim(claim["id"], claims_adjuster_headers)
    validate_error(res, "ERR_COVERAGE_ABOVE_APPRAISAL", expected_status=422)


def test_a_loss_within_coverage_under_a_none_provision_is_payed_at_coverage(
        api, underwriter_headers, claims_adjuster_headers):
    """PRD 3.8: "whereas under a `NONE` provision the excess over Coverage A itself is
    refused, because Coverage A is the ceiling."

    Design: Difficulty/combinatorial_formula/settlement_formula_circular_dependency_pinned_by_evaluation_order
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZD1F", agency_code="AG3F", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band=None)
    assert enroll["replacement_provision"] == "NONE"

    # Inside the ceiling the loss settles at its own value.
    inside = report_claim(enroll["id"], cause_of_loss="WATER",
                          reported_indemnity_cents=290_000_000,
                          adjuster_override=False)
    validate_success(api_client.review_claim(inside["id"], claims_adjuster_headers), 200)
    ok = validate_success(api_client.approve_claim(inside["id"], claims_adjuster_headers), 200)
    assert ok["settlement_amount_cents"] == 290_000_000

    # Above the ceiling the excess is refused.
    outside = report_claim(enroll["id"], cause_of_loss="WATER",
                           reported_indemnity_cents=310_000_000,
                           adjuster_override=False)
    validate_success(api_client.review_claim(outside["id"], claims_adjuster_headers), 200)
    res = api_client.approve_claim(outside["id"], claims_adjuster_headers)
    validate_error(res, "ERR_COVERAGE_ABOVE_APPRAISAL", expected_status=422)


def test_a_guaranteed_provision_settles_without_a_limit(
        api, underwriter_headers, claims_adjuster_headers):
    """PRD 3.8: "`cash_settlement_eligible` is true exactly when the provision is
    `GUARANTEED`."
    PRD 3.7: "When a defense dispatch is in progress — meaning one exists in
    `VENDOR_ASSIGNED` or `ON_SITE` — the provision is `GUARANTEED` and the guaranteed
    limit is unlimited, represented as null."

    Design: Difficulty/dual_variant_calc/premium_calculation_variant_at_extended_coverage
    """
    zone, agency, prop = setup_active_zone_underwritable(
        zone_code="ZGUA", agency_code="AGGUA")
    get_success_data(api_client.request_dispatch(prop["id"], underwriter_headers))
    get_success_data(api_client.poll_vendors(zone["id"], underwriter_headers))

    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=300_000_000)
    submit_enrollment(enroll["id"], agency["id"])
    approved = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)
    assert approved["replacement_provision"] == "GUARANTEED"

    attached = attach_enrollment(approved["id"], prop["id"])
    assert attached["status"] == "ATTACHED"

    claim = report_claim(attached["id"], cause_of_loss="WILDFIRE",
                         reported_indemnity_cents=350_000_000,
                         adjuster_override=False)
    validate_success(api_client.review_claim(claim["id"], claims_adjuster_headers), 200)
    settled = validate_success(
        api_client.approve_claim(claim["id"], claims_adjuster_headers), 200)
    # The unlimited ceiling lets the full loss through, and the claim is cash-eligible.
    assert settled["settlement_amount_cents"] == 350_000_000
    assert settled["cash_settlement_eligible"] is True


def test_a_loss_at_or_below_the_deductible_has_nothing_to_settle(
        api, underwriter_headers, claims_adjuster_headers):
    """PRD 3.8: "a claim whose reported indemnity is at or below the deductible that
    would be applied is refused with `ERR_CLAIM_BELOW_DEDUCTIBLE`, so the payable line
    is drawn strictly above the deductible with nothing to settle at or beneath it."
    PRD 3.8: "The deductible percentage depends on the cause: two percent for
    `WILDFIRE`"

    Design: Corner/calculations/deductible_at_or_above_the_loss_leaves_nothing_to_settle
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZDED", agency_code="AGDED", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band=None)

    below = report_claim(enroll["id"], cause_of_loss="WILDFIRE",
                         reported_indemnity_cents=3_000_000, adjuster_override=False)
    validate_success(api_client.review_claim(below["id"], claims_adjuster_headers), 200)
    res = api_client.approve_claim(below["id"], claims_adjuster_headers)
    validate_error(res, "ERR_CLAIM_BELOW_DEDUCTIBLE", expected_status=422)


def test_a_loss_above_the_deductible_is_admissible(api, underwriter_headers,
                                                   claims_adjuster_headers):
    """PRD 3.8: "a claim whose reported indemnity is at or below the deductible that would
    be applied is refused with `ERR_CLAIM_BELOW_DEDUCTIBLE`, so the payable line is
    drawn strictly above the deductible with nothing to settle at or beneath it."
    PRD 3.8: "The raw deductible is that percentage applied to the enrollment's
    `dwelling_coverage_cents`, rounded half up."

    Design: Corner/calculations/deductible_at_or_above_the_loss_leaves_nothing_to_settle
    """
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code="ZDED2", agency_code="AGDED2", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band=None)

    above = report_claim(enroll["id"], cause_of_loss="WILDFIRE",
                         reported_indemnity_cents=9_000_000, adjuster_override=False)
    validate_success(api_client.review_claim(above["id"], claims_adjuster_headers), 200)
    settled = validate_success(
        api_client.approve_claim(above["id"], claims_adjuster_headers), 200)
    assert settled["settlement_amount_cents"] == 9_000_000
    assert settled["deductible_applied_cents"] == 6_000_000


def test_claim_review_is_gated_on_a_bound_enrollment(api, underwriter_headers,
                                                     claims_adjuster_headers):
    """PRD 3.8: "Review is the adjuster's first act and it is refused with
    `ERR_ENROLLMENT_NOT_BOUND` unless the parent enrollment is `ATTACHED`; the
    rationale is simple, in that an unattached policy has no coverage to draw on."

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_the_parent_enrollment_to_be_attached
    """
    zone, agency, prop, enroll = setup_approved_enrollment(
        zone_code="ZCLM", agency_code="AGCLM", coverage_cents=300_000_000)
    assert enroll["status"] == "APPROVED"

    claim = report_claim(enroll["id"], cause_of_loss="WILDFIRE",
                         reported_indemnity_cents=200_000_000)
    res = api_client.review_claim(claim["id"], claims_adjuster_headers)
    validate_error(res, "ERR_ENROLLMENT_NOT_BOUND", expected_status=409)

    still = get_success_data(api_client.list_enrollment_claims(
        enroll["id"], claims_adjuster_headers))
    assert still[0]["status"] == "REPORTED"


def test_the_same_claim_enters_review_once_the_enrollment_binds(
        api, underwriter_headers, claims_adjuster_headers):
    """PRD 3.8: "Review is the adjuster's first act and it is refused with
    `ERR_ENROLLMENT_NOT_BOUND` unless the parent enrollment is `ATTACHED`"
    PRD 3.7: "Attachment is the binding act"

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_the_parent_enrollment_to_be_attached
    """
    zone, agency, prop, enroll = setup_approved_enrollment(
        zone_code="ZCLM2", agency_code="AGCLM2", coverage_cents=300_000_000)
    claim = report_claim(enroll["id"], cause_of_loss="WIND",
                         reported_indemnity_cents=200_000_000)
    validate_error(api_client.review_claim(claim["id"], claims_adjuster_headers),
                   "ERR_ENROLLMENT_NOT_BOUND", expected_status=409)

    attach_enrollment(enroll["id"], prop["id"])
    reviewed = validate_success(
        api_client.review_claim(claim["id"], claims_adjuster_headers), 200)
    assert reviewed["status"] == "UNDER_REVIEW"


def test_settlement_releases_the_property_scheduled_property(api, underwriter_headers,
                                                             claims_adjuster_headers):
    """PRD 3.8: "it transitions every scheduled item of the property that is in
    `ATTACHED` status back to `APPROVED` with `attached_value_cents` set to 0, after
    which the property's `scheduled_valuation_cents` and `total_insured_value_cents`
    are recomputed."
    PRD 3.2: "Consumption is the other path: when the property's enrollment reaches
    `ATTACHED`, every approved scheduled item of that property transitions to `ATTACHED`
    automatically"

    Design: Difficulty/cross_entity_state_dependency/scheduled_item_attachment_is_gated_on_the_property_enrollment
    """
    zone = create_zone(zone_code="ZO1C", wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code="AG14C")
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"], dwelling_cost_cents=200_000_000)
    run_posture_eval(prop["id"])
    item = add_approved_scheduled_item(prop["id"], item_type="JEWELRY",
                                       declared_value_cents=50_000_000,
                                       appraised_value_cents=60_000_000)
    assert item["status"] == "APPROVED"

    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=300_000_000)
    submit_enrollment(enroll["id"], agency["id"])
    approved = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)
    attached = attach_enrollment(approved["id"], prop["id"])
    assert attached["status"] == "ATTACHED"

    # Consumption: the approved item rides the enrollment into ATTACHED.
    attached_item = get_success_data(api_client.list_scheduled_items(
        prop["id"], underwriter_headers, params={"status": "ATTACHED"}))
    assert len(attached_item) == 1
    assert attached_item[0]["attached_value_cents"] == 50_000_000
    assert reload_property(prop["id"])["scheduled_valuation_cents"] == 50_000_000

    claim = report_claim(attached["id"], cause_of_loss="THEFT",
                         reported_indemnity_cents=50_000_000)
    validate_success(api_client.review_claim(claim["id"], claims_adjuster_headers), 200)
    validate_success(api_client.approve_claim(claim["id"], claims_adjuster_headers), 200)
    validate_success(api_client.settle_claim(claim["id"], claims_adjuster_headers), 200)

    released = get_success_data(api_client.list_scheduled_items(
        prop["id"], underwriter_headers, params={"status": "APPROVED"}))
    assert len(released) == 1
    assert released[0]["attached_value_cents"] == 0
    assert reload_property(prop["id"])["scheduled_valuation_cents"] == 0


def test_a_claim_is_reported_against_a_bound_policy(api, underwriter_headers,
                                                    claims_adjuster_headers):
    """PRD 3.8: "A claim is reported against a bound policy by naming the
    `cause_of_loss` — `WILDFIRE`, `WIND`, `HALL`, `WATER`, `THEFT` or `OTHER` — the
    `loss_date`, the `reported_indemnity_cents` (which must be at least zero), an
    optional `adjuster_user_id` and an optional `adjuster_override` defaulting to
    false."
    PRD 3.8: "The claim is born `REPORTED` with `reported_at` stamped, and all of its
    monetary fields — `settlement_amount_cents`, `deductible_applied_cents` and
    `limit_applied_cents` — at 0, with `cash_settlement_eligible` false."

    Design: Corner/cross_cutting_layers/claim_status_under_review_reads_consistent_with_its_approval
    """
    zone, agency, prop, enroll, claim = setup_bound_claim(
        zone_code="ZREPORT", agency_code="AGREPORT",
        cause_of_loss="HALL", reported_indemnity_cents=50_000_000)
    assert_claim(claim)
    assert claim["status"] == "REPORTED"
    assert claim["reported_at"]
    assert claim["settlement_amount_cents"] == 0
    assert claim["deductible_applied_cents"] == 0
    assert claim["limit_applied_cents"] == 0
    assert claim["cash_settlement_eligible"] is False


def test_two_read_surfaces_report_the_same_settlement(api, underwriter_headers,
                                                      claims_adjuster_headers):
    """PRD 3.8: "The `settlement_amount_cents` is the capped figure multiplied by the
    scarcity factor, rounded half up, and `deductible_applied_cents` is the lesser of
    the raw deductible and that settlement value."

    Design: Corner/cross_cutting_layers/claim_status_under_review_reads_consistent_with_its_approval
    """
    zone, agency, prop, enroll, claim = setup_reviewed_claim(
        zone_code="ZFLAT", agency_code="AGFLAT", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, cause_of_loss="WILDFIRE",
        reported_indemnity_cents=50_000_000)
    approved = validate_success(
        api_client.approve_claim(claim["id"], claims_adjuster_headers), 200)
    assert approved["settlement_amount_cents"] == 50_000_000
    assert approved["deductible_applied_cents"] == 6_000_000

    flat = get_success_data(api_client.list_claims(
        claims_adjuster_headers,
        params={"enrollment_id": enroll["id"], "status": "APPROVED"}))
    nested = get_success_data(api_client.list_enrollment_claims(
        enroll["id"], claims_adjuster_headers, params={"status": "APPROVED"}))
    assert len(flat) == 1 and len(nested) == 1
    assert flat[0]["settlement_amount_cents"] == nested[0]["settlement_amount_cents"]

    settled = validate_success(
        api_client.settle_claim(claim["id"], claims_adjuster_headers), 200)
    assert settled["status"] == "SETTLED"
    flat_after = get_success_data(api_client.list_claims(
        claims_adjuster_headers, params={"enrollment_id": enroll["id"]}))
    assert flat_after[0]["status"] == "SETTLED"