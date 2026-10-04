"""The ordered underwriting gate, property/zone intake and the OCC guard on writes."""
import pytest

from test_helpers import (
    api_client,
    create_agency,
    create_enrollment,
    create_property,
    create_zone,
    get_success_data,
    reload_property,
    reset_clock,
    run_posture_eval,
    setup_declined_property,
    setup_declined_property_pair,
    setup_frozen_and_unfrozen_siblings,
    setup_property_with_late_second_appraisal,
    setup_three_properties_two_appraised,
    setup_underwritable_property,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_zone_create_returns_every_derived_field_and_starts_unfrozen(
        api, platform_admin_headers):
    """PRD 2.10: "When the portfolio holds fewer than two such enrollments the ratio is
    pinned to 0.0 and the band to `NORMAL`, even though a single active enrollment is
    by construction the entire book."
    PRD 3.4: "`freeze_active` defaults to false and is re-derived from the concentration
    band, being true only while the band is `CRITICAL`."

    Design: Corner/entities/risk_zone_create_returns_every_derived_field_and_starts_unfrozen
    """
    reset_clock()
    zone = validate_success(api_client.create_risk_zone({
        "zone_code": "ZC9", "state_code": "CA",
        "wildland_urban_interface_band": "WITHIN_WUI",
        "sustained_wind_mph": 50, "mitigation_band_multiplier": 1.0,
        "mitigated_loss_multiplier": 1.0, "exposure_band": "EXTREME",
    }, platform_admin_headers), 201)
    assert zone["zone_code"] == "ZC9"
    assert zone["exposure_band"] == "EXTREME"
    assert zone["concentration_ratio_pct"] == 0.0
    assert zone["concentration_band"] == "NORMAL"
    assert zone["freeze_active"] is False
    assert zone["state_event"] == "NONE"
    assert isinstance(zone["version"], int)
    assert zone["id"] and zone["created_at"] and zone["updated_at"]


def test_zone_create_rejects_an_out_of_enum_wui_band(api, platform_admin_headers):
    """PRD 3.4: "its `wildland_urban_interface_band` — `WITHIN_WUI`, `ADJACENT_WUI` or
    `OUTSIDE_WUI`"
    PRD 2.11: "an enumerated value that falls outside its declared set, or a numeric
    value that violates a declared bound is refused with `ERR_INVALID_REQUEST` before
    any business rule is consulted"

    Design: Corner/entities/property_create_with_an_out_of_enum_wui_band_returns_invalid_request
    """
    reset_clock()
    res = api_client.create_risk_zone({
        "zone_code": "ZC7", "state_code": "CA",
        "wildland_urban_interface_band": "NEAR_WUI",
        "sustained_wind_mph": 50, "mitigation_band_multiplier": 1.0,
        "mitigated_loss_multiplier": 1.0, "exposure_band": "EXTREME",
    }, platform_admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    listed = get_success_data(api_client.list_risk_zones(
        platform_admin_headers, params={"zone_code": "ZC7"}))
    assert listed == []

    # The same zone with a declared band is accepted.
    validate_success(api_client.create_risk_zone({
        "zone_code": "ZC7", "state_code": "CA",
        "wildland_urban_interface_band": "OUTSIDE_WUI",
        "sustained_wind_mph": 50, "mitigation_band_multiplier": 1.0,
        "mitigated_loss_multiplier": 1.0, "exposure_band": "EXTREME",
    }, platform_admin_headers), 201)


def test_property_create_without_a_risk_zone_id_is_refused(api, underwriter_headers,
                                                           platform_admin_headers):
    """PRD 3.5: "A dwelling is registered against a zone and a producing agency by
    supplying the `risk_zone_id`, the `agency_id`, the `address_line`, and an optional
    `grid_risk_block` defaulting to `UNGROUPED`."
    PRD 2.11: "a required input field that is absent, an enumerated value that falls
    outside its declared set, or a numeric value that violates a declared bound is
    refused with `ERR_INVALID_REQUEST` before any business rule is consulted"

    Design: Corner/entities/property_create_missing_risk_zone_id_returns_invalid_request
    """
    reset_clock()
    create_zone(zone_code="ZC9M")
    agency = create_agency(agency_code="AGC9M")

    res = api_client.create_property(
        {"agency_id": agency["id"], "address_line": "5 Corner Rd"}, underwriter_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    listed = get_success_data(api_client.list_properties(
        underwriter_headers, params={"agency_id": agency["id"]}))
    assert listed == []


def test_property_create_omitting_the_grid_block_defaults_to_ungrouped(
        api, underwriter_headers):
    """PRD 3.5: "an optional `grid_risk_block` defaulting to `UNGROUPED`"
    PRD 3.5: "A newly registered property is born `PENDING_APPRAISAL` and
    `WRITE_FROZEN`"

    Design: Corner/entities/property_create_omitting_grid_risk_block_defaults_to_ungrouped
    """
    reset_clock()
    zone = create_zone(zone_code="ZC9G")
    agency = create_agency(agency_code="AGC9G")

    prop = validate_success(api_client.create_property(
        {"risk_zone_id": zone["id"], "agency_id": agency["id"],
         "address_line": "6 Corner Rd"}, underwriter_headers), 201)
    assert prop["grid_risk_block"] == "UNGROUPED"
    assert prop["base_posture"] == "PENDING_APPRAISAL"
    assert prop["posture"] == "WRITE_FROZEN"


def test_guarantee_ratio_failure_declines_the_property(api, underwriter_headers):
    """PRD 3.5: "When the latest approved appraisal fails that ratio the property is
    driven to `DECLINED` instead, its posture set to `WRITE_FROZEN`, and every `DRAFT`
    or `SUBMITTED` enrollment of that property moved to `DECLINED`"

    Design: Corner/state_machines/posture_eval_from_declined_property_returns_invalid_state
    """
    zone, agency, prop = setup_declined_property(zone_code="ZDEC", agency_code="AGDEC")
    assert prop["base_posture"] == "DECLINED"
    assert prop["posture"] == "WRITE_FROZEN"


def test_declined_property_is_terminal_for_the_gate(api, underwriter_headers):
    """PRD 3.5: "A `DECLINED` property is terminal unless an underwriter reopens it at
    the branch of record."
    
    Design: Corner/state_machines/posture_eval_from_declined_property_returns_invalid_state
    """
    zone, agency, prop = setup_declined_property(zone_code="ZDEC2", agency_code="AGDEC2")
    assert prop["base_posture"] == "DECLINED"

    res = api_client.posture_eval(prop["id"], prop["version"], underwriter_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = reload_property(prop["id"])
    assert after["base_posture"] == "DECLINED"
    assert after["version"] == prop["version"]


def test_reopen_is_gated_on_the_branch_capital_check(api, underwriter_headers):
    """PRD 3.5: "Reopening recomputes `base_posture` and `posture` from the property's
    current appraisal and mitigation state and increments its version, but it is
    refused when the branch the property would inherit has a `mitigated_loss_multiplier`
    above 1.00 — that is, when the zone baseline has not been capitalised — with
    `ERR_BRANCH_CAPITAL_INSUFFICIENT`."

    Design: Corner/cross_cutting_layers/bulk_free_batch_reopen_reports_partial_success_per_property
    """
    zone_ok, prop_ok, zone_thin, prop_thin = setup_declined_property_pair()
    assert prop_ok["base_posture"] == "DECLINED"
    assert prop_thin["base_posture"] == "DECLINED"

    validate_success(api_client.reopen_property(prop_ok["id"], underwriter_headers), 200)

    refused = api_client.reopen_property(prop_thin["id"], underwriter_headers)
    validate_error(refused, "ERR_BRANCH_CAPITAL_INSUFFICIENT", expected_status=422)

    # The successful reopen is not rolled back by the sibling's failure.
    assert reload_property(prop_ok["id"])["version"] > prop_ok["version"]


def test_frozen_property_outranks_coverage_below_required_on_attach(
        api, underwriter_headers):
    """PRD 2.11: "Business-safety gates follow — the write-frozen gate (priority 4,
    ahead of the zone-freeze gate at priority 5 and the referral-posture gate at
    priority 6), because a frozen property is a more fundamental refusal than a
    referred one."

    Design: Difficulty/priority_pair_validation_conflict/write_frozen_outranks_coverage_below_required_when_zone_is_below_population_minimum
    """
    zone, agency, frozen_prop, live_prop, live_enroll = setup_frozen_and_unfrozen_siblings(
        zone_code="ZJ1", agency_code="AG9")
    assert frozen_prop["posture"] == "WRITE_FROZEN"

    # An enrollment sitting against the frozen dwelling, with coverage far below
    # what its replacement cost would require.
    enroll = create_enrollment(frozen_prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=100_000_000)
    res = api_client.attach_enrollment(enroll["id"], frozen_prop["version"],
                                       underwriter_headers)
    validate_error(res, "ERR_WRITE_FROZEN", expected_status=409)
    body = res.json()
    assert body["data"]["error_id"] != "ERR_COVERAGE_BELOW_REQUIRED"


def test_the_same_deficient_coverage_on_an_unfrozen_property_is_flagged_as_coverage(
        api, underwriter_headers):
    """PRD 3.7: "The enrollment's `dwelling_coverage_cents` must be at least its
    `required_dwelling_coverage_cents` (`ERR_COVERAGE_BELOW_REQUIRED`)."
    PRD 3.7: "computes `required_dwelling_coverage_cents` as 1.5 times the current
    replacement cost"

    Design: Difficulty/priority_pair_validation_conflict/write_frozen_outranks_coverage_below_required_when_zone_is_below_population_minimum
    """
    zone, agency, dead, live, submitted = setup_frozen_and_unfrozen_siblings(
        zone_code="ZJ1B", agency_code="AG9B")
    assert live["posture"] != "WRITE_FROZEN"

    approved = validate_success(
        api_client.approve_enrollment(submitted["id"], underwriter_headers), 200)
    # The submitted enrollment was opened at 250000000 against a 200000000
    # replacement cost, so the required Coverage A is 300000000.
    assert approved["required_dwelling_coverage_cents"] == 300_000_000

    res = api_client.attach_enrollment(submitted["id"], live["version"], underwriter_headers)
    validate_error(res, "ERR_COVERAGE_BELOW_REQUIRED", expected_status=422)


def test_posture_eval_with_a_stale_property_version_is_refused(
        api, underwriter_headers):
    """PRD 2.8: "Re-running the ordered underwriting gate — `POST
    /hnw/properties/{id}/posture-eval` — carries the same `expected_property_version`
    guard and rejects a stale view with the same `ERR_STALE_VERSION` at HTTP 412"

    Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_property_version_on_posture_eval_returns_412
    """
    zone, agency, prop, stale_version, second = setup_property_with_late_second_appraisal(
        zone_code="ZOCC", agency_code="AGOCC")

    res = api_client.posture_eval(prop["id"], stale_version, underwriter_headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    assert prop["dwelling_replacement_cost_cents"] == 250_000_000
    # A fresh version is accepted.
    validate_success(api_client.posture_eval(
        prop["id"], reload_property(prop["id"])["version"], underwriter_headers), 200)


def test_property_listing_composes_filters_with_pagination(api, underwriter_headers):
    """PRD 2.3: "`limit` caps the number of records returned, defaults to 10 when
    omitted, and must fall between a minimum of 1 and a maximum of 100. `offset` skips
    that many records and defaults to 0."
    PRD 2.3: "Responses to list operations carry the four pagination fields — `limit`,
    `offset`, `total_count` and `has_more` — inside the `meta` object"

    Design: Corner/cross_cutting_layers/pagination_with_filtering_and_sort_interact_correctly
    """
    zone, agency, props = setup_three_properties_two_appraised(
        zone_code="ZPAGE", agency_code="AGPAGE")

    data, meta = validate_paginated(api_client.list_properties(underwriter_headers))
    assert meta["total_count"] == 3
    assert meta["limit"] == 10

    page, meta = validate_paginated(api_client.list_properties(
        underwriter_headers, params={"risk_zone_id": zone["id"], "limit": 1, "offset": 0}))
    assert len(page) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    # The posture filter narrows the candidate set before the page is cut.
    pending, meta = validate_paginated(api_client.list_properties(
        underwriter_headers, params={"base_posture": "PENDING_APPRAISAL"}))
    assert meta["total_count"] == 1
    assert pending[0]["base_posture"] == "PENDING_APPRAISAL"