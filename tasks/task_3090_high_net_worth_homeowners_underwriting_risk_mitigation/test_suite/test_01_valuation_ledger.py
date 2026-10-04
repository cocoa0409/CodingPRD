"""Replacement-cost valuation: the appraisal cycle, the contribution ledger and lapse."""
from test_helpers import (
    api_client,
    assert_property_invariants,
    create_appraisal,
    get_success_data,
    reload_property,
    reset_clock,
    review_and_approve_appraisal,
    setup_property_with_reviewed_second_appraisal,
    setup_submitted_enrollment,
    setup_underwritable_property,
    validate_error,
    validate_success,
)


def test_reopened_appraisal_leaves_the_valuation_ledger(api, underwriter_headers):
    """PRD 3.1: "An underwriter may re-open an already approved appraisal for a fresh
    review cycle by naming the `appraisal_id`; the target row returns to `REVIEWED`
    with `percent_complete` reset to 0.00, and the property's dwelling and total
    insured value are recomputed so the row stops contributing immediately."
    PRD 3.1: "The re-opened row is then recycled through review and approval rather
    than replaced, which is precisely why a provision can be re-derived from a
    superseded baseline."

    Design: Difficulty/non_linear_state_machine/appraisal_cycle_reopens_an_approved_valuation
    """
    prop = setup_underwritable_property(zone_code="ZF1", agency_code="AG5")
    before = reload_property(prop["id"])
    assert before["dwelling_replacement_cost_cents"] == 200_000_000

    approved = get_success_data(api_client.list_appraisals(prop["id"], underwriter_headers))
    appraisal_id = approved[0]["id"]

    reopened = validate_success(
        api_client.reappraise(prop["id"], appraisal_id, underwriter_headers), 200)
    assert reopened["status"] == "REVIEWED"
    assert reopened["percent_complete"] == 0.00

    after = reload_property(prop["id"])
    assert after["dwelling_replacement_cost_cents"] == 0
    assert after["base_posture"] == "PENDING_APPRAISAL"
    assert_property_invariants(after)

    # The machine re-enters a state it had already left: re-opening leaves the row
    # in REVIEWED, and the same row approves again from there (PRD §3.1).
    reapproved = get_success_data(
        api_client.approve_appraisal(appraisal_id, underwriter_headers))
    assert reapproved["status"] == "APPROVED"
    assert reapproved["percent_complete"] == 1.00
    assert reload_property(prop["id"])["dwelling_replacement_cost_cents"] == 200_000_000


def test_superseded_reviewed_row_is_retired_at_full_weight(api, underwriter_headers):
    """PRD 3.1: "A reviewed row can also be marked `SUPERSEDED` — which is how a
    desktop estimate or a drive-by is retired while still contributing at full weight"

    Design: Difficulty/non_linear_state_machine/appraisal_cycle_reopens_an_approved_valuation
    """
    prop = setup_underwritable_property(zone_code="ZF2", agency_code="AG52")
    estimate = create_appraisal(prop["id"], valuation_method="DRIVE_BY",
                                dwelling_cost_cents=90_000_000)
    get_success_data(api_client.review_appraisal(estimate["id"], underwriter_headers))

    superseded = validate_success(
        api_client.supersede_appraisal(estimate["id"], underwriter_headers), 200)
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["percent_complete"] == 1.00

    # A superseded row still contributes at full weight.
    after = reload_property(prop["id"])
    assert after["dwelling_replacement_cost_cents"] == 290_000_000
    assert_property_invariants(after)


def test_reopen_refused_while_another_appraisal_is_in_flight(api, underwriter_headers):
    """PRD 3.1: "Re-opening is refused while any other appraisal of the same property
    sits in `PENDING_REVIEW` or `REVIEWED`, so the property never has two valuations
    in flight."

    Design: Corner/entities/appraisal_percent_complete_is_computed_on_create_extra_field_ignored
    """
    prop = setup_underwritable_property(zone_code="ZF3", agency_code="AG53")
    approved = get_success_data(api_client.list_appraisals(prop["id"], underwriter_headers))[0]
    second = create_appraisal(prop["id"], dwelling_cost_cents=90_000_000)
    get_success_data(api_client.review_appraisal(second["id"], underwriter_headers))

    res = api_client.reappraise(prop["id"], approved["id"], underwriter_headers)
    assert res.status_code >= 400, "re-open must be refused while a second row is in flight"
    # The property still carries exactly one contributing valuation.
    assert reload_property(prop["id"])["dwelling_replacement_cost_cents"] == 200_000_000


def test_foreign_valuation_method_is_refused_with_method_invalid(api, underwriter_headers):
    """PRD 3.1: "An ordinary approval requires the row's `valuation_method` to be
    `SITE_MEASURED`; a row carrying any other method is refused with
    `ERR_APPRAISAL_METHOD_INVALID`."

    Design: Corner/errors/every_error_code_is_reachable_from_a_declared_endpoint
    """
    prop = setup_underwritable_property(zone_code="ZF4", agency_code="AG54")
    desktop = create_appraisal(prop["id"], valuation_method="DESKTOP_ESTIMATE",
                               dwelling_cost_cents=210_000_000)
    get_success_data(api_client.review_appraisal(desktop["id"], underwriter_headers))

    res = api_client.approve_appraisal(desktop["id"], underwriter_headers)
    validate_error(res, "ERR_APPRAISAL_METHOD_INVALID", expected_status=422)
    # A desktop estimate cannot be approved outright; supersede is its exit.
    validate_success(api_client.supersede_appraisal(desktop["id"], underwriter_headers), 200)


def test_valuation_provision_requires_a_one_point_two_five_baseline(api, underwriter_headers):
    """PRD 3.1: "The second admissible path is the valuation provision: a reviewed row
    may be approved as a provision only when at least one prior appraisal on the same
    property already holds `APPROVED` or `SUPERSEDED` status and the highest such
    prior `dwelling_cost_cents` is at least 1.25 times the provision row's own
    `dwelling_cost_cents`."
    PRD 3.1: "When no such baseline exists, or the baseline falls below that multiple,
    the provision is refused with `ERR_APPRAISAL_PROVISION_BASELINE`."

    Design: Corner/errors/every_error_code_is_reachable_from_a_declared_endpoint
    """
    prop = setup_underwritable_property(zone_code="ZF5", agency_code="AG55")

    # Baseline 200000000 against a provision row of 150000000 is only 1.33x — admissible.
    good = create_appraisal(prop["id"], dwelling_cost_cents=150_000_000)
    get_success_data(api_client.review_appraisal(good["id"], underwriter_headers))
    provisioned = validate_success(
        api_client.provision_appraisal(good["id"], underwriter_headers), 200)
    assert provisioned["status"] == "APPROVED"
    assert provisioned["percent_complete"] == 1.00

    # A second provision row of 190000000 against the same 200000000 baseline is only
    # 1.05x — below the 1.25 multiple, so it is refused.
    thin = create_appraisal(prop["id"], dwelling_cost_cents=190_000_000)
    get_success_data(api_client.review_appraisal(thin["id"], underwriter_headers))
    res = api_client.provision_appraisal(thin["id"], underwriter_headers)
    validate_error(res, "ERR_APPRAISAL_PROVISION_BASELINE", expected_status=422)


def test_gated_property_does_not_contribute_a_reviewed_appraisal(
        api, underwriter_headers):
    """PRD 3.1: "The contributing set is every appraisal of the property whose `status`
    is `APPROVED` or `SUPERSEDED`; rows in `PENDING_REVIEW`, `REVIEWED`, `REJECTED` or
    `WITHDRAWN` contribute nothing at all."

    Design: Corner/calculations/replacement_cost_valuation_excludes_unapproved_appraisals
    """
    zone, agency, prop, second = setup_property_with_reviewed_second_appraisal(
        zone_code="ZREV", agency_code="AGREV", second_cost_cents=90_000_000)
    assert prop["dwelling_replacement_cost_cents"] == 200_000_000

    # Rejecting the reviewed row changes nothing.
    validate_success(api_client.reject_appraisal(second["id"], "superseded by field visit",
                                                 underwriter_headers), 200)
    assert reload_property(prop["id"])["dwelling_replacement_cost_cents"] == 200_000_000


def test_valuations_accumulate_rather_than_replace(api, underwriter_headers):
    """PRD 3.1: "For each contributing row the server multiplies the row's
    `dwelling_cost_cents` by that row's `percent_complete`, rounds the product half up
    to the cent, and adds the rounded products together to give
    `dwelling_replacement_cost_cents`"

    Design: Corner/calculations/replacement_cost_valuation_excludes_unapproved_appraisals
    """
    zone, agency, prop, second = setup_property_with_reviewed_second_appraisal(
        zone_code="ZREV2", agency_code="AGREV2", second_cost_cents=90_000_000)

    approved = get_success_data(api_client.approve_appraisal(
        second["id"], underwriter_headers))
    assert approved["status"] == "APPROVED"
    # A second contributing row is summed, not substituted for the first.
    assert reload_property(prop["id"])["dwelling_replacement_cost_cents"] == 290_000_000
    # The row is gone from the reviewed filter once it is approved.
    listed = api_client.list_appraisals(prop["id"], underwriter_headers,
                                        params={"status": "REVIEWED"})
    assert listed.json()["data"] == []


def test_base_appraisal_lapse_closes_the_gate_but_keeps_the_exposure(
        api, underwriter_headers, platform_admin_headers):
    """PRD 3.1: "once the logical clock passes 24 months from the latest approved
    site-measured appraisal, and no approved appraisal remains within currency, the
    property reverts to `PENDING_APPRAISAL` — but the dwelling component continues to
    be computed from the stale approved rows rather than being zeroed, so the exposure
    figure survives the lapse even as the gate closes."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_restores_required_coverage_after_a_lapse
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code="ZLAPSE2", agency_code="AGLAPSE2")
    assert prop["base_posture"] == "UNDERWRITABLE"

    reset_clock("2028-10-01T00:00:00Z")
    after = reload_property(prop["id"])
    assert after["base_posture"] == "PENDING_APPRAISAL"
    assert after["posture"] == "WRITE_FROZEN"
    # The exposure figure survives the lapse.
    assert after["dwelling_replacement_cost_cents"] == 200_000_000


def test_property_create_rejects_a_client_supplied_percent_complete(
        api, underwriter_headers):
    """PRD 3.1: "A new row is born in `PENDING_REVIEW` with `percent_complete` at 0.00,
    and nothing about the property's valuation moves yet."

    Design: Corner/entities/appraisal_percent_complete_is_computed_on_create_extra_field_ignored
    """
    prop = setup_underwritable_property(zone_code="ZF6", agency_code="AG56")
    payload = {
        "appraiser_name": "Corner Valuation",
        "valuation_method": "SITE_MEASURED",
        "appraised_on": "2026-08-15T00:00:00Z",
        "dwelling_cost_cents": 200_000_000,
        "contents_cost_cents": 0,
        "valuation_confidence_pct": 95.0,
        "percent_complete": 1.00,
    }
    row = validate_success(
        api_client.create_appraisal(prop["id"], payload, underwriter_headers), 201)
    assert row["status"] == "PENDING_REVIEW"
    assert row["percent_complete"] == 0.00
    assert reload_property(prop["id"])["dwelling_replacement_cost_cents"] == 200_000_000