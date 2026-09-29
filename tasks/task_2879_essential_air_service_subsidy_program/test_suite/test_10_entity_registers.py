"""Register-level behaviour: creation echoes, retrieval, listing, defaults,
computed fields, system fields, shape rejection, immutability and the flat
entity topology of the Essential Air Service Subsidy API.
"""


from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_append_only_row,
    assert_envelope_meta,
    assert_instant,
    assert_money,
    assert_one_decimal,
    assert_pagination_meta,
    assert_ratio,
    assert_versioned_row,
)
from test_helpers.constants import (
    CARRIER_ACTIVE,
    CARRIER_PROBATION,
    COMMUNITY_REGISTERED,
    DEFAULT_CLOCK,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    EVAL_NOT_EVALUATED,
    OUTCOME_ELIGIBLE,
    PROPOSAL_DRAFT,
    SOLICITATION_OPEN,
    STANDING_PLACE_ON_PROBATION,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    OFFICER,
)


# ─── community_creation_returns_every_declared_field ──────────────────

def test_community_creation_echoes_every_declared_field(api: ApiClient):
    """Registering a community returns 201 and echoes all seven inputs beside the system and computed fields at their declared blanks.

    "A newly registered community has `status` `REGISTERED`, no `distance_band`, no `subsidy_per_passenger_cap_usd`, no `latest_determination_outcome`, and an `active_agreement_count` of 0."

    Design: Corner/entities/community_creation_returns_every_declared_field
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    response = api.create_community(f.community_payload(), ADMIN)
    community = validate_success(response, 201)
    assert_envelope_meta(response)
    assert response.json()["response_type"] == "object"

    assert community["code"] == "HYS"
    assert community["name"] == "Hays"
    assert community["state_code"] == "KS"
    assert_one_decimal(
        community["driving_miles_to_nearest_hub"], 165.0, "driving_miles_to_nearest_hub"
    )
    assert community["enplanements_prior_year"] == 6200
    assert community["min_required_weekly_round_trips"] == 12
    assert community["min_required_weekly_seats"] == 400

    assert community["status"] == COMMUNITY_REGISTERED
    assert community.get("distance_band") is None
    assert community.get("subsidy_per_passenger_cap_usd") is None
    assert community.get("latest_determination_outcome") is None
    assert community["active_agreement_count"] == 0

    assert_versioned_row(community, expected_version=1)
    assert_instant(community["created_at"], DEFAULT_CLOCK, "created_at")


# ─── carrier_retrieval_returns_the_stored_row ─────────────────────────

def test_carrier_get_returns_the_stored_row_with_its_creation_defaults(api: ApiClient):
    """Reading a never-reviewed carrier by id returns the stored row with its performance headline fields still empty.

    "A new carrier opens in `ACTIVE` standing, with `latest_completion_factor`, `latest_quality_score` and `latest_performance_tier` all empty because no review has been run, and `consecutive_watch_count` at 0."

    Design: Corner/entities/carrier_retrieval_returns_the_stored_row
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    created = get_success_data(api.create_carrier(f.carrier_payload(), ADMIN))

    response = api.get_carrier(created["id"], OFFICER)
    carrier = validate_success(response)
    assert response.json()["response_type"] == "object"

    assert carrier["id"] == created["id"]
    assert carrier["name"] == "Prairie Air"
    assert carrier["certificate_number"] == "CERT-1001"
    assert carrier["status"] == CARRIER_ACTIVE
    assert carrier["consecutive_watch_count"] == 0
    assert carrier.get("latest_completion_factor") is None
    assert carrier.get("latest_quality_score") is None
    assert carrier.get("latest_performance_tier") is None


# ─── community_listing_filters_and_paginates ──────────────────────────

def _three_communities(api: ApiClient):
    """HYS (KS, determined ELIGIBLE), DDC (KS, REGISTERED), GDV (MT, REGISTERED)."""
    fx.set_clock(api, DEFAULT_CLOCK)
    hays = get_success_data(api.create_community(f.community_payload(), ADMIN))
    fx.set_clock(api, "2026-08-01T01:00:00Z")
    dodge = get_success_data(api.create_community(f.second_community_payload(), ADMIN))
    fx.set_clock(api, "2026-08-01T02:00:00Z")
    glendive = get_success_data(
        api.create_community(
            f.community_payload(
                code="GDV",
                name="Glendive",
                state_code="MT",
                driving_miles_to_nearest_hub=221.0,
            ),
            ADMIN,
        )
    )
    get_success_data(
        api.create_eligibility_determination(
            hays["id"], f.determination_payload(), ANALYST
        )
    )
    return hays, dodge, glendive


def test_community_list_narrows_conjunctively_on_state_and_status(api: ApiClient):
    """Supplying a state filter, a status filter, or both narrows the community list and total_count follows the filtered set.

    "Filters on list endpoints are conjunctive: supplying more than one narrows the result set."

    Design: Corner/entities/community_listing_filters_and_paginates
    """
    hays, dodge, glendive = _three_communities(api)

    rows, meta = validate_paginated(api.list_communities(ADMIN, {"state_code": "KS"}))
    assert {row["id"] for row in rows} == {hays["id"], dodge["id"]}
    assert_pagination_meta(meta, DEFAULT_LIMIT, DEFAULT_OFFSET, 2, False)

    rows, meta = validate_paginated(
        api.list_communities(ADMIN, {"status": COMMUNITY_REGISTERED})
    )
    assert {row["id"] for row in rows} == {dodge["id"], glendive["id"]}
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_communities(
            ADMIN, {"state_code": "KS", "status": COMMUNITY_REGISTERED}
        )
    )
    assert [row["id"] for row in rows] == [dodge["id"]]
    assert meta["total_count"] == 1


def test_community_list_pages_the_filtered_set_without_overlap(api: ApiClient):
    """A limit of 1 over a two-row filtered set reports total_count 2 on both pages, flags has_more only on the first, and never repeats a row.

    "Successful list responses carry `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` counts every row matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/community_listing_filters_and_paginates
    """
    hays, dodge, _glendive = _three_communities(api)

    first_rows, first_meta = validate_paginated(
        api.list_communities(ADMIN, {"state_code": "KS", "limit": 1, "offset": 0})
    )
    assert len(first_rows) == 1
    assert_pagination_meta(first_meta, 1, 0, 2, True)

    second_rows, second_meta = validate_paginated(
        api.list_communities(ADMIN, {"state_code": "KS", "limit": 1, "offset": 1})
    )
    assert len(second_rows) == 1
    assert_pagination_meta(second_meta, 1, 1, 2, False)

    assert first_rows[0]["id"] != second_rows[0]["id"]
    assert {first_rows[0]["id"], second_rows[0]["id"]} == {hays["id"], dodge["id"]}


# ─── community_get_with_unknown_id_returns_not_found ──────────────────

def test_community_get_with_unknown_id_returns_the_community_not_found_error(api: ApiClient):
    """A well-formed identifier matching no stored community yields the register's own 404 and leaves the existing row untouched.

    "A request naming a community that does not exist therefore yields `ERR_COMMUNITY_NOT_FOUND` even if the rest of the request is also invalid."

    Design: Corner/entities/community_get_with_unknown_id_returns_not_found
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    stored = get_success_data(api.create_community(f.community_payload(), ADMIN))

    response = api.get_community(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(response, E.ERR_COMMUNITY_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()

    again = validate_success(api.get_community(stored["id"], ADMIN))
    assert again == stored


# ─── proposal_creation_missing_required_field_rejected ────────────────

def test_proposal_creation_omitting_term_months_is_rejected_as_malformed(api: ApiClient):
    """A proposal body missing term_months is refused as a shape violation and no proposal row is created.

    "Request shape — the body parses, every required field of the endpoint is present, enum values are members of their declared sets, numbers respect their declared ranges and decimal widths, month strings match the `YYYY-MM` form, datetimes are ISO 8601 UTC, and a requested annual subsidy does not exceed 1.25 times the agreement's current `annual_subsidy_usd`: `ERR_INVALID_REQUEST`."

    Design: Corner/entities/proposal_creation_missing_required_field_rejected
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    solicitation = fx.open_solicitation(api, reference.community_id)

    payload = f.proposal_payload(
        solicitation["id"],
        reference.carrier_id,
        reference.aircraft_type_id,
        term_months=None,
    )
    response = api.create_proposal(payload, reference.carrier_headers)
    validate_error(response, E.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_proposals(ADMIN, {"solicitation_id": solicitation["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0

    stored = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert stored["status"] == SOLICITATION_OPEN
    assert stored["preference_filing_count"] == 0


# ─── community_and_carrier_defaults_applied_on_create ─────────────────

def test_declared_defaults_appear_on_create_without_being_sent(api: ApiClient):
    """A community, a carrier, an aircraft type and a determination filed with an empty body all take their declared defaults.

    "The filing takes a single optional input, `waiver_requested`, which defaults to false and signals that the community is asking for relief from the enplanement floor."

    Design: Corner/entities/community_and_carrier_defaults_applied_on_create
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    community = validate_success(
        api.create_community(f.community_payload(), ADMIN), 201
    )
    assert community["status"] == COMMUNITY_REGISTERED
    assert community["active_agreement_count"] == 0

    carrier = validate_success(api.create_carrier(f.carrier_payload(), ADMIN), 201)
    assert carrier["status"] == CARRIER_ACTIVE
    assert carrier["consecutive_watch_count"] == 0

    aircraft_type = validate_success(
        api.create_aircraft_type(f.aircraft_type_payload(), ADMIN), 201
    )
    assert aircraft_type["is_retired"] is False

    determination = validate_success(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(waiver_requested=None), ANALYST
        ),
        201,
    )
    assert determination["waiver_requested"] is False
    assert determination["outcome"] == OUTCOME_ELIGIBLE
    assert_append_only_row(determination)


# ─── proposal_computed_fields_ignore_client_supplied_values ───────────

def test_proposal_draft_computes_projected_passengers_and_per_passenger_price(api: ApiClient):
    """Drafting a 12 round-trip, 19-seat bid for 1,600,000.00 stores 8892 projected passengers and a 179.94 per-passenger price the client never sent.

    "The program projects annual traffic as the weekly round trips multiplied by two — each round trip is two departures — multiplied by the seats offered on each departure, multiplied by 52 weeks in the year, multiplied by an assumed load factor of 0.375, with any fractional passenger discarded: the result is `projected_annual_passengers`."

    Design: Corner/entities/proposal_computed_fields_ignore_client_supplied_values
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, reference.community_id)

    response = api.create_proposal(
        f.proposal_payload(
            solicitation["id"], reference.carrier_id, reference.aircraft_type_id
        ),
        reference.carrier_headers,
    )
    proposal = validate_success(response, 201)

    assert proposal["projected_annual_passengers"] == 8892
    assert_money(
        proposal["subsidy_per_passenger_usd"], 179.94, "subsidy_per_passenger_usd"
    )
    assert proposal.get("composite_score") is None
    assert proposal["submission_state"] == PROPOSAL_DRAFT
    assert proposal["evaluation_state"] == EVAL_NOT_EVALUATED


# ─── carrier_system_fields_are_server_minted_and_versioned ────────────

def test_carrier_id_and_timestamps_are_minted_by_the_server(api: ApiClient):
    """A carrier created from a body carrying neither an id nor a version comes back with a bare UUID id, timestamps taken from the logical clock, and version 1.

    "Every stored row is addressed by an `id` that the server mints as a UUID string."

    Design: Corner/entities/carrier_system_fields_are_server_minted_and_versioned
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    payload = f.carrier_payload()
    assert "id" not in payload
    assert "version" not in payload
    assert "created_at" not in payload

    carrier = validate_success(api.create_carrier(payload, ADMIN), 201)

    identifier = carrier["id"]
    assert isinstance(identifier, str)
    assert len(identifier) == 36, f"id is not a bare UUID: {identifier!r}"
    assert identifier.count("-") == 4
    assert identifier == identifier.lower()
    assert "_" not in identifier

    assert carrier["version"] == 1
    assert_instant(carrier["created_at"], DEFAULT_CLOCK, "created_at")
    assert_instant(carrier["updated_at"], DEFAULT_CLOCK, "updated_at")


def test_carrier_standing_change_increments_version_and_refreshes_updated_at(api: ApiClient):
    """Placing a carrier on probation five days later takes version from 1 to 2 and moves updated_at to the new clock reading while created_at stays put.

    "Ten of the fourteen registers additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation of the row — and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation."

    Design: Corner/entities/carrier_system_fields_are_server_minted_and_versioned
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    created = get_success_data(api.create_carrier(f.carrier_payload(), ADMIN))
    assert created["version"] == 1

    fx.set_clock(api, "2026-08-06T09:30:00Z")
    changed = validate_success(
        api.carrier_standing_action(
            created["id"],
            f.carrier_standing_payload(STANDING_PLACE_ON_PROBATION, note="watch list"),
            ADMIN,
        )
    )
    assert changed["status"] == CARRIER_PROBATION
    assert changed["version"] == 2

    reread = validate_success(api.get_carrier(created["id"], ADMIN))
    assert reread["version"] == 2
    assert_instant(reread["created_at"], DEFAULT_CLOCK, "created_at")
    assert_instant(reread["updated_at"], "2026-08-06T09:30:00Z", "updated_at")


# ─── aircraft_type_invalid_enum_and_range_rejected ────────────────────

def test_proposal_enum_outside_its_set_and_term_outside_its_member_list_are_rejected(api: ApiClient):
    """A service level that is not one of the three declared values and a term of 18 months are each refused as shape violations, leaving the solicitation with no proposals.

    "It states a `service_level` of `ESSENTIAL_MINIMUM`, `ENHANCED` or `HUB_CONNECT`; the `weekly_round_trips` it commits to operate, from 1 through 21; the `seats_per_departure` it will offer on each departure, from 1 through 100; the `annual_subsidy_request_usd` it asks for, strictly greater than zero and carried to two decimal places; a `term_months` commitment of 12, 24, 36 or 48 months; and a `payment_basis` of either `COMPLETED_FLIGHT_PRORATION` or `SCHEDULED_FLIGHT_FLAT`, which fixes for the whole resulting agreement which of the two payment variants the program will pay on."

    Design: Corner/entities/aircraft_type_invalid_enum_and_range_rejected
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    solicitation = fx.open_solicitation(api, reference.community_id)

    bad_enum = api.create_proposal(
        f.proposal_payload(
            solicitation["id"],
            reference.carrier_id,
            reference.aircraft_type_id,
            service_level="PREMIUM_JET",
        ),
        reference.carrier_headers,
    )
    validate_error(bad_enum, E.ERR_INVALID_REQUEST, 400)

    bad_term = api.create_proposal(
        f.proposal_payload(
            solicitation["id"],
            reference.carrier_id,
            reference.aircraft_type_id,
            term_months=18,
        ),
        reference.carrier_headers,
    )
    validate_error(bad_term, E.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_proposals(ADMIN, {"solicitation_id": solicitation["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_fuel_index_month_that_is_not_a_year_dash_month_string_is_rejected(api: ApiClient):
    """Publishing a fuel index for "2026-8" is refused as a shape violation and the register stays empty.

    "Each row names an `index_month` in `YYYY-MM` form, unique across the register, and the `price_per_gallon_usd` published for that month: strictly positive and carried to exactly four decimal places."

    Design: Corner/entities/aircraft_type_invalid_enum_and_range_rejected
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    response = api.create_fuel_index(f.fuel_index_payload("2026-8", 2.4000), ADMIN)
    validate_error(response, E.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_fuel_indices(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


# ─── fuel_index_is_immutable_with_no_update_path ──────────────────────

def test_fuel_index_month_cannot_be_republished_at_a_corrected_price(api: ApiClient):
    """Republishing 2026-08 at a different price is refused as a duplicate, the register keeps the original price, and the row carries no version or updated_at to rewrite.

    "A community `code`, a carrier `certificate_number`, an aircraft type `code` or a fuel `index_month` that duplicates an existing row is refused with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/fuel_index_is_immutable_with_no_update_path
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    published = validate_success(
        api.create_fuel_index(f.fuel_index_payload("2026-08", 2.4000), ADMIN), 201
    )
    assert_append_only_row(published)

    republish = api.create_fuel_index(
        f.fuel_index_payload("2026-08", 3.1000), ADMIN
    )
    validate_error(republish, E.ERR_DUPLICATE_RESOURCE, 409)

    rows, meta = validate_paginated(
        api.list_fuel_indices(ADMIN, {"index_month": "2026-08"})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["id"] == published["id"]
    assert_ratio(rows[0]["price_per_gallon_usd"], 2.4000, "price_per_gallon_usd")
    assert_append_only_row(rows[0])


# ─── proposal_parent_references_must_resolve_in_declaration_order ──────

def test_proposal_body_foreign_keys_are_resolved_in_their_declared_order(api: ApiClient):
    """With three unresolvable foreign keys the carrier is reported first, then the aircraft type once the carrier is fixed, then the solicitation last.

    "Existence — every identifier referenced in the path or the body resolves to a stored row, checked left to right: the path identifier first, then body foreign keys in this declaration order — `community_id`, `carrier_id`, `aircraft_type_id`, `solicitation_id`, `proposal_id`, `agreement_id`, `service_period_id`."

    Design: Corner/entities/proposal_parent_references_must_resolve_in_declaration_order
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    fx.open_solicitation(api, reference.community_id)
    missing = NON_EXISTENT_UUID

    all_bad = api.create_proposal(
        f.proposal_payload(missing, missing, missing), reference.carrier_headers
    )
    validate_error(all_bad, E.ERR_CARRIER_NOT_FOUND, 404)

    bad_aircraft = api.create_proposal(
        f.proposal_payload(missing, reference.carrier_id, missing),
        reference.carrier_headers,
    )
    validate_error(bad_aircraft, E.ERR_AIRCRAFT_TYPE_NOT_FOUND, 404)

    bad_solicitation = api.create_proposal(
        f.proposal_payload(missing, reference.carrier_id, reference.aircraft_type_id),
        reference.carrier_headers,
    )
    validate_error(bad_solicitation, E.ERR_SOLICITATION_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_proposals(ADMIN, {"carrier_id": reference.carrier_id})
    )
    assert rows == []
    assert meta["total_count"] == 0


# ─── flat_topology_keeps_children_addressable_at_top_level ────────────

def test_child_rows_are_reachable_both_by_id_and_through_their_foreign_key_filter(api: ApiClient):
    """A proposal, its agreement and the agreement's first month are each fetched from their own collection with a foreign-key filter, and the period fetched by id is field-for-field the row the filtered list returned.

    "Communities may be filtered by `status` and `state_code`; eligibility determinations of a community by `outcome`; the solicitations of a community by `status` and `created_reason`; fuel indices by `index_month`; preference rows of a solicitation by `filing_sequence`; proposals by `solicitation_id`, `carrier_id`, `aircraft_type_id`, `submission_state` and `evaluation_state`; service agreements by `community_id`, `carrier_id`, `proposal_id`, `predecessor_agreement_id` and `status`; the performance reviews of an agreement by `basis` and `tier`; service periods by `agreement_id`, `status` and `period_month`; subsidy payments by `service_period_id` and `status`; termination petitions by `community_id`, `agreement_id` and `status`; and rate renegotiations by `agreement_id` and `status`."

    Design: Corner/entities/flat_topology_keeps_children_addressable_at_top_level
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.open_period(api, award.agreement_id, "2026-08")

    rows, meta = validate_paginated(
        api.list_proposals(ADMIN, {"solicitation_id": award.solicitation_id})
    )
    assert [row["id"] for row in rows] == [award.proposal_id]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_service_agreements(ADMIN, {"community_id": award.community_id})
    )
    assert [row["id"] for row in rows] == [award.agreement_id]
    assert rows[0]["proposal_id"] == award.proposal_id
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_service_periods(ADMIN, {"agreement_id": award.agreement_id})
    )
    assert [row["id"] for row in rows] == [period["id"]]
    assert rows[0]["period_month"] == "2026-08"
    assert meta["total_count"] == 1

    by_id = validate_success(api.get_service_period(period["id"], ADMIN))
    assert by_id == rows[0]
