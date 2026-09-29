"""Entity-level breadth: creation projections, reads, listings and shape refusals.

These are the plain resource-surface checks — what a successful create returns,
what a read returns for a row someone else created, how a listing pages, and
which refusals a malformed or unresolvable body earns.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_1,
    COUNSELOR_1,
    HRA_ADMIN_1,
    make_benefits_admin_headers,
    make_enrollment_counselor_headers,
    make_hra_administrator_headers,
)


def test_plan_year_creation_returns_the_full_projection(api):
    """A complete registration returns 201 and the whole seeded PlanYear.

    PRD 3.1: "A newly registered plan year opens in `DRAFT` with no valuation
    attached: `liability_method` and `liability_valued_at` are null, and
    `measured_retiree_count`, `epbo_total_cents`, `apbo_total_cents` and
    `service_cost_total_cents` all start at 0." The envelope is fixed by PRD 2.2:
    "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`." and the `response_type` is "object" for a single
    resource. PRD 2.4 adds that "`version` is an integer that starts at 1 when the
    row is created".

    Design: Corner/entities/plan_year_creation_returns_every_declared_field
    """
    response = api.create_plan_year(
        f.plan_year_payload(), make_benefits_admin_headers(ADMIN_1)
    )
    data = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    assert data["year"] == 2027
    assert data["status"] == "DRAFT"
    assert data["hra_credit_pre_medicare_cents"] == 185000
    assert data["hra_credit_medicare_cents"] == 209500
    assert data["carryover_cap_pct"] == 0.5
    assert data["discount_rate_bps"] == 500
    assert data["assumed_annual_subsidy_cents"] == 240000
    assert data["assumed_payment_years"] == 20
    assert data["premium_grace_period_days"] == 31
    assert data["reinstatement_window_days"] == 60
    assert data["notice_lead_days"] == 60

    assert data["measured_retiree_count"] == 0
    assert data["epbo_total_cents"] == 0
    assert data["apbo_total_cents"] == 0
    assert data["service_cost_total_cents"] == 0
    assert data["liability_method"] is None
    assert data["liability_valued_at"] is None

    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["version"] == 1


def test_retiree_retrieval_returns_the_stored_row_with_its_derived_group(api):
    """A read by a different role returns the row as stored, derivations included.

    PRD 3.3: "A retiree hired strictly before 1 January 1993 is a
    `GRANDFATHERED_A`." and "A new retiree record starts with `eligibility_status`
    `UNDETERMINED` and `determination_sequence` 0." The point total is not waiting
    on a determination, because PRD 3.3 also says the retiree's own
    `eligibility_points` "is computed when the retiree record is created" — for a
    retiree who retires at completed age 63 with 150 credited months, that is
    63 plus 12, or 75.

    Design: Corner/entities/retiree_retrieval_returns_stored_row_with_derived_group
    """
    created = fx.make_retiree_r1(api)

    data = validate_success(
        api.get_retiree(created["id"], make_enrollment_counselor_headers(COUNSELOR_1))
    )

    assert data["id"] == created["id"]
    assert data["full_name"] == "Rosa Alvarez"
    assert data["credited_service_months"] == 150
    assert data["hire_date"] == "1990-06-01"
    assert data["grandfathered_group"] == "GRANDFATHERED_A"
    assert data["eligibility_status"] == "UNDETERMINED"
    assert data["determination_sequence"] == 0
    assert data["eligibility_points"] == 75
    assert data["version"] == 1


def test_retiree_listing_pages_report_the_whole_filtered_total(api):
    """Two windows over three rows: total_count is the set, not the page.

    PRD 2.3: "`total_count` reports the number of rows matching the filters before
    the page window is applied, and `has_more` is true when rows remain beyond the
    current window." and "List results are always ordered by `created_at`
    ascending.", so the first page holds the two earliest rows and the second page
    holds the last one.

    Design: Corner/entities/retirees_listing_paginated_with_total_count_and_has_more
    """
    r1 = fx.make_retiree_r1(api)
    r3 = fx.make_retiree_r3(api)
    r4 = fx.make_retiree_r4(api)
    admin = make_benefits_admin_headers(ADMIN_1)

    page_1, meta_1 = validate_paginated(
        api.list_retirees(admin, {"limit": 2, "offset": 0})
    )
    assert len(page_1) == 2
    assert meta_1["total_count"] == 3
    assert meta_1["has_more"] is True
    assert meta_1["limit"] == 2
    assert meta_1["offset"] == 0
    assert fx.list_ids(page_1) == [r1["id"], r3["id"]]

    page_2, meta_2 = validate_paginated(
        api.list_retirees(admin, {"limit": 2, "offset": 2})
    )
    assert len(page_2) == 1
    assert meta_2["total_count"] == 3
    assert meta_2["has_more"] is False
    assert meta_2["offset"] == 2
    assert fx.list_ids(page_2) == [r4["id"]]

    assert not set(fx.list_ids(page_1)) & set(fx.list_ids(page_2))


def test_unknown_plan_option_id_reports_the_entity_specific_not_found(api):
    """An unused id on a non-empty database earns the option's own 404.

    PRD 2.8 rung 5: "A `plan_option_id` in the path, or `requested_plan_option_id`
    in the body, resolves to an existing plan option → `ERR_PLAN_OPTION_NOT_FOUND`
    (404), on plan-option reads and writes and on election-event creation." A
    plan year exists, so the refusal is about the named entity rather than about
    an empty store, and the plan year is left alone.

    Design: Corner/entities/plan_option_not_found_for_unknown_id
    """
    plan_year = fx.make_plan_year(api)
    admin = make_benefits_admin_headers(ADMIN_1)

    response = api.get_plan_option(NON_EXISTENT_UUID, admin)

    validate_error(
        response, ApiErrorId.ERR_PLAN_OPTION_NOT_FOUND.value, expected_status=404
    )
    assert response.json()["response_type"] == "error"

    untouched = fx.reload_plan_year(api, plan_year["id"])
    assert untouched["version"] == plan_year["version"]
    assert untouched["status"] == "DRAFT"


def test_plan_year_creation_without_the_carryover_cap_is_refused(api):
    """A required fraction is as required as a required id.

    PRD 3.1 lists `carryover_cap_pct` among the values the registration request
    establishes: "`carryover_cap_pct` is the fraction of the year's credit that is
    allowed to survive the year-end close." It is not one of the three optional
    parameters, because PRD 3.1 names those exactly: "Three calendar parameters on
    the plan year are optional and carry defaults chosen to match common plan
    documents." So PRD 2.8 rung 12 applies — "every required body field is
    present" → `ERR_INVALID_REQUEST` (400) — and nothing is persisted.

    Design: Corner/entities/plan_year_creation_missing_required_field_invalid_request
    """
    payload = f.plan_year_payload()
    del payload["carryover_cap_pct"]
    admin = make_benefits_admin_headers(ADMIN_1)

    validate_error(
        api.create_plan_year(payload, admin),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    _rows, meta = validate_paginated(api.list_plan_years(admin))
    assert meta["total_count"] == 0


def test_omitted_optional_fields_take_their_declared_defaults(api):
    """The day-count knobs and the retiree's other-coverage flags default, not null.

    PRD 3.1: "`premium_grace_period_days` — the number of days added to an
    invoice's due date before that invoice ages into past-due status — defaults to
    31 days, roughly a full billing month of forbearance. `reinstatement_window_days`,
    the number of days after a lapse during which coverage can still be bought
    back, defaults to 60 days. `notice_lead_days`, the minimum whole days that must
    separate a plan change communication from the date the change takes effect,
    defaults to 60 days as well." PRD 3.3 pins the retiree side: "`medicare_status`
    defaults to `PRE_MEDICARE`; `medicare_part_b_effective_date` defaults to null,
    meaning Part B is not in force; `other_group_coverage_employer_size` defaults
    to 0, where 0 means the retiree has no other group health coverage at all;
    `active_employment_flag` defaults to false".

    Design: Corner/entities/plan_year_day_count_defaults_applied_when_omitted
    """
    bare = f.plan_year_payload()
    for knob in (
        "premium_grace_period_days",
        "reinstatement_window_days",
        "notice_lead_days",
    ):
        del bare[knob]

    plan_year = validate_success(
        api.create_plan_year(bare, make_benefits_admin_headers(ADMIN_1)),
        expected_status=201,
    )
    assert plan_year["premium_grace_period_days"] == 31
    assert plan_year["reinstatement_window_days"] == 60
    assert plan_year["notice_lead_days"] == 60

    retiree = fx.make_retiree_r1(api)
    assert retiree["medicare_status"] == "PRE_MEDICARE"
    assert retiree["medicare_part_b_effective_date"] is None
    assert retiree["other_group_coverage_employer_size"] == 0
    assert retiree["active_employment_flag"] is False
    assert retiree["esrd_flag"] is False
    assert retiree["esrd_entitlement_date"] is None
    assert retiree["disability_entitlement_flag"] is False


def test_hra_account_system_fields_are_server_generated(api):
    """The client supplies three fields; the server mints the rest.

    PRD 2.4: "`id` is a server-minted UUID with no type prefix." and "`version` is
    an integer that starts at 1 when the row is created". PRD 3.7 fixes the seeded
    ledger: "`available_balance_cents` opens equal to `funded_cents`, and the four
    spent buckets — `pending_hold_cents`, `substantiated_paid_cents`,
    `premium_offset_cents` and `forfeited_cents` — all open at 0. The account's
    `status` opens `OPEN` and `closed_at` is null." With no prior account named,
    "`carryover_in_cents` is the `available_balance_cents` of the account named by
    `prior_year_account_id`, or 0 when no prior account was supplied", and the
    pre-Medicare credit of 185000 floors to 15416 cents a month before being
    multiplied by the 12 covered months.

    Design: Corner/entities/hra_account_system_fields_generated_server_side
    """
    fx.set_clock(api, "2026-11-01T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]

    data = validate_success(
        api.create_hra_account(
            f.hra_account_payload(retiree_id, plan_year["id"], 12),
            make_hra_administrator_headers(HRA_ADMIN_1),
        ),
        expected_status=201,
    )

    assert is_valid_uuid(data["id"])
    assert data["id"] != retiree_id
    assert data["id"] != plan_year["id"]
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])

    assert data["status"] == "OPEN"
    assert data["closed_at"] is None
    assert data["carryover_in_cents"] == 0
    assert data["annual_credit_cents"] == 184992
    assert data["funded_cents"] == 184992
    assert data["available_balance_cents"] == 184992
    assert data["pending_hold_cents"] == 0
    assert data["substantiated_paid_cents"] == 0
    assert data["premium_offset_cents"] == 0
    assert data["forfeited_cents"] == 0


def test_three_shape_violations_all_report_invalid_request(api):
    """An undeclared enum, a negative amount and an inverted interval share one id.

    PRD 2.8 rung 12: "Request shape — every required body field is present, every
    field has its declared JSON type, every enum field carries a declared member,
    every `_cents` and `_bps` field is a non-negative integer, every date and
    instant field parses as ISO 8601, `carryover_cap_pct` lies in the inclusive
    range 0 through 1, and every interval field pair satisfies a start strictly
    earlier than its end → `ERR_INVALID_REQUEST` (400), on every endpoint." The
    three declared coverage classes are named in PRD 3.1: "`PRE_MEDICARE_GROUP`,
    `MEDICARE_GROUP_WRAP` or `INDIVIDUAL_EXCHANGE_HRA`". None of the three
    requests may leave a row behind.

    Design: Corner/entities/plan_option_invalid_coverage_class_enum_rejected
    """
    plan_year = fx.make_plan_year(api)
    admin = make_benefits_admin_headers(ADMIN_1)

    validate_error(
        api.create_plan_option(
            f.plan_option_payload(
                plan_year["id"],
                plan_code="BAD-CLASS",
                coverage_class="CATASTROPHIC_ONLY",
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    validate_error(
        api.create_plan_option(
            f.plan_option_payload(
                plan_year["id"], plan_code="NEG-MONEY", monthly_premium_cents=-1
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    validate_error(
        api.create_plan_year(
            f.plan_year_payload(
                2028,
                overrides={
                    "open_enrollment_start": "2027-11-15T00:00:00Z",
                    "open_enrollment_end": "2027-10-15T00:00:00Z",
                    "coverage_start": "2028-01-01T00:00:00Z",
                },
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    _options, option_meta = validate_paginated(
        api.list_plan_options(admin, {"plan_year_id": plan_year["id"]})
    )
    assert option_meta["total_count"] == 0

    _years, year_meta = validate_paginated(api.list_plan_years(admin))
    assert year_meta["total_count"] == 1


def test_election_event_with_an_unknown_retiree_reports_retiree_not_found(api):
    """Existence outranks every business gate below it on the ladder.

    PRD 2.8 rung 4: "A `retiree_id` in the path or body resolves to an existing
    retiree → `ERR_RETIREE_NOT_FOUND` (404), on retiree read and update, and on
    eligibility-determination, election-event and reimbursement-account creation."
    No determination exists either, and PRD 3.5 would refuse that with
    `ERR_DETERMINATION_NOT_CERTIFIED`, but that gate sits far below rung 4 and PRD
    2.8 states the consequence: "no later rule is evaluated or reported."

    Design: Corner/entities/election_event_unknown_retiree_foreign_key_not_found
    """
    program = fx.standard_program(api)
    counselor = make_enrollment_counselor_headers(COUNSELOR_1)

    response = api.create_election_event(
        f.election_event_payload(
            NON_EXISTENT_UUID,
            program["plan_year"]["id"],
            program["pre65_core"]["id"],
            "ANNUAL_OPEN",
            "2026-10-20",
        ),
        counselor,
    )

    error = validate_error(
        response, ApiErrorId.ERR_RETIREE_NOT_FOUND.value, expected_status=404
    )
    assert error["error_id"] != ApiErrorId.ERR_DETERMINATION_NOT_CERTIFIED.value

    _rows, meta = validate_paginated(api.list_election_events(counselor))
    assert meta["total_count"] == 0
