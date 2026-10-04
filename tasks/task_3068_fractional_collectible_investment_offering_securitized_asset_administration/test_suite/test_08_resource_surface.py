"""The resource surface: creation defaults, listing, filtering, and lookups.

Each primary resource carries a standard identity block that the caller never
supplies, the five child record types are append-mostly and expose only `id` and
`created_at`, and an out-of-range or out-of-enum field is refused at the payload
layer rather than falling through to a lookup.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, is_iso8601_timestamp,
    make_investor_headers, TEST_USERS, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, file_asset_report, file_verified_authentication,
    file_verified_provenance, file_circular, get_artwork, get_offering,
    setup_authenticated_artwork, setup_filed_offering,
)
from test_helpers.assertions import assert_artist, assert_investor

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ── Creation writes the identity block the caller never supplies ─────────────

def test_artist_creation_returns_the_identity_block_and_the_defaulted_flag(api):
    """PRD 2.5: "The `id` is a server-minted UUID with no type prefix: the value is a
    bare universally unique identifier, never a string such as `artwork_…` or `off_…`."
    PRD 3.1: "a `catalogue_raisonne_published` flag that defaults to false."
    PRD 2.5: "The `version` is a system-managed integer that begins at its initial
    value".

    Design: Corner/entities/artist_create_returns_system_fields_and_the_stored_attribution
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.create_artist({
        "legal_name": "Ines Calderon", "attribution_status": "DISPUTED",
        "nationality_country_code": "ES",
    }, ISSUER)
    artist = validate_success(res, 201)

    assert is_valid_uuid(artist["id"])
    assert not artist["id"].startswith("artist_")
    assert artist["legal_name"] == "Ines Calderon"
    assert artist["attribution_status"] == "DISPUTED"
    assert artist["nationality_country_code"] == "ES"
    assert artist["catalogue_raisonne_published"] is False
    assert artist["version"] == 1
    assert is_iso8601_timestamp(artist["created_at"])
    assert is_iso8601_timestamp(artist["updated_at"])
    assert_artist(artist)


def test_artist_creation_envelope_carries_the_request_metadata(api):
    """PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`." PRD 2.2: "The `response_type` is either "object"
    for a single resource or "array" for a list of resources."

    Design: Corner/entities/artist_create_returns_system_fields_and_the_stored_attribution
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.create_artist({
        "legal_name": "Ines Calderon", "attribution_status": "DISPUTED",
        "nationality_country_code": "ES",
    }, ISSUER)
    validate_success(res, 201)
    body = res.json()

    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_investor_registration_starts_pending_and_restricted(api):
    """PRD 2.8: "The account is created with `suitability_status` `PENDING`,
    `suitability_verified_at` and `suitability_expires_at` both null,
    `lifetime_invested_cents` at zero, and `restriction_until` initialised to the row's
    `created_at`."

    Design: Corner/entities/investor_registration_starts_pending_with_restriction_until_at_created_at
    """
    set_clock("2026-09-01T00:00:00Z")
    investor = create_investor(email="runa@x.com", legal_name="Runa Halvorsen",
                               citizenship_country_code="NO",
                               residency_country_code="NO",
                               birth_date="1971-06-01")

    assert investor["suitability_status"] == "PENDING"
    assert investor["suitability_verified_at"] is None
    assert investor["suitability_expires_at"] is None
    assert investor["restriction_until"] == investor["created_at"]
    assert investor["lifetime_invested_cents"] == 0
    assert investor["is_accredited"] is False
    assert_investor(investor)


def test_investor_registration_round_trips_the_declared_figures(api):
    """PRD 2.8: "Registration is public and requires no credentials; it writes `email`
    as the account's login identity together with `legal_name`, `password`,
    `citizenship_country_code`, `residency_country_code`, an optional
    `residency_state_code` for US residents, `birth_date`, the declared
    `annual_income_cents` and `net_worth_cents`".

    Design: Corner/entities/investor_registration_starts_pending_with_restriction_until_at_created_at
    """
    set_clock("2026-09-01T00:00:00Z")
    investor = create_investor(email="runa2@x.com", legal_name="Runa Halvorsen",
                               annual_income_cents=25_000_000,
                               net_worth_cents=180_000_000)

    assert investor["email"] == "runa2@x.com"
    assert investor["annual_income_cents"] == 25_000_000
    assert investor["net_worth_cents"] == 180_000_000


# ── The append-mostly child record types ─────────────────────────────────────

def test_an_asset_report_exposes_only_id_and_created_at(api):
    """PRD 2.5: "Five child record types are append-mostly and are deliberately excluded
    from that block: `ArtworkAssetReport`, `Appraisal`, `OfferingReport`, `FeeAccrual`,
    and `Distribution` carry only `id` and `created_at`. They expose no `updated_at` and
    no `version` field at all."

    Design: Corner/entities/asset_reports_are_immutable_children_readable_under_their_artwork
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"])
    report = file_asset_report(artwork["id"], report_type="CONDITION_SURVEY",
                               outcome="VERIFIED", firm_name="Wrenworth Conservation",
                               condition_grade="GOOD")

    assert is_valid_uuid(report["id"])
    assert is_iso8601_timestamp(report["created_at"])
    assert "updated_at" not in report
    assert "version" not in report
    assert report["condition_grade"] == "GOOD"
    assert report["report_type"] == "CONDITION_SURVEY"


def test_a_condition_survey_writes_its_grade_through_to_the_parent(api):
    """PRD 3.1: "When the second component lands, the artwork's `condition_grade` is
    taken from the most recent condition survey on file and remains `PENDING` if no
    condition survey exists".

    Design: Corner/entities/asset_reports_are_immutable_children_readable_under_their_artwork
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"])
    file_verified_provenance(artwork["id"])
    file_asset_report(artwork["id"], report_type="CONDITION_SURVEY", outcome="VERIFIED",
                      firm_name="Wrenworth Conservation", condition_grade="GOOD")
    file_verified_authentication(artwork["id"])

    after = get_artwork(artwork["id"])
    assert after["status"] == "AUTHENTICATED"
    assert after["condition_grade"] == "GOOD"

    rows = get_success_data(api_client.list_asset_reports(artwork["id"], ISSUER))
    assert len(rows) == 3


def test_asset_reports_have_no_update_route(api):
    """PRD 2.4: "22. Route existence — the requested path has a declared route. Failure:
    `ERR_ROUTE_NOT_FOUND`, raised before any resource lookup."

    Design: Corner/entities/asset_reports_are_immutable_children_readable_under_their_artwork
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"])
    report = file_asset_report(artwork["id"], report_type="CONDITION_SURVEY",
                               outcome="VERIFIED", firm_name="Wrenworth Conservation",
                               condition_grade="GOOD")

    res = api_client._request(
        "PATCH", f"/api/artworks/{artwork['id']}/asset-reports/{report['id']}",
        {"condition_grade": "POOR"}, ISSUER)
    validate_error(res, "ERR_ROUTE_NOT_FOUND", expected_status=404)


# ── Creation defaults on the artwork ─────────────────────────────────────────

def test_a_new_work_starts_appraised_with_or_without_a_planted_grade(api):
    """PRD 3.1: "A newly registered work starts in `APPRAISED` with its `condition_grade`
    at the null-equivalent `PENDING`, its `last_appraised_value_cents` at zero, and
    `last_appraisal_at` null."

    Design: Corner/entities/artwork_condition_grade_ignored_input_is_recomputed_from_child_reports
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon")
    res = api_client.create_artwork({
        "title": "Cuadro Rojo", "artist_id": artist["id"], "creation_year": 1963,
        "medium": "PAINTING", "acquisition_cost_cents": 12_000_000,
        "reserve_price_cents": 20_000_000, "condition_grade": "EXCELLENT",
    }, ISSUER)
    artwork = validate_success(res, 201)

    assert artwork["condition_grade"] == "PENDING"
    assert artwork["status"] == "APPRAISED"
    assert artwork["last_appraised_value_cents"] == 0
    assert artwork["last_appraisal_at"] is None


def test_the_artifacts_overview_follows_the_report_chain_not_the_input(api):
    """PRD 3.1: "That projection carries `is_authenticated`, `has_good_provenance`,
    `latest_appraisal_value_cents`, `latest_appraisal_filed_at`, `custody_started_at`,
    `holding_period_elapsed_days`, and `appraisal_due`".

    Design: Corner/entities/artwork_condition_grade_ignored_input_is_recomputed_from_child_reports
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon")
    res = api_client.create_artwork({
        "title": "Cuadro Rojo", "artist_id": artist["id"], "creation_year": 1963,
        "medium": "PAINTING", "acquisition_cost_cents": 12_000_000,
        "reserve_price_cents": 20_000_000,
        "artifacts_overview": {"is_authenticated": True},
    }, ISSUER)
    artwork = validate_success(res, 201)

    assert artwork["status"] == "APPRAISED"
    assert artwork["artifacts_overview"]["is_authenticated"] is False
    assert artwork["artifacts_overview"]["latest_appraisal_value_cents"] == 0


# ── Lookups ──────────────────────────────────────────────────────────────────

def test_an_unknown_investor_id_is_not_found(api):
    """PRD 2.4: "4. Existence — every path identifier and every body identifier resolves
    to a stored row of the expected entity type. Failure: `ERR_NOT_FOUND`."

    Design: Corner/entities/investor_get_with_an_unknown_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.get_investor(NON_EXISTENT_UUID, ISSUER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
    assert res.json()["response_type"] == "error"
    assert get_success_data(api_client.list_investors(ISSUER)) == []


def test_an_unknown_artwork_id_is_not_found_rather_than_an_unknown_route(api):
    """PRD 2.4: "4. Existence ... Failure: `ERR_NOT_FOUND`." PRD 2.4: "22. Route
    existence — the requested path has a declared route. Failure: `ERR_ROUTE_NOT_FOUND`,
    raised before any resource lookup."

    Design: Corner/entities/artwork_get_with_an_unknown_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.get_artwork(NON_EXISTENT_UUID, ISSUER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    body = res.json()
    assert body["data"]["error_id"] != "ERR_ROUTE_NOT_FOUND"
    assert get_success_data(api_client.list_artworks(ISSUER)) == []


# ── Payload-shape refusals ───────────────────────────────────────────────────

def test_an_out_of_enum_exemption_type_is_refused_at_the_payload_layer(api):
    """PRD 2.4: "21. Enum membership — every enum-typed body field carries a declared
    member. Failure: `ERR_VALUE_REJECTED`."

    Design: Corner/entities/offering_create_with_an_out_of_enum_exemption_type_returns_value_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon")
    artwork = create_artwork(artist["id"], title="Cuadro Rojo",
                             acquisition_cost_cents=12_000_000,
                             reserve_price_cents=20_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])

    res = api_client.create_offering(artwork["id"], {
        "total_shares": 40_000, "price_per_share_cents": 1_500,
        "exemption_type": "REG_CF", "registration_cap_pct": 2_000,
        "liquidity_ratio_bps": 1_000, "hold_period_days": 182,
        "management_fee_bps": 150, "profit_participation_bps": 2_000,
        "cost_pass_through_bps": 10_000, "preferred_return_bps": 800,
    }, ISSUER)
    validate_error(res, "ERR_VALUE_REJECTED", expected_status=400)

    assert get_success_data(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork["id"]})) == []
    assert get_artwork(artwork["id"])["status"] == "AUTHENTICATED"


def test_omitting_a_required_body_field_is_refused_as_invalid_request(api):
    """PRD 2.4: "A request whose required body field is missing, or whose numeric field
    falls outside its declared range, is refused with `ERR_INVALID_REQUEST` (HTTP 400)
    as soon as the payload is parsed."

    Design: Corner/entities/artwork_create_missing_a_required_artist_reference_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    create_artist(legal_name="Ines Calderon")

    res = api_client.create_artwork({
        "title": "Cuadro Rojo", "creation_year": 1963, "medium": "PAINTING",
        "acquisition_cost_cents": 12_000_000, "reserve_price_cents": 20_000_000,
    }, ISSUER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
    assert get_success_data(api_client.list_artworks(ISSUER)) == []


# ── Listing: pagination and filtering ────────────────────────────────────────

def test_the_artwork_list_paginates_with_a_total_count_and_has_more(api):
    """PRD 2.3: "`limit` caps the number of items returned; it defaults to 10, must be at
    least 1, and must not exceed 100. `offset` states how many items to skip before the
    first returned item and defaults to 0. The paginated `meta` block carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/artwork_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon")
    titles = ["Cuadro Rojo", "Cuadro Azul", "Cuadro Verde"]
    artworks = [create_artwork(artist["id"], title=title) for title in titles]
    file_verified_provenance(artworks[0]["id"])
    file_verified_authentication(artworks[0]["id"])

    first, meta = validate_paginated(
        api_client.list_artworks(ISSUER, params={"limit": 2, "offset": 0}))
    assert len(first) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second, meta2 = validate_paginated(
        api_client.list_artworks(ISSUER, params={"limit": 2, "offset": 2}))
    assert len(second) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_the_artwork_list_defaults_to_ten_items_from_the_start(api):
    """PRD 2.3: "`limit` caps the number of items returned; it defaults to 10 ... `offset`
    states how many items to skip before the first returned item and defaults to 0."

    Design: Corner/entities/artwork_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon")
    for title in ("Cuadro Rojo", "Cuadro Azul", "Cuadro Verde"):
        create_artwork(artist["id"], title=title)

    data, meta = validate_paginated(api_client.list_artworks(ISSUER))
    assert len(data) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_an_offering_list_composes_its_parent_and_status_filters(api):
    """PRD 4: "GET `/api/offerings` | List offerings, optionally filtered by artwork or
    status". PRD 2.3: "The paginated `meta` block carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/offering_list_filters_by_status_and_parent_artwork_together
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon")
    artwork_1 = create_artwork(artist["id"], title="Cuadro Rojo",
                               acquisition_cost_cents=12_000_000,
                               reserve_price_cents=20_000_000)
    artwork_2 = create_artwork(artist["id"], title="Cuadro Azul",
                               acquisition_cost_cents=14_000_000,
                               reserve_price_cents=22_000_000)
    for artwork in (artwork_1, artwork_2):
        file_verified_provenance(artwork["id"])
        file_verified_authentication(artwork["id"])
    offering_1 = create_offering(artwork_1["id"])
    create_offering(artwork_2["id"])

    by_parent = get_success_data(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork_1["id"]}))
    assert [row["id"] for row in by_parent] == [offering_1["id"]]

    by_status = get_success_data(api_client.list_offerings(
        ISSUER, params={"status": "DRAFT"}))
    assert len(by_status) == 2

    both, meta = validate_paginated(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork_1["id"], "status": "DRAFT"}))
    assert [row["id"] for row in both] == [offering_1["id"]]

    neither, meta_none = validate_paginated(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork_1["id"], "status": "ALLOCATED"}))
    assert neither == []
    assert meta_none["total_count"] == 0


def test_the_offering_list_pagination_meta_counts_the_filtered_set(api):
    """PRD 2.3: "The paginated `meta` block carries `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/offering_list_filters_by_status_and_parent_artwork_together
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon")
    for title, cost in (("Cuadro Rojo", 12_000_000), ("Cuadro Azul", 14_000_000)):
        artwork = create_artwork(artist["id"], title=title,
                                 acquisition_cost_cents=cost,
                                 reserve_price_cents=cost + 8_000_000)
        file_verified_provenance(artwork["id"])
        file_verified_authentication(artwork["id"])
        create_offering(artwork["id"])

    data, meta = validate_paginated(
        api_client.list_offerings(ISSUER, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ── The residence rule ───────────────────────────────────────────────────────

def test_a_non_us_resident_is_refused_as_ineligible(api):
    """PRD 2.8: "then the residence rule: a `residency_country_code` other than `US` is
    refused outright." PRD 2.8: "A failed eligibility screen is reported as
    `ERR_INVESTOR_INELIGIBLE` (HTTP 400), covering non-US residency and an investor
    under 18 at the current clock instant."

    Design: Corner/validations/a_non_us_resident_subscription_is_refused_as_ineligible
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor(email="tokyo2@x.com", legal_name="Haruko Sen",
                               citizenship_country_code="JP",
                               residency_country_code="JP", birth_date="1965-05-05")

    set_clock("2026-09-10T00:00:00Z")
    res = api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": investor["id"],
         "requested_shares": 100},
        make_investor_headers(investor["id"]))
    validate_error(res, "ERR_INVESTOR_INELIGIBLE", expected_status=400)

    assert get_success_data(api_client.list_subscriptions(
        ISSUER, params={"offering_id": offering["id"]})) == []
    assert get_offering(offering["id"])["accepted_shares"] == 0