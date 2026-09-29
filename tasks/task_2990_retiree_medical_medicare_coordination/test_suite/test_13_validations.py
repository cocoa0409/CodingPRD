"""Refusals: the ladder's rungs probed one at a time, and their exact edges.

Each test drives a single request into one rung of the validation ladder and
checks three things: the status code and error id it earns, that the rungs above
it were satisfied so the refusal really is the one under test, and that nothing
was written on the way out.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_hra_ledger_conservation,
    assert_instant_equals,
    build_user_headers,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import ROLE_BENEFITS_ADMIN
from test_helpers.test_users import (
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    BILLING_1,
    COUNSELOR_1,
    HRA_ADMIN_1,
    make_benefits_admin_headers,
    make_billing_clerk_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
    make_hra_administrator_headers,
    make_retiree_headers,
)


def test_blank_or_unknown_role_headers_all_report_unauthenticated(api):
    """An empty id, an empty role and an invented role are one failure, not three.

    PRD 2.8 rung 1: "Authentication — both headers present and non-empty and
    `X-User-Role` one of the eight declared roles → `ERR_UNAUTHENTICATED` (401),
    on every endpoint." A blank header is present but empty, so it fails the
    non-empty half; `AuditorGeneral` is non-empty but is not one of the eight, so
    it fails the membership half. Neither is an authorization failure, because
    rung 2 asks whether "the caller's role appears in the target endpoint's role
    list" and there is no established caller yet. The envelope is fixed by
    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/validations/blank_or_unknown_role_header_returns_unauthenticated
    """
    probes = (
        build_user_headers("", ROLE_BENEFITS_ADMIN),
        build_user_headers(ADMIN_1, ""),
        build_user_headers(ADMIN_1, "AuditorGeneral"),
    )

    for headers in probes:
        response = api.list_plan_years(headers)
        error = validate_error(
            response, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
        assert response.status_code != 403

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert isinstance(error["message"], str) and error["message"]


def test_pagination_bounds_are_inclusive_and_out_of_range_is_refused(api):
    """0, 101 and -1 are refused; 1 and 100 are the accepted extremes.

    PRD 2.3: "A `limit` that is not an integer in the inclusive range 1 through
    100, or an `offset` that is not an integer of at least 0, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)." PRD 2.8 rung 13 puts that on "every
    list endpoint". The accepted calls must still report the whole set, because
    PRD 2.3 says "`total_count` reports the number of rows matching the filters
    before the page window is applied, and `has_more` is true when rows remain
    beyond the current window."

    Design: Corner/validations/pagination_limit_and_offset_out_of_range_rejected
    """
    fx.make_retiree_r1(api)
    analyst = make_eligibility_analyst_headers(ANALYST_1)

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_retirees(analyst, params),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            expected_status=400,
        )

    for limit in (1, 100):
        rows, meta = validate_paginated(api.list_retirees(analyst, {"limit": limit}))
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == limit
        assert meta["offset"] == 0


def test_both_uniqueness_keys_are_refused_and_the_plan_code_key_is_scoped(api):
    """A duplicate year, a duplicate code in the same year, and the same code next year.

    PRD 3.1: "a second registration of the same `year` is refused with
    `ERR_DUPLICATE_PLAN_YEAR`", and PRD 2.8 rung 41 says the rule is "No other
    plan year already carries the requested `year`" — the year alone, so a
    request differing in every other field is still a duplicate. PRD 3.1 scopes
    the option key instead: "Each carries a `plan_code` of 1 to 32 characters
    that must be unique within its `plan_year_id`, a duplicate being refused with
    `ERR_DUPLICATE_PLAN_CODE`." So the same code under a different plan year is
    admitted. Neither refusal may touch the surviving 2027 row, whose `version`
    PRD 2.4 says "starts at 1 when the row is created".

    Design: Corner/validations/duplicate_plan_year_and_duplicate_plan_code_rejected
    """
    admin = make_benefits_admin_headers(ADMIN_1)
    year_2027 = fx.make_plan_year(api, year=2027)
    fx.make_pre65_core(api, year_2027["id"], activate=False)
    year_2028 = fx.make_plan_year(
        api,
        year=2028,
        overrides={
            "open_enrollment_start": "2027-10-15T00:00:00Z",
            "open_enrollment_end": "2027-11-15T00:00:00Z",
            "coverage_start": "2028-01-01T00:00:00Z",
        },
    )

    validate_error(
        api.create_plan_year(
            f.plan_year_payload(
                2027,
                overrides={
                    "open_enrollment_start": "2026-09-01T00:00:00Z",
                    "open_enrollment_end": "2026-09-30T00:00:00Z",
                    "coverage_start": "2027-02-01T00:00:00Z",
                    "hra_credit_pre_medicare_cents": 111111,
                    "hra_credit_medicare_cents": 222222,
                    "carryover_cap_pct": 0.25,
                    "discount_rate_bps": 400,
                    "assumed_annual_subsidy_cents": 190000,
                    "assumed_payment_years": 15,
                },
            ),
            admin,
        ),
        ApiErrorId.ERR_DUPLICATE_PLAN_YEAR.value,
        expected_status=409,
    )

    validate_error(
        api.create_plan_option(f.pre65_core_payload(year_2027["id"]), admin),
        ApiErrorId.ERR_DUPLICATE_PLAN_CODE.value,
        expected_status=409,
    )

    reused = validate_success(
        api.create_plan_option(f.pre65_core_payload(year_2028["id"]), admin),
        expected_status=201,
    )
    assert reused["plan_code"] == "PRE65-CORE"
    assert reused["plan_year_id"] == year_2028["id"]

    survivor = fx.reload_plan_year(api, year_2027["id"])
    assert_instant_equals(
        survivor["open_enrollment_start"],
        "2026-10-15T00:00:00.000Z",
        "open_enrollment_start",
    )
    assert survivor["hra_credit_pre_medicare_cents"] == 185000
    assert survivor["version"] == 1

    _rows, meta = validate_paginated(api.list_plan_years(admin))
    assert meta["total_count"] == 2


def test_a_second_account_for_the_same_retiree_and_year_is_refused_even_once_closed(api):
    """The uniqueness key ignores status, so closing the first does not free the slot.

    PRD 2.8 rung 43: "No reimbursement account already exists for the same
    retiree and plan year in any status, and any supplied `prior_year_account_id`
    belongs to the same retiree and references an earlier plan year →
    `ERR_DUPLICATE_HRA_ACCOUNT` (409), on reimbursement-account creation." PRD 3.7
    says the same thing from the other side: "Only one account may exist per
    retiree and plan year in any status". Closing the incumbent is a status move
    only — PRD 3.7: "Finally `status` moves from `OPEN` to `CLOSED`, `closed_at`
    is set to the logical clock, and the account's `version` increments." — so the
    retry is refused a second time and the original row keeps its funding inputs.

    Design: Corner/validations/duplicate_hra_account_for_same_retiree_and_year_rejected
    """
    funded = fx.hra_funded_retiree(
        api, covered_months=12, retiree_payload=f.retiree_r1_payload()
    )
    retiree_id = funded["retiree"]["id"]
    plan_year_id = funded["plan_year"]["id"]
    account_id = funded["hra_account"]["id"]
    hra_admin = make_hra_administrator_headers(HRA_ADMIN_1)

    validate_error(
        api.create_hra_account(
            f.hra_account_payload(retiree_id, plan_year_id, 6), hra_admin
        ),
        ApiErrorId.ERR_DUPLICATE_HRA_ACCOUNT.value,
        expected_status=409,
    )

    fx.set_clock(api, "2027-12-31T00:00:00Z")
    closed = fx.close_hra_year(api, account_id)
    assert closed["status"] == "CLOSED"

    validate_error(
        api.create_hra_account(
            f.hra_account_payload(retiree_id, plan_year_id, 6), hra_admin
        ),
        ApiErrorId.ERR_DUPLICATE_HRA_ACCOUNT.value,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api.list_hra_accounts(hra_admin, {"retiree_id": retiree_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == account_id
    assert rows[0]["covered_months"] == 12
    assert rows[0]["annual_credit_cents"] == 184992


def test_carrying_over_from_an_account_that_is_still_open_is_refused(api):
    """An open prior account has no final balance to inherit, so the create fails.

    PRD 3.7: "A supplied `prior_year_account_id` must additionally reference an
    account whose `status` is `CLOSED`, since an account that has not been closed
    has no final unused balance to inherit; anything else is refused with
    `ERR_PRIOR_HRA_ACCOUNT_NOT_CLOSED`." The rung above it is satisfied, because
    PRD 2.8 rung 43 asks only that the prior account "belongs to the same retiree
    and references an earlier plan year" and this one does both. PRD 2.4 keeps the
    untouched prior row at its creation `version`, which "starts at 1 when the row
    is created".

    Design: Corner/validations/prior_hra_account_still_open_rejected
    """
    fx.set_clock(api, "2026-11-01T00:00:00Z")
    year_2026 = fx.make_open_plan_year(
        api,
        year=2026,
        overrides={
            "open_enrollment_start": "2025-10-15T00:00:00Z",
            "open_enrollment_end": "2025-11-15T00:00:00Z",
            "coverage_start": "2026-01-01T00:00:00Z",
        },
    )
    year_2027 = fx.make_open_plan_year(api, year=2027)

    retiree = fx.make_retiree_r1(api)
    fx.make_determination(api, retiree, year_2026["id"], certify=True)
    retiree = fx.reload_retiree(api, retiree["id"])
    fx.make_determination(
        api,
        retiree,
        year_2027["id"],
        certify=True,
        creator_user_id=ANALYST_1,
        certifier_user_id=ANALYST_2,
    )

    prior = fx.make_hra_account(api, retiree["id"], year_2026["id"], 12)
    assert prior["status"] == "OPEN"

    hra_admin = make_hra_administrator_headers(HRA_ADMIN_1)
    validate_error(
        api.create_hra_account(
            f.hra_account_payload(
                retiree["id"], year_2027["id"], 12, prior_year_account_id=prior["id"]
            ),
            hra_admin,
        ),
        ApiErrorId.ERR_PRIOR_HRA_ACCOUNT_NOT_CLOSED.value,
        expected_status=409,
    )

    _rows, meta = validate_paginated(
        api.list_hra_accounts(hra_admin, {"plan_year_id": year_2027["id"]})
    )
    assert meta["total_count"] == 0

    untouched = fx.reload_hra_account(api, prior["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["version"] == 1
    assert untouched["available_balance_cents"] == 184992


def test_the_expense_window_admits_its_endpoints_and_refuses_the_days_outside(api):
    """One day early and one day late are refused; both endpoint days are admitted.

    PRD 3.7: "The `service_date` must fall inside the account's plan-year expense
    window, which runs from the plan year's `coverage_start` through one year
    later minus one day, inclusive at both ends; an expense outside it is refused
    with `ERR_EXPENSE_OUTSIDE_PLAN_YEAR`." For a plan year whose `coverage_start`
    is 2027-01-01 that window is 2027-01-01 through 2027-12-31, so 2026-12-31 and
    2028-01-01 both fall outside it. PRD 2.6 fixes the comparison: the date-only
    fields "are `YYYY-MM-DD` calendar dates and are compared as calendar dates."
    Each admitted claim moves money, so PRD 2.5 requires the next one to carry the
    account's new `version` as "the client's last observed `version` of the target
    `HraAccount`".

    Design: Corner/validations/claim_service_date_outside_plan_year_rejected
    """
    funded = fx.hra_funded_retiree(
        api, covered_months=12, retiree_payload=f.retiree_r1_payload()
    )
    account = funded["hra_account"]
    retiree_id = funded["retiree"]["id"]
    assert account["funded_cents"] == 184992

    fx.set_clock(api, "2028-06-01T00:00:00Z")
    retiree_headers = make_retiree_headers(retiree_id)

    for outside in ("2026-12-31", "2028-01-01"):
        validate_error(
            api.create_claim(
                f.claim_payload(
                    account["id"],
                    account["version"],
                    service_date=outside,
                    submitted_cents=10000,
                ),
                retiree_headers,
            ),
            ApiErrorId.ERR_EXPENSE_OUTSIDE_PLAN_YEAR.value,
            expected_status=422,
        )

    unchanged = fx.reload_hra_account(api, account["id"])
    assert unchanged["version"] == 1
    assert unchanged["available_balance_cents"] == 184992

    for inside in ("2027-01-01", "2027-12-31"):
        current = fx.reload_hra_account(api, account["id"])
        admitted = fx.make_claim(
            api,
            current,
            retiree_id,
            service_date=inside,
            submitted_cents=10000,
            documentation_reference="EOB-" + inside,
        )
        assert admitted["status"] == "SUBMITTED"
        assert admitted["service_date"] == inside
        assert admitted["provisional_eligible_cents"] == 10000

    final = fx.reload_hra_account(api, account["id"])
    assert final["version"] == 3
    assert final["pending_hold_cents"] == 20000
    assert final["available_balance_cents"] == 164992
    assert_hra_ledger_conservation(final)

    _claims, claim_meta = validate_paginated(
        api.list_claims(
            make_hra_administrator_headers(HRA_ADMIN_1),
            {"hra_account_id": account["id"]},
        )
    )
    assert claim_meta["total_count"] == 2


def test_part_b_starting_after_coverage_begins_is_refused_but_the_same_day_is_admitted(api):
    """Part B on the coverage start date qualifies; a Part B five months later does not.

    PRD 2.8 rung 34: "When the option's `requires_medicare_part_b` is true, the
    retiree's `medicare_part_b_effective_date` is non-null and not later than the
    election's `coverage_effective_date` → `ERR_MEDICARE_PART_B_REQUIRED` (422),
    on election-event creation." PRD 3.5 states the test the same way — "must be
    non-null and must not fall after the election's computed
    `coverage_effective_date`; otherwise `ERR_MEDICARE_PART_B_REQUIRED`" — and
    fixes the date being compared against: "Its `coverage_effective_date` is the
    plan year's `coverage_start`." The rung above it passes, because PRD 3.5 says
    "a retiree whose `medicare_status` is `MEDICARE_ENROLLED` may elect only a
    `MEDICARE_GROUP_WRAP` or an `INDIVIDUAL_EXCHANGE_HRA` option".

    Design: Corner/validations/medicare_part_b_effective_after_coverage_start_rejected
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    med_wrap = fx.make_med_wrap(api, plan_year["id"])
    assert med_wrap["requires_medicare_part_b"] is True

    late = fx.make_certified_retiree(
        api,
        plan_year["id"],
        f.retiree_r2_payload(overrides={"medicare_part_b_effective_date": "2027-06-01"}),
    )
    on_time = fx.make_certified_retiree(
        api,
        plan_year["id"],
        f.retiree_r2_payload(
            overrides={
                "full_name": "Yolanda Bright",
                "medicare_part_b_effective_date": "2027-01-01",
            }
        ),
    )
    assert late["retiree"]["eligibility_status"] == "ELIGIBLE"
    assert on_time["retiree"]["eligibility_status"] == "ELIGIBLE"

    counselor = make_enrollment_counselor_headers(COUNSELOR_1)
    refused = validate_error(
        api.create_election_event(
            f.election_event_payload(
                late["retiree"]["id"],
                plan_year["id"],
                med_wrap["id"],
                "ANNUAL_OPEN",
                "2026-10-20",
            ),
            counselor,
        ),
        ApiErrorId.ERR_MEDICARE_PART_B_REQUIRED.value,
        expected_status=422,
    )
    assert refused["error_id"] != ApiErrorId.ERR_PLAN_CLASS_MISMATCH.value

    _refused_rows, refused_meta = validate_paginated(
        api.list_election_events(counselor, {"retiree_id": late["retiree"]["id"]})
    )
    assert refused_meta["total_count"] == 0

    admitted = validate_success(
        api.create_election_event(
            f.election_event_payload(
                on_time["retiree"]["id"],
                plan_year["id"],
                med_wrap["id"],
                "ANNUAL_OPEN",
                "2026-10-20",
            ),
            counselor,
        ),
        expected_status=201,
    )
    assert admitted["status"] == "SUBMITTED"
    assert_instant_equals(
        admitted["coverage_effective_date"],
        "2027-01-01T00:00:00.000Z",
        "coverage_effective_date",
    )


def test_a_cohort_outside_the_options_allowed_list_is_refused(api):
    """One option, two eligible retirees, and only the permitted cohort gets in.

    PRD 2.8 rung 35: "The retiree's `grandfathered_group` appears in the option's
    `allowed_grandfather_groups` → `ERR_GRANDFATHER_GROUP_NOT_PERMITTED` (422),
    on election-event creation." PRD 3.5 places it last of the three referential
    checks: "Third, the retiree's `grandfathered_group` must appear in the
    option's `allowed_grandfather_groups`, or the election is refused with
    `ERR_GRANDFATHER_GROUP_NOT_PERMITTED`." The cohorts come from PRD 3.3:
    "Otherwise, a retiree hired strictly before 1 January 2005 is a
    `TRANSITION_B`." So a 1998 hire is refused on an option that admits
    `GRANDFATHERED_A` alone, while a 1990 hire on the same option is admitted.

    Design: Corner/validations/grandfather_group_absent_from_allowed_list_rejected
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    a_group_only = fx.make_plan_option(
        api,
        f.plan_option_payload(
            plan_year["id"],
            plan_code="AGRP-ONLY",
            allowed_grandfather_groups=["GRANDFATHERED_A"],
        ),
    )
    assert a_group_only["allowed_grandfather_groups"] == ["GRANDFATHERED_A"]

    transition_b = fx.make_certified_retiree(
        api, plan_year["id"], f.retiree_r5_payload()
    )
    grandfathered_a = fx.make_certified_retiree(
        api, plan_year["id"], f.retiree_r1_payload()
    )
    assert transition_b["retiree"]["grandfathered_group"] == "TRANSITION_B"
    assert transition_b["retiree"]["eligibility_status"] == "ELIGIBLE"
    assert grandfathered_a["retiree"]["grandfathered_group"] == "GRANDFATHERED_A"

    counselor = make_enrollment_counselor_headers(COUNSELOR_1)
    refused = validate_error(
        api.create_election_event(
            f.election_event_payload(
                transition_b["retiree"]["id"],
                plan_year["id"],
                a_group_only["id"],
                "ANNUAL_OPEN",
                "2026-10-20",
            ),
            counselor,
        ),
        ApiErrorId.ERR_GRANDFATHER_GROUP_NOT_PERMITTED.value,
        expected_status=422,
    )
    assert refused["error_id"] != ApiErrorId.ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL.value

    _rows, refused_meta = validate_paginated(
        api.list_election_events(
            counselor, {"retiree_id": transition_b["retiree"]["id"]}
        )
    )
    assert refused_meta["total_count"] == 0

    admitted = validate_success(
        api.create_election_event(
            f.election_event_payload(
                grandfathered_a["retiree"]["id"],
                plan_year["id"],
                a_group_only["id"],
                "ANNUAL_OPEN",
                "2026-10-20",
            ),
            counselor,
        ),
        expected_status=201,
    )
    assert admitted["status"] == "SUBMITTED"
    assert admitted["requested_plan_option_id"] == a_group_only["id"]


def test_an_option_still_in_draft_cannot_be_elected_until_it_is_activated(api):
    """The same payload is refused before activation and admitted after it.

    PRD 2.8 rung 18: "The target plan option's `status` is `ACTIVE` →
    `ERR_PLAN_OPTION_NOT_ACTIVE` (409), on plan-change-notice issuance and on
    election-event creation." PRD 3.5 repeats the pairing: "The plan year must
    be `OPEN` and the requested option must be `ACTIVE`, refused with
    `ERR_PLAN_YEAR_NOT_OPEN` and `ERR_PLAN_OPTION_NOT_ACTIVE` respectively." The
    remedy is the one hop PRD 3.1 declares: "Activation moves `status` from
    `DRAFT` to `ACTIVE` and is permitted only while the owning plan year is in
    `DRAFT` or `OPEN`."

    Design: Corner/validations/election_on_draft_plan_option_rejected
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    option = fx.make_pre65_core(api, plan_year["id"], activate=False)
    assert option["status"] == "DRAFT"

    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]
    counselor = make_enrollment_counselor_headers(COUNSELOR_1)
    payload = f.election_event_payload(
        retiree_id, plan_year["id"], option["id"], "ANNUAL_OPEN", "2026-10-20"
    )

    validate_error(
        api.create_election_event(dict(payload), counselor),
        ApiErrorId.ERR_PLAN_OPTION_NOT_ACTIVE.value,
        expected_status=409,
    )

    _rows, meta = validate_paginated(
        api.list_election_events(counselor, {"retiree_id": retiree_id})
    )
    assert meta["total_count"] == 0

    activated = validate_success(
        api.activate_plan_option(option["id"], make_benefits_admin_headers(ADMIN_1))
    )
    assert activated["status"] == "ACTIVE"

    admitted = validate_success(
        api.create_election_event(dict(payload), counselor), expected_status=201
    )
    assert admitted["status"] == "SUBMITTED"


def test_the_life_event_window_admits_its_last_day_and_refuses_the_next(api):
    """Day 31 after the event is inside the window; day 32 is not.

    PRD 2.8 rung 32: "For a qualifying life event the logical clock lies inside
    the life-event window → `ERR_LIFE_EVENT_WINDOW_EXPIRED` (422), on
    election-event creation." PRD 2.9 fixes both endpoints: "it runs from the
    event date at midnight UTC through that instant plus 31 days, inclusive of
    both endpoints." PRD 3.5 writes the deadline onto the row — "For any of the
    four qualifying life events, `window_deadline` is the `event_date` taken at
    midnight UTC plus 31 days" — and pins the coverage date to the following
    month: "Its `coverage_effective_date` is the first day of the calendar month".
    The annual rung above cannot be the one firing, because rung 31 is scoped to
    "For an `ANNUAL_OPEN` election the logical clock lies inside the annual
    window".

    Design: Corner/validations/life_event_window_one_day_past_deadline_rejected
    """
    program = fx.standard_program(api)
    plan_year = program["plan_year"]
    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]
    counselor = make_enrollment_counselor_headers(COUNSELOR_1)
    payload = f.election_event_payload(
        retiree_id, plan_year["id"], program["pre65_core"]["id"], "MARRIAGE", "2027-02-05"
    )

    fx.set_clock(api, "2027-03-08T00:00:00Z")
    admitted = validate_success(
        api.create_election_event(dict(payload), counselor), expected_status=201
    )
    assert admitted["event_type"] == "MARRIAGE"
    assert admitted["status"] == "SUBMITTED"
    assert_instant_equals(
        admitted["window_deadline"], "2027-03-08T00:00:00.000Z", "window_deadline"
    )
    assert_instant_equals(
        admitted["coverage_effective_date"],
        "2027-03-01T00:00:00.000Z",
        "coverage_effective_date",
    )

    fx.set_clock(api, "2027-03-09T00:00:00Z")
    refused = validate_error(
        api.create_election_event(dict(payload), counselor),
        ApiErrorId.ERR_LIFE_EVENT_WINDOW_EXPIRED.value,
        expected_status=422,
    )
    assert refused["error_id"] != ApiErrorId.ERR_ELECTION_WINDOW_CLOSED.value

    rows, meta = validate_paginated(
        api.list_election_events(counselor, {"retiree_id": retiree_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == admitted["id"]


def test_reinstatement_one_day_after_the_deadline_is_refused(api):
    """Three unpaid periods lapse the coverage; the buy-back window then closes.

    PRD 3.9 hop four sets the deadline: "`billing_status` moves from `DELINQUENT`
    to `LAPSED`, `lapse_date` is set to the logical clock, and
    `reinstatement_deadline` is set to the clock plus the plan year's
    `reinstatement_window_days`." and in the same hop "every `PAST_DUE` invoice on
    the enrollment moves to `WRITTEN_OFF` in `created_at` ascending order".
    PRD 2.9: "reinstatement is permitted while the logical clock is not later than
    `reinstatement_deadline`." PRD 3.8 names the refusal: "The logical clock must
    not be later than the enrollment's `reinstatement_deadline`, or the request is
    refused with `ERR_REINSTATEMENT_WINDOW_EXPIRED`." The rung above it is
    satisfied, because PRD 3.8 also requires that "The enrollment must sit in
    `coverage_status` `TERMINATED` with `billing_status` `LAPSED`" and it does.

    Design: Corner/validations/reinstatement_one_day_past_deadline_rejected
    """
    enrolled = fx.enrolled_retiree(api, retiree_payload=f.retiree_r1_payload())
    enrollment_id = enrolled["enrollment"]["id"]
    option_id = enrolled["pre65_core"]["id"]

    invoices = [
        fx.make_invoice(api, enrollment_id, "2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"),
        fx.make_invoice(api, enrollment_id, "2027-02-01T00:00:00Z", "2027-02-28T00:00:00Z"),
        fx.make_invoice(api, enrollment_id, "2027-03-01T00:00:00Z", "2027-03-31T00:00:00Z"),
    ]
    for invoice in invoices:
        assert invoice["status"] == "ISSUED"
        assert invoice["net_due_cents"] == 15422

    fx.set_clock(api, "2027-06-01T00:00:00Z")
    counters = fx.run_daily(api)
    assert counters["activated_enrollment_count"] == 1
    assert counters["processed_invoice_count"] == 3
    assert counters["lapsed_enrollment_count"] == 1

    lapsed = fx.reload_enrollment(api, enrollment_id)
    assert lapsed["billing_status"] == "LAPSED"
    assert lapsed["coverage_status"] == "TERMINATED"
    assert lapsed["consecutive_unpaid_periods"] == 3
    assert_instant_equals(
        lapsed["reinstatement_deadline"],
        "2027-07-31T00:00:00.000Z",
        "reinstatement_deadline",
    )
    for invoice in invoices:
        assert fx.reload_invoice(api, invoice["id"])["status"] == "WRITTEN_OFF"
    assert fx.reload_plan_option(api, option_id)["enrolled_count"] == 0

    fx.set_clock(api, "2027-08-01T00:00:00Z")
    refused = validate_error(
        api.reinstate_enrollment(enrollment_id, make_billing_clerk_headers(BILLING_1)),
        ApiErrorId.ERR_REINSTATEMENT_WINDOW_EXPIRED.value,
        expected_status=422,
    )
    assert refused["error_id"] != ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value

    after = fx.reload_enrollment(api, enrollment_id)
    assert after["billing_status"] == "LAPSED"
    assert after["reinstatement_count"] == 0
    assert fx.reload_plan_option(api, option_id)["enrolled_count"] == 0


def test_a_past_due_invoice_on_another_enrollment_blocks_reinstatement(api):
    """The arrears sit on a terminated enrollment, and they still block the buy-back.

    PRD 3.8: "And the retiree must not be carrying a `PAST_DUE` invoice with a
    non-zero outstanding balance on any *other* enrollment, since buying back one
    coverage while another is in arrears would let a retiree cherry-pick which
    debt to service; such a request is refused with
    `ERR_OUTSTANDING_PREMIUM_BALANCE`." The arrears survive the manual
    termination, because PRD 3.5 says termination "moves every `ISSUED` or
    `PARTIALLY_PAID` invoice of that enrollment to `WRITTEN_OFF`" and this invoice
    is neither. The refusal is not the window rung, because PRD 2.8 rung 39 asks
    only that "The logical clock is not later than the enrollment's
    `reinstatement_deadline`" and it is not.

    Design: Corner/validations/outstanding_past_due_invoice_on_another_enrollment_rejected
    """
    fx.set_clock(api, "2025-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(
        api,
        year=2026,
        overrides={
            "open_enrollment_start": "2025-10-15T00:00:00Z",
            "open_enrollment_end": "2025-11-15T00:00:00Z",
            "coverage_start": "2026-01-01T00:00:00Z",
        },
    )
    option = fx.make_pre65_core(api, plan_year["id"])
    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]

    first = fx.make_enrollment(
        api, retiree_id, plan_year["id"], option["id"], "ANNUAL_OPEN", "2025-10-20"
    )["enrollment"]
    arrears = fx.make_invoice(
        api, first["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z"
    )

    fx.set_clock(api, "2026-03-03T00:00:00Z")
    fx.run_daily(api)
    arrears = fx.reload_invoice(api, arrears["id"])
    assert arrears["status"] == "PAST_DUE"
    assert arrears["net_due_cents"] == 15422
    assert arrears["paid_cents"] == 0

    abandoned = fx.terminate_enrollment(api, first["id"])
    assert abandoned["coverage_status"] == "TERMINATED"
    assert_instant_equals(
        abandoned["coverage_end_date"], "2026-03-03T00:00:00.000Z", "coverage_end_date"
    )
    assert fx.reload_invoice(api, arrears["id"])["status"] == "PAST_DUE"

    fx.set_clock(api, "2026-03-05T00:00:00Z")
    second = fx.make_enrollment(
        api,
        retiree_id,
        plan_year["id"],
        option["id"],
        "LOSS_OF_OTHER_COVERAGE",
        "2026-03-05",
    )["enrollment"]
    assert_instant_equals(
        second["coverage_effective_date"],
        "2026-04-01T00:00:00.000Z",
        "coverage_effective_date",
    )

    second_invoices = [
        fx.make_invoice(api, second["id"], "2026-04-01T00:00:00Z", "2026-04-30T00:00:00Z"),
        fx.make_invoice(api, second["id"], "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z"),
        fx.make_invoice(api, second["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z"),
    ]

    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.run_daily(api)
    lapsed = fx.reload_enrollment(api, second["id"])
    assert lapsed["billing_status"] == "LAPSED"
    assert lapsed["coverage_status"] == "TERMINATED"
    assert_instant_equals(
        lapsed["reinstatement_deadline"],
        "2026-09-30T00:00:00.000Z",
        "reinstatement_deadline",
    )
    for invoice in second_invoices:
        assert fx.reload_invoice(api, invoice["id"])["status"] == "WRITTEN_OFF"

    fx.set_clock(api, "2026-08-15T00:00:00Z")
    refused = validate_error(
        api.reinstate_enrollment(second["id"], make_billing_clerk_headers(BILLING_1)),
        ApiErrorId.ERR_OUTSTANDING_PREMIUM_BALANCE.value,
        expected_status=409,
    )
    assert refused["error_id"] != ApiErrorId.ERR_REINSTATEMENT_WINDOW_EXPIRED.value

    after = fx.reload_enrollment(api, second["id"])
    assert after["billing_status"] == "LAPSED"
    assert after["reinstatement_count"] == 0
    assert fx.reload_plan_option(api, option["id"])["enrolled_count"] == 0


def test_a_claim_against_an_account_drawn_to_zero_is_refused(api):
    """Zero covered months funds nothing, and nothing cannot hold a hold.

    PRD 3.7: "And the account's `available_balance_cents` must be strictly greater
    than zero, so that at least part of the expense can be held; an account
    already drawn to zero refuses the claim with `ERR_HRA_BALANCE_INSUFFICIENT`."
    An account may legitimately be funded at zero, because `covered_months`
    "must be between 0 and 12 inclusive". A single covered month proves the rung
    is about the balance and not about the claim size, since PRD 3.7 caps rather
    than refuses: "`provisional_eligible_cents` is the lesser of `submitted_cents`
    and the account's `available_balance_cents`, `eligible_cents` is set to that
    same figure".

    Design: Corner/validations/claim_against_zero_balance_account_rejected
    """
    fx.set_clock(api, "2026-11-01T00:00:00Z")
    year_2027 = fx.make_open_plan_year(api, year=2027)
    year_2028 = fx.make_open_plan_year(
        api,
        year=2028,
        overrides={
            "open_enrollment_start": "2027-10-15T00:00:00Z",
            "open_enrollment_end": "2027-11-15T00:00:00Z",
            "coverage_start": "2028-01-01T00:00:00Z",
        },
    )

    retiree = fx.make_retiree_r1(api)
    fx.make_determination(api, retiree, year_2027["id"], certify=True)
    retiree = fx.reload_retiree(api, retiree["id"])
    fx.make_determination(api, retiree, year_2028["id"], certify=True)
    retiree_id = retiree["id"]

    empty = fx.make_hra_account(api, retiree_id, year_2027["id"], 0)
    assert empty["funded_cents"] == 0
    assert empty["available_balance_cents"] == 0

    one_month = fx.make_hra_account(api, retiree_id, year_2028["id"], 1)
    assert one_month["funded_cents"] == 15416

    retiree_headers = make_retiree_headers(retiree_id)
    fx.set_clock(api, "2027-06-01T00:00:00Z")
    validate_error(
        api.create_claim(
            f.claim_payload(
                empty["id"], empty["version"], service_date="2027-06-01", submitted_cents=1
            ),
            retiree_headers,
        ),
        ApiErrorId.ERR_HRA_BALANCE_INSUFFICIENT.value,
        expected_status=422,
    )

    untouched = fx.reload_hra_account(api, empty["id"])
    assert untouched["version"] == 1
    assert untouched["available_balance_cents"] == 0

    hra_admin = make_hra_administrator_headers(HRA_ADMIN_1)
    _rows, empty_meta = validate_paginated(
        api.list_claims(hra_admin, {"hra_account_id": empty["id"]})
    )
    assert empty_meta["total_count"] == 0

    fx.set_clock(api, "2028-06-01T00:00:00Z")
    capped = validate_success(
        api.create_claim(
            f.claim_payload(
                one_month["id"],
                one_month["version"],
                service_date="2028-06-01",
                submitted_cents=90000,
            ),
            retiree_headers,
        ),
        expected_status=201,
    )
    assert capped["status"] == "SUBMITTED"
    assert capped["submitted_cents"] == 90000
    assert capped["provisional_eligible_cents"] == 15416
    assert capped["eligible_cents"] == 15416

    drawn = fx.reload_hra_account(api, one_month["id"])
    assert drawn["available_balance_cents"] == 0
    assert drawn["pending_hold_cents"] == 15416
    assert_hra_ledger_conservation(drawn)


def test_neither_settlement_action_touches_a_claim_still_awaiting_review(api):
    """PAY wants APPROVED and REVERSE wants PAID, so a SUBMITTED claim gets neither.

    PRD 2.8 rung 23 spells both preconditions out: "settlement by payment requires
    `APPROVED`, and settlement by reversal requires `PAID` →
    `ERR_INVALID_CLAIM_STATE` (409)". PRD 3.7 states them again: "`PAY` requires `status` `APPROVED` and moves
    it to `PAID`" while "`REVERSE` requires `status` `PAID` and moves it to
    `REVERSED`, clears `paid_at`". The hold placed at submission must survive both
    refusals, and PRD 2.10 requires it to stay accounted for: "`funded_cents`
    equals the sum of five buckets: `available_balance_cents`,
    `pending_hold_cents`, `substantiated_paid_cents`, `premium_offset_cents` and
    `forfeited_cents`."

    Design: Corner/validations/settlement_on_submitted_claim_rejected
    """
    funded = fx.hra_funded_retiree(
        api, covered_months=12, retiree_payload=f.retiree_r1_payload()
    )
    account = funded["hra_account"]
    retiree_id = funded["retiree"]["id"]

    fx.set_clock(api, "2027-06-01T00:00:00Z")
    claim = fx.make_claim(
        api, account, retiree_id, service_date="2027-06-01", submitted_cents=40000
    )
    assert claim["status"] == "SUBMITTED"

    billing = make_billing_clerk_headers(BILLING_1)
    for action in ("PAY", "REVERSE"):
        validate_error(
            api.settle_claim(claim["id"], f.claim_settlement_payload(action), billing),
            ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
            expected_status=409,
        )

    unchanged = fx.reload_claim(api, claim["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["paid_at"] is None
    assert unchanged["eligible_cents"] == 40000

    ledger = fx.reload_hra_account(api, account["id"])
    assert ledger["version"] == 2
    assert ledger["pending_hold_cents"] == 40000
    assert ledger["substantiated_paid_cents"] == 0
    assert ledger["available_balance_cents"] == 144992
    assert_hra_ledger_conservation(ledger)


def test_reinstating_coverage_that_never_lapsed_is_refused(api):
    """An ACTIVE, current enrollment has nothing to buy back.

    PRD 3.8: "The enrollment must sit in `coverage_status` `TERMINATED` with
    `billing_status` `LAPSED`, or the request is refused with
    `ERR_INVALID_ENROLLMENT_STATE`." Activation alone does not touch billing,
    because PRD 3.9 phase 1 says of each activated enrollment: "Its
    `billing_status` is untouched." And the window rung cannot be the one firing,
    because PRD 3.5 opens a fresh enrollment with "`lapse_date`,
    `reinstatement_deadline` and `reinstatement_count` start at null, null, null
    and 0 respectively" — there is no deadline to be past.

    Design: Corner/validations/reinstate_of_active_enrollment_rejected
    """
    enrolled = fx.enrolled_retiree(api, retiree_payload=f.retiree_r1_payload())
    enrollment_id = enrolled["enrollment"]["id"]
    option_id = enrolled["pre65_core"]["id"]
    assert enrolled["enrollment"]["coverage_status"] == "PENDING"

    fx.set_clock(api, "2027-01-05T00:00:00Z")
    counters = fx.run_daily(api)
    assert counters["activated_enrollment_count"] == 1

    active = fx.reload_enrollment(api, enrollment_id)
    assert active["coverage_status"] == "ACTIVE"
    assert active["billing_status"] == "CURRENT"
    assert active["reinstatement_deadline"] is None

    refused = validate_error(
        api.reinstate_enrollment(enrollment_id, make_billing_clerk_headers(BILLING_1)),
        ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value,
        expected_status=409,
    )
    assert refused["error_id"] != ApiErrorId.ERR_REINSTATEMENT_WINDOW_EXPIRED.value

    after = fx.reload_enrollment(api, enrollment_id)
    assert after["coverage_status"] == "ACTIVE"
    assert after["billing_status"] == "CURRENT"
    assert after["reinstatement_count"] == 0
    assert after["version"] == active["version"]
    assert fx.reload_plan_option(api, option_id)["enrolled_count"] == 1


def test_an_unknown_plan_year_id_outranks_the_bad_transition_in_the_same_body(api):
    """The same malformed body earns a 404 on a missing row and a 400 on a real one.

    PRD 2.8: "When a single request violates more than one rule, the rule that
    appears earliest in the following ladder produces the response, and no later
    rule is evaluated or reported." Rung 3 comes first — "A `plan_year_id` in the
    path or body resolves to an existing plan year → `ERR_PLAN_YEAR_NOT_FOUND`
    (404)" — ahead of rung 12's requirement that "every enum field carries a
    declared member". `SUSPENDED` is not a declared member, because PRD 3.1 fixes
    the chain: "Its lifecycle is a strict single-successor chain, driven by a
    `BenefitsAdmin` supplying a `to_status`: `DRAFT → OPEN`, then `OPEN → CLOSED`,
    then `CLOSED → ARCHIVED`." So the shape refusal is a 400 and never the 409 of
    rung 16.

    Design: Corner/validations/existence_check_precedes_request_shape_check_not_found
    """
    plan_year = fx.make_plan_year(api, year=2027)
    admin = make_benefits_admin_headers(ADMIN_1)
    bad_body = f.plan_year_status_payload("SUSPENDED")

    missing = api.set_plan_year_status(NON_EXISTENT_UUID, dict(bad_body), admin)
    validate_error(
        missing, ApiErrorId.ERR_PLAN_YEAR_NOT_FOUND.value, expected_status=404
    )
    assert missing.status_code != 400
    assert missing.status_code != 409

    present = api.set_plan_year_status(plan_year["id"], dict(bad_body), admin)
    validate_error(present, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    untouched = fx.reload_plan_year(api, plan_year["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["version"] == 1


def test_an_election_that_clears_every_gate_is_created_and_creates_nothing_else(api):
    """The whole ladder satisfied: one SUBMITTED election and no enrollment yet.

    PRD 3.5: "An admitted election is created with `status` `SUBMITTED`,
    `submitted_at` set to the logical clock, `created_by_user_id` set to the
    submitting user's `X-User-ID`, `denial_reason_code` null and
    `resulting_enrollment_id` null." The two computed dates come from the annual
    branch: "For an `ANNUAL_OPEN` election, `window_deadline` is the plan year's
    `open_enrollment_end`" and "Its `coverage_effective_date` is the plan year's
    `coverage_start`." No coverage exists yet, because only the decision creates
    it: "A surviving approval moves `status` from `UNDER_REVIEW` to `APPROVED` and
    materialises exactly one enrollment."

    Design: Corner/validations/election_creation_with_every_check_satisfied_succeeds
    """
    program = fx.standard_program(api)
    plan_year = program["plan_year"]
    option = program["pre65_core"]
    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]
    counselor = make_enrollment_counselor_headers(COUNSELOR_1)

    data = validate_success(
        api.create_election_event(
            f.election_event_payload(
                retiree_id, plan_year["id"], option["id"], "ANNUAL_OPEN", "2026-10-20"
            ),
            counselor,
        ),
        expected_status=201,
    )

    assert data["status"] == "SUBMITTED"
    assert data["event_type"] == "ANNUAL_OPEN"
    assert data["retiree_id"] == retiree_id
    assert data["requested_plan_option_id"] == option["id"]
    assert data["event_date"] == "2026-10-20"
    assert data["created_by_user_id"] == COUNSELOR_1
    assert data["denial_reason_code"] is None
    assert data["resulting_enrollment_id"] is None
    assert data["version"] == 1
    assert_instant_equals(
        data["submitted_at"], "2026-10-20T00:00:00.000Z", "submitted_at"
    )
    assert_instant_equals(
        data["window_deadline"], "2026-11-15T00:00:00.000Z", "window_deadline"
    )
    assert_instant_equals(
        data["coverage_effective_date"],
        "2027-01-01T00:00:00.000Z",
        "coverage_effective_date",
    )

    _rows, meta = validate_paginated(
        api.list_enrollments(counselor, {"retiree_id": retiree_id})
    )
    assert meta["total_count"] == 0
    assert fx.reload_plan_option(api, option["id"])["enrolled_count"] == 0
