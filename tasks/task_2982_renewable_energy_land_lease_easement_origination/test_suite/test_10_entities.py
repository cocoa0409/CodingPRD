"""Entity-level claims: creation, retrieval, listing, defaults and integrity gates."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_LANDOWNER_NOT_FOUND,
    ERR_LEASE_AGREEMENT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_acres_equals,
    assert_ascending_by_created_at,
    assert_cents_equals,
    assert_common_fields,
    assert_instant_equals,
    assert_null,
    assert_page_meta,
    assert_score_equals,
    assert_status,
    assert_version_is,
)
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.factories import OMIT, landowner_payload, parcel_payload
from test_helpers.fixtures import (
    client,
    parcels_page,
    publish_setback_rule,
    read_consent,
    read_landowner,
    read_parcel,
    register_landowner,
    register_parcel,
    request_consent,
)
from test_helpers.test_users import LAND_AGENT, PORTFOLIO_MANAGER

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"


def _sandhill() -> str:
    """The one owner of record every case in this file hangs off."""
    return register_landowner(**SANDHILL)["id"]


def _clean_parcel(landowner_id: str, apn: str = "R-9001-001", gross_acres: float = 200.00):
    """A tract in a county carrying no published ordinance at all."""
    return register_parcel(
        landowner_id,
        apn=apn,
        county_fips=CLEAN_COUNTY,
        gross_acres=gross_acres,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )


def test_a_newly_registered_owner_opens_in_prospect_with_a_zero_balance():
    """
    The very first write to an empty store returns an owner whose posture and
    ledger balance are already computed, before any parcel, option or payment
    exists to compute them from.

    PRD: "A newly registered landowner starts in `PROSPECT` with
    `total_paid_cents` of 0."

    Design: Corner/entities/create_landowner_returns_prospect_posture_and_zero_ledger
    """
    response = client().create_landowner(landowner_payload(**SANDHILL), LAND_AGENT)

    landowner = validate_success(response, 201)

    assert landowner["legal_name"] == "Sandhill Prairie LLC"
    assert landowner["entity_type"] == "LLC"
    assert landowner["mailing_state"] == "TX"
    assert landowner["contact_email"] == "ops@sandhill.example"
    assert landowner["w9_on_file"] is True
    assert landowner["payment_hold"] is False
    assert_status(landowner, "PROSPECT", "landowner")
    assert_cents_equals(landowner["total_paid_cents"], 0, "total_paid_cents")


def test_the_registration_response_already_carries_the_common_field_set():
    """
    Registration is a mutation of nothing, so the row lands at the bottom of the
    version sequence with both of its timestamps stamped from the logical clock.

    PRD: "`created_at` is the ISO 8601 UTC instant at which the row was inserted,
    rendered with exactly three fractional digits; `updated_at` is the same format
    and is refreshed on every mutation of the row, including mutations the row's
    owner did not request but a cascade performed; and `version` is an integer that
    starts at 1 on creation and increases by exactly 1 on every mutation, again
    including cascade-driven mutations."

    Design: Corner/entities/create_landowner_returns_prospect_posture_and_zero_ledger
    """
    response = client().create_landowner(landowner_payload(**SANDHILL), LAND_AGENT)

    landowner = validate_success(response, 201)

    assert_common_fields(landowner, "landowner")
    assert_version_is(landowner, 1, "landowner")
    # PRD 2.6 enumerates the instants stamped from the logical clock and
    # deliberately excludes created_at/updated_at, so their clock source is not
    # pinned; only their format and the version floor are asserted here.
    assert read_landowner(landowner["id"])["id"] == landowner["id"]


def test_the_single_parcel_read_returns_the_whole_derived_picture():
    """
    The flat topology gives the reader one resource and expects the server to have
    filled in everything downstream of the five inputs: all five acreage terms,
    both screening outputs and the persisted variant.

    PRD: "Reads of a single parcel return the whole derived picture — the acreage
    breakdown, the score, the tier and the three counters — and the parcel
    collection may be filtered down by owner, county, tier or status."

    Design: Corner/entities/get_parcel_returns_full_derived_acreage_and_screening_breakdown
    """
    landowner_id = _sandhill()
    created = _clean_parcel(landowner_id)

    response = client().get_parcel(created["id"], PORTFOLIO_MANAGER)

    parcel = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert_acres_equals(parcel["slope_excluded_acres"], 0.00, "slope_excluded_acres")
    assert_acres_equals(parcel["raw_setback_acres"], 0.00, "raw_setback_acres")
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 0.00, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["buildable_acres"], 200.00, "buildable_acres")
    assert_score_equals(parcel["screening_score"], 82.15, "screening_score")
    assert parcel["screening_tier"] == "PRIORITY", parcel["screening_tier"]
    assert parcel["screen_mode"] == "DESKTOP", parcel["screen_mode"]
    assert_status(parcel, "QUALIFIED", "parcel")


def test_the_retrieved_parcel_conserves_the_deeded_acreage():
    """
    Nothing has been excluded and nothing encumbered, so the identity holds in its
    degenerate form on the retrieved row rather than only on the creation response.

    PRD: "Whenever `buildable_acres` comes out greater than zero, the three figures
    conserve the deed exactly: `gross_acres` equals `buildable_acres` plus
    `slope_excluded_acres` plus `setback_encumbered_acres`."

    Design: Corner/entities/get_parcel_returns_full_derived_acreage_and_screening_breakdown
    """
    landowner_id = _sandhill()
    created = _clean_parcel(landowner_id)

    parcel = read_parcel(created["id"], PORTFOLIO_MANAGER)

    assert_acres_equals(parcel["gross_acres"], 200.00, "gross_acres")
    total = (
        parcel["buildable_acres"]
        + parcel["slope_excluded_acres"]
        + parcel["setback_encumbered_acres"]
    )
    assert_acres_equals(total, 200.00, "conserved deeded acreage")


def test_the_filtered_parcel_page_reports_the_prepagination_total():
    """
    Three parcels are asked for two at a time. The window returns exactly two rows
    while the envelope reports the full count matching the filter and warns that
    more remain.

    PRD: "For list responses the `meta` object additionally carries `limit`,
    `offset`, `total_count` (the number of records matching the filters before
    pagination) and `has_more` (true when records remain beyond the current page)."

    Design: Corner/entities/list_parcels_filtered_by_landowner_paginates_with_total_count_and_has_more
    """
    landowner_id = _sandhill()
    _clean_parcel(landowner_id, "R-9001-001", 200.00)
    _clean_parcel(landowner_id, "R-9001-002", 100.00)
    _clean_parcel(landowner_id, "R-9001-003", 60.00)

    rows, meta = parcels_page(LAND_AGENT, landowner_id=landowner_id, limit=2, offset=0)

    assert_page_meta(meta, total_count=3, has_more=True, limit=2, offset=0)
    assert len(rows) == 2, f"expected two rows on the page, got {len(rows)}"


def test_the_parcel_pages_run_oldest_first_and_end_with_has_more_false():
    """
    The two pages together spell out the insertion order, not the identifier order,
    and the last page closes the collection.

    PRD: "Collections are ordered by `created_at` ascending — oldest record first —
    and never by `id`."

    Design: Corner/entities/list_parcels_filtered_by_landowner_paginates_with_total_count_and_has_more
    """
    landowner_id = _sandhill()
    _clean_parcel(landowner_id, "R-9001-001", 200.00)
    _clean_parcel(landowner_id, "R-9001-002", 100.00)
    _clean_parcel(landowner_id, "R-9001-003", 60.00)

    first_page, _first_meta = parcels_page(
        LAND_AGENT, landowner_id=landowner_id, limit=2, offset=0
    )
    second_page, second_meta = parcels_page(
        LAND_AGENT, landowner_id=landowner_id, limit=2, offset=2
    )

    assert [row["apn"] for row in first_page] == ["R-9001-001", "R-9001-002"]
    assert_ascending_by_created_at(first_page, "first page")
    assert [row["apn"] for row in second_page] == ["R-9001-003"]
    assert_page_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)


def test_reading_an_unknown_lease_reports_the_lease_not_found_code():
    """
    The deepest entity in the chain is asked for by a well-formed identifier that
    names nothing. The answer is an error envelope carrying the code, not an empty
    success.

    PRD: "Leases are readable individually and as a collection filterable by
    originating option, parcel, owner, rent status or recording status; a path
    identifier naming no lease is answered with `ERR_LEASE_AGREEMENT_NOT_FOUND`
    (404)."

    Design: Corner/entities/get_lease_with_unknown_id_returns_lease_agreement_not_found
    """
    response = client().get_lease(UNKNOWN_UUID, PORTFOLIO_MANAGER)

    error = validate_error(response, ERR_LEASE_AGREEMENT_NOT_FOUND, 404)

    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"error message should be a non-empty string, got {error['message']!r}"
    )


def test_a_parcel_body_without_gross_acres_is_refused_by_the_shape_gate():
    """
    The deeded acreage every derived figure hangs off is simply absent. The owner it
    names does exist, so the existence rung passes and the shape rung is the one
    that answers — and nothing is screened, defaulted or written.

    PRD: "The ladder runs authentication, then authorisation, then existence, then
    request shape, then optimistic concurrency, then instrument expiry, then generic
    state admissibility, then title and security compliance, then deal-structure
    constraints, then temporal conflicts, and finally money."

    Design: Corner/entities/create_parcel_missing_required_gross_acres_returns_invalid_request
    """
    landowner_id = _sandhill()

    response = client().create_parcel(
        parcel_payload(
            landowner_id,
            apn="R-9001-001",
            county_fips=CLEAN_COUNTY,
            gross_acres=OMIT,
            interconnection_distance_km=3.50,
            resource_capacity_factor=0.38,
            slope_pct=4.0,
            title_condition_grade="B",
            zoning_code="AG2",
        ),
        LAND_AGENT,
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    _rows, meta = parcels_page(LAND_AGENT, landowner_id=landowner_id)
    assert_page_meta(meta, total_count=0)
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")


def _encumbered_sandhill_parcel():
    """A two-hundred-acre tract behind one waivable five-percent ordinance."""
    landowner_id = _sandhill()
    rule = publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=150,
        encumbrance_rate_per_acre=0.0500,
        consent_waivable=True,
    )
    parcel = _clean_parcel(landowner_id)
    assert_acres_equals(parcel["raw_setback_acres"], 10.00, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 190.00, "buildable_acres")
    return landowner_id, parcel["id"], rule["id"]


def test_an_omitted_consent_window_defaults_to_sixty_days():
    """
    The absent input is only observable through the derived expiry instant: sixty
    days on from the request lands at the end of September.

    PRD: "That window defaults to 60 days when omitted and must be at least 1 and at
    most 365 — a year is the outside limit."

    Design: Corner/entities/create_neighbor_consent_without_expiry_days_applies_sixty_day_default
    """
    _landowner_id, parcel_id, rule_id = _encumbered_sandhill_parcel()

    consent = request_consent(
        parcel_id, rule_id, neighbor_name="H. Vaughn", consent_expiry_days=OMIT
    )

    assert consent["consent_expiry_days"] == 60, consent["consent_expiry_days"]
    assert_instant_equals(
        consent["requested_at"], "2026-08-01T00:00:00Z", "requested_at"
    )
    assert_instant_equals(
        consent["consent_expiry_at"], "2026-09-30T00:00:00Z", "consent_expiry_at"
    )
    assert_version_is(read_consent(consent["id"]), 1, "consent")


def test_a_merely_requested_consent_releases_no_acreage_at_all():
    """
    The request opens unsigned, so its own release term is nil and the parcel's
    encumbrance is exactly what the ordinance imposed.

    PRD: "Consents in `REQUESTED`, `REVOKED` or `EXPIRED`, and consents whose rule is
    not consent-waivable, release nothing and carry `released_acres` of `0.00`."

    Design: Corner/entities/create_neighbor_consent_without_expiry_days_applies_sixty_day_default
    """
    _landowner_id, parcel_id, rule_id = _encumbered_sandhill_parcel()

    response = client().create_neighbor_consent(
        {
            "parcel_id": parcel_id,
            "setback_rule_id": rule_id,
            "neighbor_name": "H. Vaughn",
        },
        LAND_AGENT,
    )

    consent = validate_success(response, 201)
    assert_status(consent, "REQUESTED", "consent")
    assert_acres_equals(consent["released_acres"], 0.00, "released_acres")
    assert_null(consent["granted_at"], "granted_at")
    assert_null(consent["revoked_at"], "revoked_at")
    parcel = read_parcel(parcel_id)
    assert_acres_equals(parcel["raw_setback_acres"], 10.00, "raw_setback_acres")
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(parcel["buildable_acres"], 190.00, "buildable_acres")


def test_the_screen_mode_and_the_three_counters_are_written_by_the_server():
    """
    None of these four fields is a client input. The variant is persisted as the
    desktop one by the intake cascade itself, and the title workflow's three
    counters open at nil because no defect has been raised.

    PRD: "The server derives the acreage figures, then computes the screening score
    under the desktop variant, persisting `screen_mode` as `DESKTOP`, then
    re-evaluates qualification, then resynchronises the landowner's posture."

    Design: Corner/entities/parcel_screening_and_recount_fields_are_system_owned_at_creation
    """
    landowner_id = _sandhill()

    response = client().create_parcel(
        parcel_payload(
            landowner_id,
            apn="R-9001-001",
            county_fips=CLEAN_COUNTY,
            gross_acres=200.00,
            interconnection_distance_km=3.50,
            resource_capacity_factor=0.38,
            slope_pct=4.0,
            title_condition_grade="B",
            zoning_code="AG2",
        ),
        LAND_AGENT,
    )

    parcel = validate_success(response, 201)
    assert parcel["screen_mode"] == "DESKTOP", parcel["screen_mode"]
    assert parcel["blocking_curative_open_count"] == 0
    assert parcel["waived_blocking_count"] == 0
    assert_cents_equals(parcel["curative_cost_cents"], 0, "curative_cost_cents")
    assert_version_is(parcel, 1, "parcel")


def test_the_intake_cascade_advances_both_the_parcel_and_its_owner_in_one_request():
    """
    The parcel does not linger in its screening default and the owner does not
    linger in theirs: one POST leaves the tract qualified and the owner engaged.

    PRD: "`PROSPECT → ENGAGED` fires once one of the owner's parcels enters
    `QUALIFIED`."

    Design: Corner/entities/parcel_screening_and_recount_fields_are_system_owned_at_creation
    """
    landowner_id = _sandhill()
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")

    parcel = _clean_parcel(landowner_id)

    assert_status(parcel, "QUALIFIED", "parcel")
    assert_acres_equals(parcel["buildable_acres"], 200.00, "buildable_acres")
    assert parcel["screening_tier"] == "PRIORITY", parcel["screening_tier"]
    assert_status(read_landowner(landowner_id), "ENGAGED", "landowner")


def test_a_slope_outside_its_declared_domain_is_refused_before_any_tier_is_read():
    """
    The value is a well-formed number, so the shape rung has nothing to say about
    it; the numeric-domain rung does, and no tier is selected for a slope that
    cannot exist.

    PRD: "The numeric domains that must hold are: `gross_acres` strictly greater
    than 0; `slope_pct` between 0 and 100 inclusive; `resource_capacity_factor`
    strictly greater than 0 and at most 1; `interconnection_distance_km` of 0 or
    more; every field ending in `_bps` between 0 and 10000 inclusive; every field
    ending in `_cents` of 0 or more; `option_term_days` of 1 or more;
    `extension_count_allowed` of 0 or more; `crew_count` between 1 and 3 inclusive;
    `buffer_m` of 0 or more; `total_length_m` strictly greater than 0;
    `period_year` of 1 or more; `production_mwh` of 0 or more; and
    `consent_expiry_days` of 1 or more."

    Design: Corner/entities/create_parcel_with_slope_pct_above_domain_returns_invalid_request
    """
    landowner_id = _sandhill()

    response = client().create_parcel(
        parcel_payload(
            landowner_id,
            apn="R-9001-001",
            county_fips=CLEAN_COUNTY,
            gross_acres=200.00,
            interconnection_distance_km=3.50,
            resource_capacity_factor=0.38,
            slope_pct=120.0,
            title_condition_grade="B",
            zoning_code="AG2",
        ),
        LAND_AGENT,
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    _rows, meta = parcels_page(LAND_AGENT, landowner_id=landowner_id)
    assert_page_meta(meta, total_count=0)


def test_a_body_landowner_id_naming_nobody_is_refused_by_the_existence_gate():
    """
    The only route from a parcel to its owner is the body foreign key, so
    referential integrity has to be enforced on the way in — against an empty store
    the create is refused outright.

    PRD: "When a parcel is registered or an option drafted and the referenced
    `landowner_id` names no existing landowner, the request is refused with
    `ERR_LANDOWNER_NOT_FOUND` (404), and the same code answers a read or an
    amendment aimed at an unknown owner."

    Design: Corner/entities/create_parcel_with_unknown_landowner_id_returns_landowner_not_found
    """
    response = client().create_parcel(
        parcel_payload(
            UNKNOWN_UUID,
            apn="R-9001-001",
            county_fips=CLEAN_COUNTY,
            gross_acres=200.00,
            interconnection_distance_km=3.50,
            resource_capacity_factor=0.38,
            slope_pct=4.0,
            title_condition_grade="B",
            zoning_code="AG2",
        ),
        LAND_AGENT,
    )

    validate_error(response, ERR_LANDOWNER_NOT_FOUND, 404)
    _rows, meta = parcels_page(LAND_AGENT)
    assert_page_meta(meta, total_count=0)
