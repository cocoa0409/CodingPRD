"""Remaining edges: enrollments listing, invalid transitions, endorsement gating and
the fixed startup instant of the logical clock."""
from test_helpers import (
    add_approved_appraisal,
    api_client,
    attach_enrollment,
    create_agency,
    create_appraisal_document,
    create_enrollment,
    create_property,
    create_zone,
    get_success_data,
    make_agency_producer_headers,
    reload_property,
    run_posture_eval,
    setup_approved_enrollment,
    setup_draft_enrollment_on_write_eligible,
    setup_submitted_enrollment,
    setup_three_draft_enrollments_two_zones,
    submit_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_START


def _norm(ts):
    """Normalise an ISO 8601 instant to the three-fractional-digit form PRD 2.2/2.6
    fix on the wire, so a value that omits milliseconds compares equal."""
    assert isinstance(ts, str) and ts.endswith("Z"), ts
    head, _, _frac = ts[:-1].partition(".")
    return head + ".000Z"


def test_enrollments_list_filters_by_zone_and_paginates(api, underwriter_headers):
    """PRD 2.10: "The active population is every enrollment whose `status` is
    `SUBMITTED`, `REFERRED`, `APPROVED` or `ATTACHED`"
    PRD 2.3: "`limit` caps the number of records returned, defaults to 10 when omitted"
    PRD 2.3: "Responses to list operations carry the four pagination fields"

    Design: Corner/entities/enrollments_list_filters_by_zone_and_paginates
    """
    zone1, zone2, agency, enrolls = setup_three_draft_enrollments_two_zones(
        zone1_code="ZC9L", zone2_code="ZC8L", agency_code="AGC9L")

    data, meta = validate_paginated(api_client.list_enrollments(
        underwriter_headers, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail, tail_meta = validate_paginated(api_client.list_enrollments(
        underwriter_headers, params={"limit": 2, "offset": 2}))
    assert len(tail) == 1
    assert tail_meta["has_more"] is False

    on_zone1, z1_meta = validate_paginated(api_client.list_enrollments(
        underwriter_headers, params={"risk_zone_id": zone1["id"]}))
    assert z1_meta["total_count"] == 2

    on_zone2, z2_meta = validate_paginated(api_client.list_enrollments(
        underwriter_headers, params={"risk_zone_id": zone2["id"]}))
    assert z2_meta["total_count"] == 1


def test_attaching_a_draft_enrollment_is_a_state_rejection(api, underwriter_headers):
    """PRD 3.5: "An enrollment is opened by a producer against a dwelling by naming the
    producing `agency_id` and the desired `dwelling_coverage_cents`"
    
    Design: Corner/state_machines/attach_from_draft_enrollment_returns_invalid_state
    """
    zone, agency, prop, enroll = setup_draft_enrollment_on_write_eligible(
        zone_code="ZADRAFT", agency_code="AGADRAFT", coverage_cents=300_000_000)
    assert enroll["status"] == "DRAFT"

    res = api_client.attach_enrollment(enroll["id"], prop["version"], underwriter_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    still = get_success_data(api_client.get_enrollment(enroll["id"], underwriter_headers))
    assert still["status"] == "DRAFT"
    assert still["bound_at"] is None


def test_a_second_claim_review_is_refused(api, underwriter_headers, claims_adjuster_headers):
    """PRD 3.8: "Review is the adjuster's first act and it is refused with
    `ERR_ENROLLMENT_NOT_BOUND` unless the parent enrollment is `ATTACHED`"
    
    Design: Corner/state_machines/claim_second_review_attempt_is_rejected
    """
    from test_helpers import setup_bound_claim

    zone, agency, prop, enroll, claim = setup_bound_claim(
        zone_code="ZCLMR", agency_code="AGCLMR",
        cause_of_loss="HALL", reported_indemnity_cents=50_000_000)
    first = validate_success(
        api_client.review_claim(claim["id"], claims_adjuster_headers), 200)
    assert first["status"] == "UNDER_REVIEW"
    version_after_first = first["version"]

    res = api_client.review_claim(claim["id"], claims_adjuster_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    still = get_success_data(api_client.list_enrollment_claims(
        enroll["id"], claims_adjuster_headers))[0]
    assert still["version"] == version_after_first


def test_a_moved_valuation_fingerprint_blocks_the_attach(api, underwriter_headers):
    """PRD 3.7: "The enrollment's `valuation_fingerprint` must still equal the
    property's current approved dwelling, contents and scheduled values
    (`ERR_VALUATION_STALE`) — a valuation that moved after approval invalidates the
    bind."
    PRD 3.2: "Approval recomputes the item's `appraisal_currency_months` from the clock
    and then recomputes both `scheduled_valuation_cents` and `total_insured_value_cents`
    on the property."

    Design: Corner/validations/stale_valuation_fingerprint_blocks_attach
    """
    from test_helpers import setup_enrollment_with_extra_scheduled_item

    zone, agency, prop, enroll, item = setup_enrollment_with_extra_scheduled_item(
        zone_code="ZFING", agency_code="AGFING")
    assert enroll["status"] == "APPROVED"

    res = api_client.attach_enrollment(enroll["id"], prop["version"], underwriter_headers)
    validate_error(res, "ERR_VALUATION_STALE", expected_status=422)
    # The failure is the fingerprint, not a stale version.
    assert res.json()["data"]["error_id"] != "ERR_STALE_VERSION"

    still = get_success_data(api_client.get_enrollment(enroll["id"], underwriter_headers))
    assert still["status"] == "APPROVED"
    assert still["bound_at"] is None


def test_an_endorsement_conflicting_with_the_snapshot_is_refused(
        api, underwriter_headers):
    """PRD 3.7: "the endorsement is refused with `ERR_INCOMPATIBLE_ENDORSEMENT` when its
    required provision conflicts with the enrollment's snapshotted
    `replacement_provision`"
    PRD 3.7: "The result records the `endorsement_id`, the `enrollment_id` it was
    attached to, and a `void_on_recall` flag carrying that understanding."

    Design: Corner/endpoints/endorsement_with_a_conflicting_provision_is_refused
    """
    zone, agency, prop, enroll = setup_approved_enrollment(
        zone_code="ZENDOR", agency_code="AGENDOR", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band="CLEARED")
    assert enroll["replacement_provision"] == "EXTENDED"

    refused = api_client.create_endorsement(
        enroll["id"],
        {"endorsement_code": "SUPERIOR_PROTECTION", "required_provision": "GUARANTEED"},
        underwriter_headers)
    validate_error(refused, "ERR_INCOMPATIBLE_ENDORSEMENT", expected_status=422)

    # A compatible endorsement is accepted and records its recall-void flag.
    accepted = validate_success(api_client.create_endorsement(
        enroll["id"],
        {"endorsement_code": "EXTENDED_COVER", "required_provision": "EXTENDED"},
        underwriter_headers), 201)
    assert accepted["enrollment_id"] == enroll["id"]
    assert accepted["void_on_recall"] is True


def test_the_logical_clock_defaults_to_its_fixed_startup_instant(
        api, underwriter_headers):
    """PRD 2.4: "At server startup the clock is pinned to 2026-09-01T00:00:00Z."
    PRD 2.4: "The clock never falls back to real time"

    Design: Corner/cross_cutting_layers/logical_clock_defaults_to_the_fixed_startup_instant
    """
    zone = create_zone(zone_code="ZCLK")
    agency = create_agency(agency_code="AGCLK")
    prop = create_property(zone["id"], agency["id"])
    # The clock is pinned to 2026-09-01T00:00:00Z at every server boot, so a
    # dwelling registered with no clock call carries that exact instant.  No
    # fixture in this test advances the clock, so this also proves the pin
    # survives a fresh server start (the harness reboots per test).
    added = validate_success(
        api_client.create_appraisal(prop["id"], {
            "appraiser_name": "Corner Valuation",
            "valuation_method": "SITE_MEASURED",
            "appraised_on": CLOCK_START,
            "dwelling_cost_cents": 200_000_000,
            "contents_cost_cents": 0,
            "valuation_confidence_pct": 95.0,
        }, underwriter_headers), 201)
    assert _norm(added["created_at"]) == "2026-09-01T00:00:00.000Z"

    doc = create_appraisal_document(prop["id"], item_class="WINE",
                                    appraiser_name="Corner Cellars",
                                    appraisal_date="2024-09-01T00:00:00Z",
                                    appraised_value_cents=30_000_000)
    # An appraisal_date 24 months before the pinned instant derives EXPIRED without any
    # clock call, so the same fixture yields the same band on any run date.
    assert doc["currency_months"] == 24
    assert doc["currency_status"] == "EXPIRED"
    # PRD 3.2: expires_on is the appraisal date advanced by 24 months and then
    # rolled forward to the first day of the following month.
    assert _norm(doc["expires_on"]) == "2026-10-01T00:00:00.000Z"