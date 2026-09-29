"""Entity contracts: round-trip, listing, schema, defaults and scope (PRD §2.2-§2.4, §2.11)."""
from test_helpers import *  # noqa: F401,F403

DIRECTOR = TEST_USERS["program_director_headers"]
SOURCER = TEST_USERS["sourcing_manager_headers"]
APPROVER = TEST_USERS["contract_approver_headers"]
ANALYST = TEST_USERS["sales_ops_analyst_headers"]
DESK = TEST_USERS["travel_desk_headers"]
TAXMAN = TEST_USERS["tax_officer_headers"]

# The PLATINUM / GOLD ladder used by the corner-design recipes in this module.
PLATINUM = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250_000_000,
    "budget_per_qualifier_cents": 2_500_000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 150_000,
    "service_load_bp": 1275,
}
GOLD = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150_000_000,
    "budget_per_qualifier_cents": 1_600_000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40_000,
    "service_load_bp": 800,
}


def build_ladder_program(budget_total_cents=20_000_000, name="FY26 Presidents Circle"):
    """A DESIGN program plus the two-rung PLATINUM / GOLD ladder."""
    program = create_program(name=name, budget_total_cents=budget_total_cents)
    platinum = create_award_tier(program["id"], **PLATINUM)
    gold = create_award_tier(program["id"], **GOLD)
    return program, platinum, gold


def build_lisbon(program_id, inspection_score=82, shortlist=True):
    """Lisbon: the inspected (and by default shortlisted) candidate destination."""
    destination = create_destination(
        program_id,
        city="Lisbon",
        country_code="PT",
        per_person_cost_cents=431_757,
        risk_score=35,
        air_gateway_code="LIS",
    )
    inspect_destination(destination["id"], inspection_score)
    if shortlist:
        shortlist_destination(destination["id"])
    return read_destination(destination["id"])


def build_three_reviewed_qualifiers(program_id):
    """Two winners (PLATINUM, GOLD) and one salesperson who cleared no rung."""
    ana = create_qualifier(
        program_id,
        employee_code="S-1001",
        full_name="Ana Reyes",
        baseline_metric=180_000_000,
        actual_metric=260_000_000,
        guest_count=1,
    )
    review_qualifier(ana["id"])
    ben = create_qualifier(
        program_id,
        employee_code="S-2001",
        full_name="Ben Ortiz",
        baseline_metric=120_000_000,
        actual_metric=155_000_000,
        guest_count=0,
    )
    review_qualifier(ben["id"])
    zane = create_qualifier(
        program_id,
        employee_code="S-5003",
        full_name="Zane Holt",
        baseline_metric=100_000_000,
        actual_metric=149_999_999,
        guest_count=0,
    )
    review_qualifier(zane["id"])
    return ana, ben, zane


def test_program_creation_echoes_its_six_inputs_in_the_object_envelope():
    """POST /programs returns 201 with the charter it was handed, in the object envelope.

    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/program_creation_returns_full_row_with_seeded_derived_fields
    """
    payload = {
        "name": "FY26 Presidents Circle",
        "fiscal_year": 2026,
        "qualification_metric": "NET_REVENUE_CENTS",
        "sales_period_start": "2026-01-01T00:00:00Z",
        "sales_period_end": "2026-06-30T00:00:00Z",
        "budget_total_cents": 5_000_000,
    }
    response = api_client.create_program(payload, DIRECTOR)
    data = validate_success(response, 201)
    assert_program(data)

    body = response.json()
    assert body["response_type"] == "object", "a single resource is an object envelope"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    assert data["name"] == "FY26 Presidents Circle"
    assert data["fiscal_year"] == 2026
    assert data["qualification_metric"] == "NET_REVENUE_CENTS"
    assert_instant_equals(data["sales_period_start"], "2026-01-01T00:00:00Z", "sales_period_start")
    assert_instant_equals(data["sales_period_end"], "2026-06-30T00:00:00Z", "sales_period_end")
    assert data["budget_total_cents"] == 5_000_000
    assert data["status"] == "DESIGN", "the declared initial state"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])


def test_new_program_seeds_every_derived_field_and_leaves_measurement_null():
    """A fresh charter seeds its derived money and count fields to 0, not to null.

    PRD §3.1: "A newly chartered program lands in `DESIGN` with `gross_up_policy`
    set to `NONE`, `gross_up_policy_locked` false, `budget_posture` `OK`, and
    every computed money and count field at 0 — that is
    `per_person_cost_basis_cents`, `committed_budget_cents`,
    `budget_headroom_cents`, `cancellation_exposure_cents`,
    `reported_award_total_cents`, `qualified_count` and `travelled_count`. Both
    measurement outputs, `sales_lift_pct` and `satisfaction_index`, start null,
    as does `cancellation_reason`."

    Design: Corner/entities/program_creation_returns_full_row_with_seeded_derived_fields
    """
    data = validate_success(
        api_client.create_program(create_program_payload(budget_total_cents=5_000_000), DIRECTOR),
        201,
    )
    assert data["gross_up_policy"] == "NONE"
    assert data["gross_up_policy_locked"] is False
    assert data["budget_posture"] == "OK"
    for field in (
        "per_person_cost_basis_cents",
        "committed_budget_cents",
        "budget_headroom_cents",
        "cancellation_exposure_cents",
        "reported_award_total_cents",
        "qualified_count",
        "travelled_count",
    ):
        assert data[field] == 0, f"{field} must be seeded to 0, got {data[field]!r}"
    assert data["sales_lift_pct"] is None
    assert data["satisfaction_index"] is None
    assert data["cancellation_reason"] is None


def test_program_round_trips_byte_identically_through_its_single_get():
    """GET /programs/{id} returns the very row the create returned, unrecomputed.

    PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC
    timestamp with three fractional digits, recorded when the row is first
    persisted and never changed afterwards."

    Design: Corner/entities/stored_rows_round_trip_through_their_single_get
    """
    created = validate_success(
        api_client.create_program(create_program_payload(budget_total_cents=20_000_000), DIRECTOR),
        201,
    )
    fetched = validate_success(api_client.get_program(created["id"], DIRECTOR), 200)
    assert fetched == created, (
        "an unmutated program must read back exactly as it was written: "
        f"{fetched!r} != {created!r}"
    )
    assert fetched["version"] == 1, "a read is not a mutation"


def test_award_tier_round_trips_with_its_full_ladder_terms():
    """Every commercial term of a rung survives the round trip through its GET.

    PRD §4: "Read one award tier."

    Design: Corner/entities/stored_rows_round_trip_through_their_single_get
    """
    program = create_program(budget_total_cents=20_000_000)
    created = validate_success(
        api_client.create_award_tier(dict(program_id=program["id"], **PLATINUM), DIRECTOR), 201
    )
    fetched = validate_success(api_client.get_award_tier(created["id"], DIRECTOR), 200)
    assert_award_tier(fetched)
    assert fetched == created, f"tier must read back as written: {fetched!r} != {created!r}"
    assert fetched["program_id"] == program["id"]
    assert fetched["tier_code"] == "PLATINUM"
    assert fetched["tier_rank"] == 1
    assert fetched["qualification_threshold"] == 250_000_000
    assert fetched["budget_per_qualifier_cents"] == 2_500_000
    assert fetched["guest_allowance"] == 1
    assert fetched["air_cabin_class"] == "BUSINESS"
    assert fetched["upgrade_allowance_cents"] == 150_000
    assert fetched["service_load_bp"] == 1275


def test_both_destinations_round_trip_with_their_inspection_records():
    """The inspected destination keeps its stamps; its untouched sibling keeps its nulls.

    PRD §3.3: "A fresh candidate lands with `status` `CANDIDATE`,
    `inspection_status` `NOT_INSPECTED`, a null `inspection_score`, a null
    `inspected_by_user_id` and a null `inspected_at`."

    Design: Corner/entities/stored_rows_round_trip_through_their_single_get
    """
    program, _platinum, _gold = build_ladder_program()
    lisbon = build_lisbon(program["id"])
    seville = create_destination(
        program["id"],
        city="Seville",
        country_code="ES",
        per_person_cost_cents=388_000,
        risk_score=28,
        air_gateway_code="SVQ",
    )

    fetched_lisbon = read_destination(lisbon["id"])
    assert_destination(fetched_lisbon)
    assert fetched_lisbon == lisbon, "the shortlisted destination must read back as written"
    assert fetched_lisbon["status"] == "SHORTLISTED"
    assert fetched_lisbon["inspection_status"] == "INSPECTED"
    assert fetched_lisbon["inspection_score"] == 82
    assert fetched_lisbon["inspected_by_user_id"] == USER_IDS["SOURCING_MANAGER"]
    assert_instant_equals(
        fetched_lisbon["inspected_at"], LOGICAL_CLOCK_DEFAULT, "Destination.inspected_at"
    )
    assert fetched_lisbon["per_person_cost_cents"] == 431_757

    fetched_seville = read_destination(seville["id"])
    assert_destination(fetched_seville)
    assert fetched_seville == seville, "the candidate destination must read back as written"
    assert fetched_seville["status"] == "CANDIDATE"
    assert fetched_seville["inspection_status"] == "NOT_INSPECTED"
    assert fetched_seville["inspection_score"] is None
    assert fetched_seville["inspected_by_user_id"] is None
    assert fetched_seville["inspected_at"] is None


def test_reviewed_qualifiers_and_the_program_rollup_round_trip():
    """Adjudicated qualifiers read back with their stamped tier and committed cost.

    PRD §3.2: "The chosen rung is stamped onto `assigned_tier_id`,
    `committed_cost_cents` is stamped from the award-commitment computation
    below, and the qualifier moves `PENDING_REVIEW → QUALIFIED`."

    Design: Corner/entities/stored_rows_round_trip_through_their_single_get
    """
    program, platinum, gold = build_ladder_program()
    build_lisbon(program["id"])
    ana, ben, _zane = build_three_reviewed_qualifiers(program["id"])
    advance_program(program["id"], "SOURCING")

    fetched_ana = read_qualifier(ana["id"])
    assert_qualifier(fetched_ana)
    assert fetched_ana["assigned_tier_id"] == platinum["id"], "richest rung actually cleared"
    assert fetched_ana["award_status"] == "QUALIFIED"
    assert fetched_ana["committed_cost_cents"] == 150_000
    assert fetched_ana["employee_code"] == "S-1001"
    assert fetched_ana["full_name"] == "Ana Reyes"

    fetched_ben = read_qualifier(ben["id"])
    assert fetched_ben["assigned_tier_id"] == gold["id"]
    assert fetched_ben["award_status"] == "QUALIFIED"
    assert fetched_ben["committed_cost_cents"] == 40_000

    fetched_program = read_program(program["id"])
    assert fetched_program["status"] == "SOURCING"
    assert fetched_program["qualified_count"] == 2, "the disqualified row is not counted"
    assert fetched_program["per_person_cost_basis_cents"] == 0, "no hotel contract executed yet"
    assert fetched_program["committed_budget_cents"] == 150_000 + 40_000
    assert_budget_conserved(fetched_program)


def test_qualifier_list_resolves_the_declared_pagination_defaults():
    """GET /qualifiers with no params resolves limit 10, offset 0 and reports the total.

    PRD §2.3: "`limit` defaults to 10 when omitted, has a minimum of 1 and a
    maximum of 100. `offset` defaults to 0 when omitted and has a minimum of 0;
    it has no upper bound."

    Design: Corner/entities/qualifier_listing_paginates_and_filters_independently
    """
    program, _platinum, _gold = build_ladder_program()
    build_three_reviewed_qualifiers(program["id"])

    response = api_client.list_qualifiers(ANALYST)
    items, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", "a list response is an array envelope"
    assert meta["limit"] == 10, "the resolved default limit is echoed in meta"
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False, "offset 0 plus 3 rows is not less than total_count 3"
    assert len(items) == 3


def test_qualifier_pages_are_disjoint_slices_of_the_created_at_ordering():
    """A limit-2 walk returns the first two rows then the third, in created_at order.

    PRD §2.3: "List responses always return their rows sorted by `created_at`
    ascending, so that a page boundary is stable across repeated reads."

    Design: Corner/entities/qualifier_listing_paginates_and_filters_independently
    """
    program, _platinum, _gold = build_ladder_program()
    build_three_reviewed_qualifiers(program["id"])

    everything, _ = validate_paginated(api_client.list_qualifiers(ANALYST, params={"limit": 100}))
    stamps = [row["created_at"] for row in everything]
    assert stamps == sorted(stamps), f"rows must be ordered by created_at ascending, got {stamps}"

    page_one, meta_one = validate_paginated(
        api_client.list_qualifiers(ANALYST, params={"limit": 2, "offset": 0})
    )
    assert page_one == everything[:2]
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3, "total_count counts matching rows before pagination"
    assert meta_one["has_more"] is True, "0 + 2 < 3"

    page_two, meta_two = validate_paginated(
        api_client.list_qualifiers(ANALYST, params={"limit": 2, "offset": 2})
    )
    assert page_two == everything[2:]
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False, "2 + 1 is not less than 3"

    ids_one = {row["id"] for row in page_one}
    ids_two = {row["id"] for row in page_two}
    assert not (ids_one & ids_two), "consecutive pages must not overlap"

    beyond, meta_beyond = validate_paginated(
        api_client.list_qualifiers(ANALYST, params={"limit": 2, "offset": 3})
    )
    assert beyond == [], "offset has no upper bound; past the end is simply empty"
    assert meta_beyond["total_count"] == 3
    assert meta_beyond["has_more"] is False


def test_award_status_filter_narrows_the_qualifier_collection():
    """award_status=DISQUALIFIED returns only the salesperson who cleared no rung.

    PRD §2.3: "Qualifiers may be filtered by `program_id`, `assigned_tier_id`,
    `award_status`, `tax_status` and `employee_code`."

    Design: Corner/entities/qualifier_listing_paginates_and_filters_independently
    """
    program, _platinum, _gold = build_ladder_program()
    _ana, _ben, zane = build_three_reviewed_qualifiers(program["id"])

    items, meta = validate_paginated(
        api_client.list_qualifiers(ANALYST, params={"award_status": "DISQUALIFIED"})
    )
    assert meta["total_count"] == 1, "total_count reflects the filter, not the whole collection"
    assert [row["id"] for row in items] == [zane["id"]]
    assert items[0]["award_status"] == "DISQUALIFIED"
    assert items[0]["assigned_tier_id"] is None
    assert meta["limit"] == 10, "filtering does not disturb the resolved pagination defaults"
    assert meta["has_more"] is False

    qualified, qualified_meta = validate_paginated(
        api_client.list_qualifiers(ANALYST, params={"award_status": "QUALIFIED"})
    )
    assert qualified_meta["total_count"] == 2
    assert zane["id"] not in {row["id"] for row in qualified}


def test_tier_and_status_filters_combine_with_logical_and():
    """assigned_tier_id and award_status intersect rather than union.

    PRD §2.3: "Filters are combined with logical AND, and any filter that is
    omitted is not applied."

    Design: Corner/entities/qualifier_listing_paginates_and_filters_independently
    """
    program, platinum, gold = build_ladder_program()
    _ana, ben, _zane = build_three_reviewed_qualifiers(program["id"])

    intersect, intersect_meta = validate_paginated(
        api_client.list_qualifiers(
            ANALYST, params={"assigned_tier_id": gold["id"], "award_status": "QUALIFIED"}
        )
    )
    assert intersect_meta["total_count"] == 1, "AND, not OR"
    assert [row["id"] for row in intersect] == [ben["id"]]

    contradiction, contradiction_meta = validate_paginated(
        api_client.list_qualifiers(
            ANALYST, params={"assigned_tier_id": gold["id"], "award_status": "DISQUALIFIED"}
        )
    )
    assert contradiction == [], "no GOLD row is disqualified"
    assert contradiction_meta["total_count"] == 0
    assert contradiction_meta["has_more"] is False

    by_code, by_code_meta = validate_paginated(
        api_client.list_qualifiers(
            ANALYST, params={"program_id": program["id"], "employee_code": "S-2001"}
        )
    )
    assert by_code_meta["total_count"] == 1
    assert [row["id"] for row in by_code] == [ben["id"]]

    by_platinum, by_platinum_meta = validate_paginated(
        api_client.list_qualifiers(ANALYST, params={"assigned_tier_id": platinum["id"]})
    )
    assert by_platinum_meta["total_count"] == 1
    assert by_platinum[0]["assigned_tier_id"] == platinum["id"]


def test_pagination_parameters_outside_their_declared_bounds_are_rejected():
    """limit 0, limit 101, a negative offset and a non-integer limit are all 400s.

    PRD §2.3: "A `limit` that is not an integer, is below 1 or is above 100, and
    an `offset` that is not an integer or is negative, are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/qualifier_listing_paginates_and_filters_independently
    """
    program, _platinum, _gold = build_ladder_program()
    build_three_reviewed_qualifiers(program["id"])

    for params in (
        {"limit": 0},
        {"limit": 101},
        {"limit": "ten"},
        {"offset": -1},
        {"offset": "first"},
        {"limit": 2, "offset": -5},
    ):
        validate_error(
            api_client.list_qualifiers(ANALYST, params=params),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

    for params in ({"limit": 1}, {"limit": 100}, {"offset": 0}):
        _items, meta = validate_paginated(api_client.list_qualifiers(ANALYST, params=params))
        assert meta["total_count"] == 3, f"{params} sits inside the declared bounds"


def test_every_path_family_reports_its_own_not_found_id():
    """Each templated single-row read maps its unresolvable id to that entity's 404.

    PRD §2.8: "Violation: `ERR_PROGRAM_NOT_FOUND` for `program_id`,
    `ERR_TIER_NOT_FOUND` for `tier_id`, `ERR_QUALIFIER_NOT_FOUND` for
    `qualifier_id`, `ERR_DESTINATION_NOT_FOUND` for `destination_id`,
    `ERR_CONTRACT_NOT_FOUND` for `contract_id`, `ERR_MILESTONE_NOT_FOUND` for
    `milestone_id`, `ERR_REGISTRATION_NOT_FOUND` for `registration_id`,
    `ERR_ACTIVITY_NOT_FOUND` for `activity_id`, `ERR_SIGNUP_NOT_FOUND` for
    `signup_id`, `ERR_TAX_REPORT_NOT_FOUND` for `report_id` — all HTTP 404."

    Design: Corner/entities/missing_path_ids_and_missing_body_foreign_keys_return_distinct_404s
    """
    probes = (
        (api_client.get_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (api_client.get_award_tier, ApiErrorId.ERR_TIER_NOT_FOUND),
        (api_client.get_qualifier, ApiErrorId.ERR_QUALIFIER_NOT_FOUND),
        (api_client.get_destination, ApiErrorId.ERR_DESTINATION_NOT_FOUND),
        (api_client.get_supplier_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api_client.get_deposit_milestone, ApiErrorId.ERR_MILESTONE_NOT_FOUND),
        (api_client.get_registration, ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
        (api_client.get_onsite_activity, ApiErrorId.ERR_ACTIVITY_NOT_FOUND),
        (api_client.get_activity_signup, ApiErrorId.ERR_SIGNUP_NOT_FOUND),
        (api_client.get_tax_award_report, ApiErrorId.ERR_TAX_REPORT_NOT_FOUND),
    )
    seen = set()
    for reader, expected_id in probes:
        validate_error(reader(NON_EXISTENT_UUID, DIRECTOR), expected_id, 404)
        seen.add(expected_id.value)
    assert len(seen) == 10, "the ten path families must not collapse onto a shared 404 id"


def test_action_paths_resolve_their_templated_id_before_doing_anything():
    """An action on an id that names no row is the entity's 404, not a state error.

    PRD §2.8: "**Path existence** — every templated id in the URL resolves to an
    existing row, validated strictly left to right, so the leftmost unresolvable
    segment decides the error. Applies to every endpoint with a templated path
    segment."

    Design: Corner/entities/missing_path_ids_and_missing_body_foreign_keys_return_distinct_404s
    """
    validate_error(
        api_client.advance_program(NON_EXISTENT_UUID, advance_payload("SOURCING"), DIRECTOR),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.review_qualifier(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_QUALIFIER_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.shortlist_destination(NON_EXISTENT_UUID, SOURCER),
        ApiErrorId.ERR_DESTINATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.execute_contract(NON_EXISTENT_UUID, APPROVER),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.pay_deposit_milestone(NON_EXISTENT_UUID, APPROVER),
        ApiErrorId.ERR_MILESTONE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.confirm_registration(NON_EXISTENT_UUID, DESK),
        ApiErrorId.ERR_REGISTRATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.close_onsite_activity(NON_EXISTENT_UUID, DESK),
        ApiErrorId.ERR_ACTIVITY_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.cancel_activity_signup(NON_EXISTENT_UUID, DESK),
        ApiErrorId.ERR_SIGNUP_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.file_tax_award_report(NON_EXISTENT_UUID, TAXMAN),
        ApiErrorId.ERR_TAX_REPORT_NOT_FOUND,
        404,
    )


def test_body_foreign_keys_are_resolved_in_the_declared_input_order():
    """A contract naming a real program but no destination is a destination 404.

    PRD §2.8: "**Body foreign-key existence** — every foreign key supplied in the
    request body resolves to an existing row, validated in the order the fields
    are listed in that endpoint's input."

    Design: Corner/entities/missing_path_ids_and_missing_body_foreign_keys_return_distinct_404s
    """
    program, _platinum, _gold = build_ladder_program()
    lisbon = build_lisbon(program["id"])
    advance_program(program["id"], "SOURCING")

    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(program["id"], NON_EXISTENT_UUID), SOURCER
        ),
        ApiErrorId.ERR_DESTINATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(NON_EXISTENT_UUID, lisbon["id"]), SOURCER
        ),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    # program_id is listed first in the endpoint's input, so it decides when both
    # foreign keys are unresolvable.
    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), SOURCER
        ),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )

    _items, meta = validate_paginated(api_client.list_supplier_contracts(SOURCER))
    assert meta["total_count"] == 0, "no rejected create may have persisted a contract"


def test_a_body_program_id_that_names_nothing_leaves_the_ladder_untouched():
    """A tier create against a phantom program is a program 404 and writes nothing.

    PRD §2.8: "Applies to `POST /award-tiers`, `POST /qualifiers`,
    `POST /destinations`, `POST /supplier-contracts`, `POST /deposit-milestones`,
    `POST /registrations`, `POST /onsite-activities`, `POST /activity-signups`
    and `POST /tax-award-reports`."

    Design: Corner/entities/missing_path_ids_and_missing_body_foreign_keys_return_distinct_404s
    """
    program, _platinum, _gold = build_ladder_program()

    validate_error(
        api_client.create_award_tier(
            create_award_tier_payload(NON_EXISTENT_UUID, tier_code="SILVER", tier_rank=3), DIRECTOR
        ),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_qualifier(create_qualifier_payload(NON_EXISTENT_UUID), ANALYST),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_destination(create_destination_payload(NON_EXISTENT_UUID), SOURCER),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )

    tiers, meta = validate_paginated(
        api_client.list_award_tiers(DIRECTOR, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 2, "the real program's ladder is unchanged"
    assert {row["tier_code"] for row in tiers} == {"PLATINUM", "GOLD"}
    assert read_program(program["id"])["version"] == 1, "a rejected child create is not a mutation"


def test_the_error_envelope_carries_only_the_two_meta_keys():
    """A 404 body is the error envelope of §2.2 and nothing more.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/missing_path_ids_and_missing_body_foreign_keys_return_distinct_404s
    """
    response = api_client.get_program(NON_EXISTENT_UUID, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry exactly two keys, got {sorted(body['meta'])}"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
    assert set(body["data"]) == {"error_id", "message"}, (
        f"error data must carry exactly error_id and message, got {sorted(body['data'])}"
    )
    assert body["data"]["message"].strip(), "the message must be a human-readable explanation"


def test_omitting_a_required_field_is_an_invalid_request():
    """Dropping a declared required field from a create body is a 400.

    PRD §2.8: "**Request schema** — all required fields present, correct JSON
    types, enum values inside their declared sets and integers inside their
    declared ranges. ... Applies to all POST endpoints. Violation:
    `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/missing_required_fields_and_malformed_bodies_return_invalid_request
    """
    program = create_program(budget_total_cents=20_000_000)

    for missing in (
        "name",
        "fiscal_year",
        "qualification_metric",
        "sales_period_start",
        "sales_period_end",
        "budget_total_cents",
    ):
        payload = create_program_payload(budget_total_cents=20_000_000)
        payload.pop(missing)
        validate_error(
            api_client.create_program(payload, DIRECTOR), ApiErrorId.ERR_INVALID_REQUEST, 400
        )

    tier_payload = create_award_tier_payload(program["id"])
    tier_payload.pop("tier_rank")
    validate_error(
        api_client.create_award_tier(tier_payload, DIRECTOR), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    qualifier_payload = create_qualifier_payload(program["id"])
    qualifier_payload.pop("actual_metric")
    validate_error(
        api_client.create_qualifier(qualifier_payload, ANALYST), ApiErrorId.ERR_INVALID_REQUEST, 400
    )


def test_a_wrongly_typed_field_is_an_invalid_request_even_when_it_looks_numeric():
    """Money must arrive as an integer of whole cents, never as a decimal or a string.

    PRD §2.6: "All monetary amounts in this system are integers denominated in
    **whole cents**; there are no fractional-cent values anywhere in a request or
    a response."

    Design: Corner/entities/missing_required_fields_and_malformed_bodies_return_invalid_request
    """
    program = create_program(budget_total_cents=20_000_000)

    validate_error(
        api_client.create_destination(
            create_destination_payload(program["id"], per_person_cost_cents="431757"), SOURCER
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_destination(
            create_destination_payload(program["id"], per_person_cost_cents=431757.5), SOURCER
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_destination(
            create_destination_payload(program["id"], risk_score="high"), SOURCER
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_program(
            create_program_payload(fiscal_year="2026", budget_total_cents=20_000_000), DIRECTOR
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_program(
            create_program_payload(name=None, budget_total_cents=20_000_000), DIRECTOR
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )


def test_an_unknown_field_is_ignored_rather_than_rejected():
    """A field the endpoint does not accept is dropped, and the create still succeeds.

    PRD §2.8: "An unknown field carrying a value the endpoint does not accept is
    ignored, not rejected."

    Design: Corner/entities/missing_required_fields_and_malformed_bodies_return_invalid_request
    """
    payload = create_program_payload(budget_total_cents=20_000_000)
    payload["totally_unknown_knob"] = "please ignore me"
    payload["committed_budget_cents"] = 9_999_999

    data = validate_success(api_client.create_program(payload, DIRECTOR), 201)
    assert_program(data)
    assert "totally_unknown_knob" not in data, "an ignored field is not echoed back"
    assert data["committed_budget_cents"] == 0, "a computed field is never taken from input"
    assert data["budget_total_cents"] == 20_000_000


def test_a_rejected_body_persists_nothing_and_advances_no_version():
    """Schema failures are pure: the collection and the parent row are untouched.

    PRD §2.4: "`version`, an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row, whether the mutation
    came from a direct request or from a cascade triggered elsewhere."

    Design: Corner/entities/missing_required_fields_and_malformed_bodies_return_invalid_request
    """
    program, _platinum, _gold = build_ladder_program()
    before = read_program(program["id"])

    broken_tier = create_award_tier_payload(program["id"], tier_code="SILVER", tier_rank=3)
    broken_tier.pop("qualification_threshold")
    validate_error(
        api_client.create_award_tier(broken_tier, DIRECTOR), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    broken_qualifier = create_qualifier_payload(program["id"], employee_code="S-9009")
    broken_qualifier["baseline_metric"] = "one hundred million"
    validate_error(
        api_client.create_qualifier(broken_qualifier, ANALYST), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    _tiers, tier_meta = validate_paginated(
        api_client.list_award_tiers(DIRECTOR, params={"program_id": program["id"]})
    )
    assert tier_meta["total_count"] == 2, "the malformed tier was not persisted"

    _qualifiers, qualifier_meta = validate_paginated(
        api_client.list_qualifiers(ANALYST, params={"program_id": program["id"]})
    )
    assert qualifier_meta["total_count"] == 0, "the malformed qualifier was not persisted"

    after = read_program(program["id"])
    assert_version_is(after, 1, "Program")
    assert after["committed_budget_cents"] == 0
    # This program has never run a budget rollup, and PRD §3.1 pins the §2.10
    # identity as taking hold only "the first time the budget rollup runs" —
    # until then the charter's seeded zeros stand. What the rejected bodies must
    # not do is move any of those figures.
    assert after["committed_budget_cents"] == before["committed_budget_cents"]
    assert after["budget_headroom_cents"] == before["budget_headroom_cents"]
    assert after["budget_posture"] == before["budget_posture"]


def test_tier_optionals_default_to_zero_when_omitted():
    """A rung created with only its required terms takes 0 for all three optionals.

    PRD §3.1: "a `guest_allowance` from 0 to 2 (defaulting to 0 when omitted)
    bounding how many companions a winner may bring; ... an
    `upgrade_allowance_cents` of at least 0 (defaulting to 0) that the program
    will absorb before a winner is billed for a better cabin; and a
    `service_load_bp` from 0 to 5000 basis points (defaulting to 0) of service
    load added onto the destination's per-person cost for that rung."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    program = create_program(budget_total_cents=20_000_000)
    minimal = {
        "program_id": program["id"],
        "tier_code": "BRONZE",
        "tier_rank": 4,
        "qualification_threshold": 0,
        "budget_per_qualifier_cents": 0,
        "air_cabin_class": "ECONOMY",
    }
    data = validate_success(api_client.create_award_tier(minimal, DIRECTOR), 201)
    assert_award_tier(data)
    assert data["guest_allowance"] == 0, "the declared default is 0, not 1 and not null"
    assert data["upgrade_allowance_cents"] == 0
    assert data["service_load_bp"] == 0
    assert data["air_cabin_class"] == "ECONOMY"

    fetched = validate_success(api_client.get_award_tier(data["id"], DIRECTOR), 200)
    assert fetched == data, "the defaults are persisted, not just echoed"


def test_qualifier_guest_count_defaults_to_zero():
    """A qualifier loaded without a guest_count brings nobody.

    PRD §3.2: "and an optional `guest_count` from 0 to 2 that defaults to 0."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    program = create_program(budget_total_cents=20_000_000)
    payload = {
        "program_id": program["id"],
        "employee_code": "S-7007",
        "full_name": "Dana Whitfield",
        "baseline_metric": 100_000_000,
        "actual_metric": 140_000_000,
    }
    data = validate_success(api_client.create_qualifier(payload, ANALYST), 201)
    assert_qualifier(data)
    assert data["guest_count"] == 0, "the declared default is 0"
    assert data["award_status"] == "PENDING_REVIEW"
    assert data["tax_status"] == "NOT_APPLICABLE"
    assert data["assigned_tier_id"] is None
    assert data["committed_cost_cents"] == 0
    assert data["taxable_award_cents"] == 0
    assert data["notified_at"] is None
    assert data["version"] == 1

    assert read_qualifier(data["id"])["guest_count"] == 0


def test_registration_rooms_defaults_to_one():
    """A seat created without a rooms count occupies exactly one room.

    PRD §3.6: "an optional `rooms` count from 1 to 3 that defaults to 1"

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    base = setup_registration_open_program()
    qualifier = base["qualifier"]
    payload = {
        "qualifier_id": qualifier["id"],
        "registration_kind": "WINNER",
        "arrival_date": TEST_DEFAULTS["ARRIVAL_DATE"],
        "departure_date": TEST_DEFAULTS["DEPARTURE_DATE"],
        "expected_program_version": program_version(base["program"]["id"]),
    }
    data = validate_success(api_client.create_registration(payload, DESK), 201)
    assert_registration(data)
    assert data["rooms"] == 1, "the declared default is 1, not 0 and not null"
    assert data["attendance_status"] == "INVITED"
    assert data["registration_kind"] == "WINNER"
    assert data["guest_of_registration_id"] is None
    assert read_registration(data["id"])["rooms"] == 1


def test_a_fully_defaulted_rung_commits_nothing_at_review():
    """With a zero basis and zero optionals the award commitment is exactly 0.

    PRD §3.2: "Its per-person basis is the program's
    `per_person_cost_basis_cents`, which is 0 until a hotel contract has been
    executed (§3.4) and is the selected destination's per-person land cost
    thereafter."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    program = create_program(budget_total_cents=20_000_000)
    tier = validate_success(
        api_client.create_award_tier(
            {
                "program_id": program["id"],
                "tier_code": "BRONZE",
                "tier_rank": 4,
                "qualification_threshold": 0,
                "budget_per_qualifier_cents": 0,
                "air_cabin_class": "ECONOMY",
            },
            DIRECTOR,
        ),
        201,
    )
    qualifier = create_qualifier(
        program["id"],
        employee_code="S-7008",
        full_name="Iris Kwan",
        baseline_metric=0,
        actual_metric=0,
    )
    reviewed = review_qualifier(qualifier["id"])
    assert reviewed["award_status"] == "QUALIFIED", "a threshold of 0 is cleared inclusively"
    assert reviewed["assigned_tier_id"] == tier["id"]
    assert reviewed["committed_cost_cents"] == 0, "0 basis, 0 service load, 0 upgrade allowance"
    assert reviewed["guest_count"] == 0

    after = read_program(program["id"])
    assert after["qualified_count"] == 1
    assert after["committed_budget_cents"] == 0
    assert after["budget_headroom_cents"] == 20_000_000
    assert after["budget_posture"] == "OK", "0 of 20000000 is 0 basis points of utilization"
    assert_budget_conserved(after)


def test_seat_program_id_is_denormalised_from_the_qualifier_not_taken_from_input():
    """A client-supplied program_id on a seat is ignored in favour of the qualifier's.

    PRD §3.6: "The seat's `program_id` is not a client input: it is denormalised
    from the referenced qualifier's own `program_id`, and any value the client
    sends for it is ignored."

    Design: Corner/entities/computed_and_system_fields_are_derived_not_accepted_from_input
    """
    base = setup_registration_open_program()
    qualifier = base["qualifier"]
    decoy = create_program(name="FY27 Decoy Program", budget_total_cents=1_000_000)

    payload = create_registration_payload(
        qualifier["id"], program_version(base["program"]["id"])
    )
    payload["program_id"] = decoy["id"]
    data = validate_success(api_client.create_registration(payload, DESK), 201)

    assert data["program_id"] == base["program"]["id"], "the qualifier's program wins"
    assert data["program_id"] != decoy["id"]
    assert data["qualifier_id"] == qualifier["id"]
    assert read_registration(data["id"])["program_id"] == base["program"]["id"]


def test_a_fresh_seat_seeds_every_computed_capacity_and_air_field():
    """Enrolment seeds the seat's ledger and air columns; it never reads them from input.

    PRD §3.6: "A fresh seat lands with `attendance_status` `INVITED`, `air_status`
    `NOT_REQUESTED`, `waiver_on_file` false, `room_nights` 0, `cost_cents` 0, a
    null `air_cabin_class`, `air_deviation_pre_days` and `air_deviation_post_days`
    both 0, `air_base_fare_cents`, `air_upgrade_cost_cents`,
    `air_deviation_fee_cents`, `air_change_count` and `air_change_fee_total_cents`
    all 0, and a null `satisfaction_score` and `cancellation_reason`."

    Design: Corner/entities/computed_and_system_fields_are_derived_not_accepted_from_input
    """
    base = setup_registration_open_program()
    payload = create_registration_payload(
        base["qualifier"]["id"], program_version(base["program"]["id"])
    )
    payload.update(
        {
            "room_nights": 99,
            "cost_cents": 777_777,
            "waiver_on_file": True,
            "air_status": "TICKETED",
            "air_cabin_class": "BUSINESS",
            "air_base_fare_cents": 214_000,
            "air_change_count": 5,
            "satisfaction_score": 10,
        }
    )
    data = validate_success(api_client.create_registration(payload, DESK), 201)
    assert_registration(data)

    assert data["attendance_status"] == "INVITED"
    assert data["air_status"] == "NOT_REQUESTED", "the air dimension is not client-settable at create"
    assert data["waiver_on_file"] is False
    assert data["room_nights"] == 0, "room-nights are stamped at confirmation, not at enrolment"
    assert data["cost_cents"] == 0
    assert data["air_cabin_class"] is None
    for field in (
        "air_deviation_pre_days",
        "air_deviation_post_days",
        "air_base_fare_cents",
        "air_upgrade_cost_cents",
        "air_deviation_fee_cents",
        "air_change_count",
        "air_change_fee_total_cents",
    ):
        assert data[field] == 0, f"{field} must be seeded to 0, got {data[field]!r}"
    assert data["satisfaction_score"] is None
    assert data["cancellation_reason"] is None
    assert data["version"] == 1


def test_confirmation_derives_room_nights_from_the_half_open_interval():
    """room_nights is computed from rooms and the night count, not supplied.

    PRD §3.7: "A seat's `room_nights` is its `rooms` multiplied by the number of
    whole days from `arrival_date` up to but excluding `departure_date` — two
    rooms arriving on the 10th and departing on the 14th consume eight
    room-nights, not ten."

    Design: Corner/entities/computed_and_system_fields_are_derived_not_accepted_from_input
    """
    base = setup_registration_open_program()
    qualifier = base["qualifier"]
    seat = create_registration(
        qualifier["id"],
        arrival_date=TEST_DEFAULTS["ARRIVAL_DATE"],
        departure_date=TEST_DEFAULTS["DEPARTURE_DATE"],
    )
    respond_registration(seat["id"], qualifier["id"], response="ACCEPT", waiver_signed=True)
    confirmed = confirm_registration(seat["id"])

    assert confirmed["attendance_status"] == "CONFIRMED"
    assert confirmed["rooms"] == 1
    assert confirmed["room_nights"] == 4, "2026-11-02 up to but excluding 2026-11-06 is 4 nights"
    assert confirmed["cost_cents"] == 0, "no air record was opened, so the three air figures are 0"

    contract = read_contract(base["contract"]["id"])
    assert contract["room_nights_confirmed"] == 4
    assert_room_nights_conserved(contract)


def test_a_client_supplied_id_is_never_honoured():
    """The server mints its own UUID whatever id the client puts in the body.

    PRD §2.4: "Every resource carries a server-minted `id` that is a UUID string
    with no type prefix; a client-supplied `id` is never honoured."

    Design: Corner/entities/computed_and_system_fields_are_derived_not_accepted_from_input
    """
    program_payload = create_program_payload(budget_total_cents=20_000_000)
    program_payload["id"] = NON_EXISTENT_UUID
    program = validate_success(api_client.create_program(program_payload, DIRECTOR), 201)
    assert program["id"] != NON_EXISTENT_UUID, "the client's id must be discarded"
    assert is_valid_uuid(program["id"])
    validate_error(
        api_client.get_program(NON_EXISTENT_UUID, DIRECTOR), ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404
    )

    tier_payload = create_award_tier_payload(program["id"], tier_code="SILVER", tier_rank=3)
    tier_payload["id"] = NON_EXISTENT_UUID
    tier = validate_success(api_client.create_award_tier(tier_payload, DIRECTOR), 201)
    assert tier["id"] != NON_EXISTENT_UUID
    assert is_valid_uuid(tier["id"])

    destination_payload = create_destination_payload(program["id"])
    destination_payload["id"] = NON_EXISTENT_UUID
    destination = validate_success(
        api_client.create_destination(destination_payload, SOURCER), 201
    )
    assert destination["id"] != NON_EXISTENT_UUID
    assert is_valid_uuid(destination["id"])


def test_qualifier_award_columns_are_derived_at_review_not_accepted_at_load():
    """A load that pre-fills the award columns still lands with the declared seed values.

    PRD §3.2: "A new row lands with `award_status` `PENDING_REVIEW`, `tax_status`
    `NOT_APPLICABLE`, a null `assigned_tier_id`, `committed_cost_cents` and
    `taxable_award_cents` both 0, and a null `notified_at`."

    Design: Corner/entities/computed_and_system_fields_are_derived_not_accepted_from_input
    """
    program, platinum, _gold = build_ladder_program()

    payload = create_qualifier_payload(
        program["id"],
        employee_code="S-3003",
        full_name="Cleo Marsh",
        baseline_metric=180_000_000,
        actual_metric=260_000_000,
    )
    payload.update(
        {
            "award_status": "QUALIFIED",
            "tax_status": "REPORTED",
            "assigned_tier_id": platinum["id"],
            "committed_cost_cents": 999_999,
            "taxable_award_cents": 888_888,
            "notified_at": "2026-08-01T00:00:00Z",
        }
    )
    data = validate_success(api_client.create_qualifier(payload, ANALYST), 201)
    assert_qualifier(data)
    assert data["award_status"] == "PENDING_REVIEW", "adjudication is the only way to QUALIFIED"
    assert data["tax_status"] == "NOT_APPLICABLE"
    assert data["assigned_tier_id"] is None
    assert data["committed_cost_cents"] == 0
    assert data["taxable_award_cents"] == 0
    assert data["notified_at"] is None

    assert read_program(program["id"])["qualified_count"] == 0, "no rollup ran at load"

    reviewed = review_qualifier(data["id"])
    assert reviewed["assigned_tier_id"] == platinum["id"], "review is what stamps the tier"
    assert reviewed["committed_cost_cents"] == 150_000, "0 basis plus the tier upgrade allowance"


def test_contract_enum_values_outside_their_declared_sets_are_rejected():
    """supplier_kind, force_majeure_clause and exposure_basis are closed sets.

    PRD §3.4: "a `supplier_kind` of `HOTEL`, `DMC` or `AIR_CONSOLIDATOR`, ... a
    `force_majeure_clause` of `NONE`, `STANDARD` or `EXPANDED`, and an
    `exposure_basis` of `ATTRITION_BASIS` or `DEPOSIT_FORFEITURE_BASIS`."

    Design: Corner/entities/enum_range_and_ordered_date_constraints_are_enforced
    """
    base = setup_sourcing_program()
    program_id = base["program"]["id"]
    destination_id = base["destination"]["id"]

    for override in (
        {"supplier_kind": "RESORT"},
        {"supplier_kind": "hotel"},
        {"force_majeure_clause": "TOTAL"},
        {"exposure_basis": "CANCELLATION_BASIS"},
        {"exposure_basis": ""},
    ):
        validate_error(
            api_client.create_supplier_contract(
                create_supplier_contract_payload(program_id, destination_id, **override), SOURCER
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

    validate_error(
        api_client.create_program(
            create_program_payload(qualification_metric="GROSS_REVENUE_CENTS"), DIRECTOR
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_award_tier(
            create_award_tier_payload(program_id, tier_code="SILVER", tier_rank=3,
                                      air_cabin_class="FIRST"),
            DIRECTOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _items, meta = validate_paginated(api_client.list_supplier_contracts(SOURCER))
    assert meta["total_count"] == 0, "no enum-invalid contract may have been persisted"


def test_integer_fields_outside_their_declared_ranges_are_rejected():
    """Each bounded integer is checked at both ends, with the inclusive edges accepted.

    PRD §3.3: "a `risk_score` from 0 to 100 expressing travel risk"

    Design: Corner/entities/enum_range_and_ordered_date_constraints_are_enforced
    """
    program = create_program(budget_total_cents=20_000_000)

    for override in ({"risk_score": 101}, {"risk_score": -1}):
        validate_error(
            api_client.create_destination(
                create_destination_payload(program["id"], **override), SOURCER
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )
    for risk_score in (0, 100):
        edge = validate_success(
            api_client.create_destination(
                create_destination_payload(
                    program["id"], city=f"Edge{risk_score}", risk_score=risk_score
                ),
                SOURCER,
            ),
            201,
        )
        assert edge["risk_score"] == risk_score, "0 and 100 are inclusive bounds"

    for override in (
        {"service_load_bp": 5001},
        {"service_load_bp": -1},
        {"guest_allowance": 3},
        {"guest_allowance": -1},
        {"tier_rank": 0},
        {"qualification_threshold": -1},
        {"budget_per_qualifier_cents": -1},
    ):
        payload = create_award_tier_payload(program["id"], tier_code="SILVER", tier_rank=3)
        payload.update(override)
        validate_error(
            api_client.create_award_tier(payload, DIRECTOR), ApiErrorId.ERR_INVALID_REQUEST, 400
        )

    validate_error(
        api_client.create_program(
            create_program_payload(fiscal_year=2101, budget_total_cents=1), DIRECTOR
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_program(
            create_program_payload(fiscal_year=1999, budget_total_cents=1), DIRECTOR
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_program(create_program_payload(budget_total_cents=-1), DIRECTOR),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )


def test_a_sales_period_that_ends_at_or_before_it_starts_is_an_invalid_date_range():
    """The charter's closing instant must be strictly after its opening instant.

    PRD §3.1: "The closing instant must be strictly after the opening instant; a
    period that ends at or before it starts is rejected with
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/entities/enum_range_and_ordered_date_constraints_are_enforced
    """
    for start, end in (
        ("2026-06-30T00:00:00Z", "2026-01-01T00:00:00Z"),
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ):
        validate_error(
            api_client.create_program(
                create_program_payload(
                    sales_period_start=start,
                    sales_period_end=end,
                    budget_total_cents=20_000_000,
                ),
                DIRECTOR,
            ),
            ApiErrorId.ERR_INVALID_DATE_RANGE,
            422,
        )

    ok = validate_success(
        api_client.create_program(
            create_program_payload(
                sales_period_start="2026-01-01T00:00:00Z",
                sales_period_end="2026-01-01T00:00:01Z",
                budget_total_cents=20_000_000,
            ),
            DIRECTOR,
        ),
        201,
    )
    assert_instant_equals(ok["sales_period_end"], "2026-01-01T00:00:01Z", "sales_period_end")

    _programs, meta = validate_paginated(api_client.list_programs(DIRECTOR))
    assert meta["total_count"] == 1, "only the strictly ordered charter was persisted"


def test_an_activity_interval_that_ends_at_or_before_it_starts_is_an_invalid_date_range():
    """An activity's end instant must be strictly after its start instant.

    PRD §3.8: "The end instant must be strictly after the start instant, or the
    request reports `ERR_INVALID_DATE_RANGE`."

    Design: Corner/entities/enum_range_and_ordered_date_constraints_are_enforced
    """
    base = setup_contracted_program()
    program_id = base["program"]["id"]
    start = TEST_DEFAULTS["ACTIVITY_START_AT"]

    for end in (instant_plus_minutes(start, -60), start):
        validate_error(
            api_client.create_onsite_activity(
                create_onsite_activity_payload(program_id, start_at=start, end_at=end), DESK
            ),
            ApiErrorId.ERR_INVALID_DATE_RANGE,
            422,
        )

    ok = validate_success(
        api_client.create_onsite_activity(
            create_onsite_activity_payload(
                program_id, start_at=start, end_at=instant_plus_minutes(start, 1)
            ),
            DESK,
        ),
        201,
    )
    assert_onsite_activity(ok)
    assert ok["status"] == "OPEN"
    assert ok["booked_count"] == 0
    assert ok["waitlist_count"] == 0

    _activities, meta = validate_paginated(
        api_client.list_onsite_activities(DESK, params={"program_id": program_id})
    )
    assert meta["total_count"] == 1, "the reversed intervals were not persisted"


def test_the_request_schema_check_outranks_the_ordered_date_check():
    """A body that is both wrongly typed and reversed reports the schema failure.

    PRD §2.8: "7. **Request schema** — all required fields present, correct JSON
    types, enum values inside their declared sets and integers inside their
    declared ranges."

    Design: Corner/entities/enum_range_and_ordered_date_constraints_are_enforced
    """
    validate_error(
        api_client.create_program(
            create_program_payload(
                fiscal_year="2026",
                sales_period_start="2026-06-30T00:00:00Z",
                sales_period_end="2026-01-01T00:00:00Z",
                budget_total_cents=20_000_000,
            ),
            DIRECTOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    base = setup_contracted_program()
    start = TEST_DEFAULTS["ACTIVITY_START_AT"]
    validate_error(
        api_client.create_onsite_activity(
            create_onsite_activity_payload(
                base["program"]["id"],
                start_at=start,
                end_at=instant_plus_minutes(start, -60),
                risk_level="EXTREME",
            ),
            DESK,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )


def test_award_tier_payload_omits_version_and_updated_at_entirely():
    """A tier carries only id and created_at from the common field set.

    PRD §2.4: "`AwardTier` is the single exception: a tier is immutable once
    created, has no update or state-change operation of any kind, and therefore
    carries only `id` and `created_at` — both `updated_at` and `version` are
    absent from an `AwardTier` payload entirely."

    Design: Corner/entities/award_tier_is_immutable_with_no_version_and_no_write_path
    """
    program = create_program(budget_total_cents=20_000_000)
    created = validate_success(
        api_client.create_award_tier(dict(program_id=program["id"], **PLATINUM), DIRECTOR), 201
    )
    assert_award_tier(created)
    assert "version" not in created, "an AwardTier has no version at all"
    assert "updated_at" not in created, "an AwardTier has no updated_at at all"
    assert is_iso8601_timestamp(created["created_at"])

    fetched = validate_success(api_client.get_award_tier(created["id"], DIRECTOR), 200)
    assert "version" not in fetched
    assert "updated_at" not in fetched

    listed, _meta = validate_paginated(
        api_client.list_award_tiers(DIRECTOR, params={"program_id": program["id"]})
    )
    assert len(listed) == 1
    assert "version" not in listed[0], "the list projection is the same immutable shape"
    assert "updated_at" not in listed[0]


def test_a_duplicate_tier_code_within_a_program_is_a_duplicate_tier_key():
    """A second rung reusing a tier_code collides.

    PRD §3.1: "Both `tier_code` and `tier_rank` are unique within a program, and a
    collision on either reports `ERR_DUPLICATE_TIER_KEY`."

    Design: Corner/entities/award_tier_is_immutable_with_no_version_and_no_write_path
    """
    program, _platinum, _gold = build_ladder_program()

    clash = dict(PLATINUM)
    clash["tier_rank"] = 7
    validate_error(
        api_client.create_award_tier(dict(program_id=program["id"], **clash), DIRECTOR),
        ApiErrorId.ERR_DUPLICATE_TIER_KEY,
        409,
    )

    tiers, meta = validate_paginated(
        api_client.list_award_tiers(DIRECTOR, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 2, "the rejected rung was not appended"
    ranks = sorted(row["tier_rank"] for row in tiers)
    assert ranks == [1, 2], f"the ladder still has exactly ranks 1 and 2, got {ranks}"


def test_a_duplicate_tier_rank_leaves_the_existing_rung_untouched():
    """A colliding rank cannot overwrite the rung that already holds it.

    PRD §3.1: "A tier is **immutable**: there is no operation that edits or
    retires one, which is why an `AwardTier` payload has no `version` and no
    `updated_at` at all."

    Design: Corner/entities/award_tier_is_immutable_with_no_version_and_no_write_path
    """
    program, platinum, _gold = build_ladder_program()

    overwrite_attempt = {
        "program_id": program["id"],
        "tier_code": "DIAMOND",
        "tier_rank": 1,
        "qualification_threshold": 1,
        "budget_per_qualifier_cents": 1,
        "guest_allowance": 2,
        "air_cabin_class": "ECONOMY",
        "upgrade_allowance_cents": 1,
        "service_load_bp": 1,
    }
    validate_error(
        api_client.create_award_tier(overwrite_attempt, DIRECTOR),
        ApiErrorId.ERR_DUPLICATE_TIER_KEY,
        409,
    )

    unchanged = validate_success(api_client.get_award_tier(platinum["id"], DIRECTOR), 200)
    assert unchanged == platinum, "rank 1 still holds exactly the rung it was created with"
    assert unchanged["tier_code"] == "PLATINUM"
    assert unchanged["guest_allowance"] == 1
    assert unchanged["upgrade_allowance_cents"] == 150_000
    assert unchanged["service_load_bp"] == 1275

    _tiers, meta = validate_paginated(
        api_client.list_award_tiers(DIRECTOR, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 2


def test_tier_uniqueness_is_scoped_to_the_program():
    """The same code and rank are free in a different program's ladder.

    PRD §2.8: "**Uniqueness** — `employee_code` is unique per `program_id`;
    `tier_code` and `tier_rank` are each unique per `program_id`"

    Design: Corner/entities/award_tier_is_immutable_with_no_version_and_no_write_path
    """
    first, platinum, _gold = build_ladder_program()
    second = create_program(name="FY27 Presidents Circle", budget_total_cents=20_000_000)

    twin = validate_success(
        api_client.create_award_tier(dict(program_id=second["id"], **PLATINUM), DIRECTOR), 201
    )
    assert_award_tier(twin)
    assert twin["id"] != platinum["id"], "a distinct row, not a shared one"
    assert twin["tier_code"] == "PLATINUM"
    assert twin["tier_rank"] == 1
    assert twin["program_id"] == second["id"]

    _first_tiers, first_meta = validate_paginated(
        api_client.list_award_tiers(DIRECTOR, params={"program_id": first["id"]})
    )
    assert first_meta["total_count"] == 2, "the first ladder is unaffected"
    _second_tiers, second_meta = validate_paginated(
        api_client.list_award_tiers(DIRECTOR, params={"program_id": second["id"]})
    )
    assert second_meta["total_count"] == 1


def test_a_contract_whose_destination_belongs_to_another_program_is_a_scope_mismatch():
    """Both ids resolve, yet the pair does not agree on a program.

    PRD §2.11: "A supplier contract's `destination_id` must name a destination
    belonging to the same program as the contract's `program_id`."

    Design: Corner/entities/cross_aggregate_foreign_keys_must_agree_on_program_scope
    """
    first = setup_sourcing_program()
    second = setup_sourcing_program(program_overrides={"name": "FY27 Presidents Circle"})

    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(
                first["program"]["id"], second["destination"]["id"]
            ),
            SOURCER,
        ),
        ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
        422,
    )
    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(
                second["program"]["id"], first["destination"]["id"]
            ),
            SOURCER,
        ),
        ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
        422,
    )


def test_a_rejected_cross_program_contract_leaves_both_programs_untouched():
    """The scope failure is pure: no contract, no destination move, no rollup.

    PRD §2.8: "**Cross-aggregate scope agreement** — a contract's `destination_id`
    belongs to the same program as its `program_id`; a signup's activity and
    registration belong to the same program; a tax report's `tax_year` equals the
    `fiscal_year` of the program behind the referenced qualifier."

    Design: Corner/entities/cross_aggregate_foreign_keys_must_agree_on_program_scope
    """
    first = setup_sourcing_program()
    second = setup_sourcing_program(program_overrides={"name": "FY27 Presidents Circle"})
    before_first = read_program(first["program"]["id"])
    before_second = read_program(second["program"]["id"])

    validate_error(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(
                first["program"]["id"], second["destination"]["id"]
            ),
            SOURCER,
        ),
        ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
        422,
    )

    _contracts, first_meta = validate_paginated(
        api_client.list_supplier_contracts(SOURCER, params={"program_id": first["program"]["id"]})
    )
    assert first_meta["total_count"] == 0, "no contract was opened against the first program"
    _also, second_meta = validate_paginated(
        api_client.list_supplier_contracts(SOURCER, params={"program_id": second["program"]["id"]})
    )
    assert second_meta["total_count"] == 0

    borrowed = read_destination(second["destination"]["id"])
    assert borrowed["status"] == "SHORTLISTED", "the borrowed destination did not move"
    assert borrowed["program_id"] == second["program"]["id"]

    assert read_program(first["program"]["id"]) == before_first
    assert read_program(second["program"]["id"]) == before_second
    assert before_second["committed_budget_cents"] == 0
    assert before_second["per_person_cost_basis_cents"] == 0


def test_an_in_scope_contract_is_accepted_and_lands_with_its_seeded_columns():
    """The control case: same program, and the DRAFT row seeds every derived column.

    PRD §3.4: "A new contract lands in `DRAFT` with `round_count` 0,
    `room_nights_blocked`, `room_nights_confirmed` and `room_nights_available`
    all 0, `attrition_posture` `CLEAR`, and null values for
    `last_proposed_by_user_id`, `last_countered_by_user_id`,
    `executed_by_user_id`, `executed_at` and `withdrawal_reason`."

    Design: Corner/entities/cross_aggregate_foreign_keys_must_agree_on_program_scope
    """
    base = setup_sourcing_program()
    data = validate_success(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(
                base["program"]["id"], base["destination"]["id"]
            ),
            SOURCER,
        ),
        201,
    )
    assert_supplier_contract(data)
    assert data["status"] == "DRAFT"
    assert data["round_count"] == 0
    assert data["room_nights_blocked"] == 0, "the block is stamped at execution, not at create"
    assert data["room_nights_confirmed"] == 0
    assert data["room_nights_available"] == 0
    assert data["attrition_posture"] == "CLEAR"
    for field in (
        "last_proposed_by_user_id",
        "last_countered_by_user_id",
        "executed_by_user_id",
        "executed_at",
        "withdrawal_reason",
    ):
        assert data[field] is None, f"{field} must start null, got {data[field]!r}"
    assert data["program_id"] == base["program"]["id"]
    assert data["destination_id"] == base["destination"]["id"]
    assert_instant_equals(data["stay_end_at"], "2026-11-11T00:00:00Z", "stay_end_at")
    assert data["version"] == 1


def test_a_signup_across_two_programs_is_a_scope_mismatch():
    """An activity of one program cannot take a seat from another.

    PRD §3.8: "The activity and the registration must belong to the same program,
    or it reports `ERR_PROGRAM_SCOPE_MISMATCH`."

    Design: Corner/entities/cross_aggregate_foreign_keys_must_agree_on_program_scope
    """
    first = setup_onsite_with_activity()
    second = setup_onsite_with_activity(program_overrides={"name": "FY27 Presidents Circle"})

    validate_error(
        api_client.create_activity_signup(
            create_activity_signup_payload(
                first["activity"]["id"],
                second["registration"]["id"],
                activity_version(first["activity"]["id"]),
            ),
            DESK,
        ),
        ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
        422,
    )

    untouched = read_activity(first["activity"]["id"])
    assert_signup_counters(untouched, booked=0, waitlisted=0)
    assert untouched["version"] == 1, "a rejected signup does not bump the activity"

    in_scope = create_signup(first["activity"]["id"], first["registration"]["id"])
    assert_activity_signup(in_scope)
    assert in_scope["status"] == "BOOKED", "the same call inside one program is accepted"


def test_a_tax_year_that_disagrees_with_the_fiscal_year_is_a_scope_mismatch():
    """The report's tax_year must match the fiscal_year of the qualifier's program.

    PRD §3.9: "The `tax_year` must equal the `fiscal_year` of the program behind
    that qualifier, or the draft reports `ERR_PROGRAM_SCOPE_MISMATCH`."

    Design: Corner/entities/cross_aggregate_foreign_keys_must_agree_on_program_scope
    """
    base = setup_reconciled_program()
    qualifier = base["qualifier"]
    assert base["program"]["fiscal_year"] == 2026

    for wrong_year in (2027, 2025):
        validate_error(
            api_client.create_tax_award_report(
                create_tax_award_report_payload(qualifier["id"], tax_year=wrong_year), TAXMAN
            ),
            ApiErrorId.ERR_PROGRAM_SCOPE_MISMATCH,
            422,
        )

    _reports, meta = validate_paginated(
        api_client.list_tax_award_reports(TAXMAN, params={"qualifier_id": qualifier["id"]})
    )
    assert meta["total_count"] == 0, "no mismatched draft was persisted"

    control = validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(qualifier["id"], tax_year=2026), TAXMAN
        ),
        201,
    )
    assert_tax_award_report(control)
    assert control["status"] == "DRAFT"
    assert control["tax_year"] == 2026
    assert control["qualifier_id"] == qualifier["id"]
    assert_reported_value_identity(control)
