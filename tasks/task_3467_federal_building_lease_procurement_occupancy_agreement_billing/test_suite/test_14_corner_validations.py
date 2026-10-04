"""Corner coverage: validation rules — auth presence, existence-before-state,
cross-entity gates, term windows, uniqueness, and temporal boundaries."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, create_agency,
    create_leased_building, create_leased_oa, create_offer_payload,
    create_plan, create_requirement, generate_bill, get_success_data,
    set_clock, setup_active_leased_oa, setup_active_owned_oa,
    setup_commenced_lease, submit_requirement, validate_error,
    validate_paginated, validate_success, walk_requirement_to_soliciting,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
PM = TEST_USERS["gsa_property_manager_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. A request missing either header, or carrying an empty value
    in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    resp = api.create_agency({"bureau_code": "BUR-350", "name": "Forest Service"},
                             {})  # both auth headers omitted entirely
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_nonexistent_offer_select_returns_not_found_before_state(api):
    """PRD §2.10: "When a single request violates several rules, the violation
    with the lowest priority number produces the response; the checks are
    evaluated in this order:"
    PRD §2.10: "4. Existence of path and body identifiers, left to right —
    `ERR_NOT_FOUND` (404)."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Selecting a well-formed but nonexistent offer id hits existence (4) before
    any state check (6).

    Design: Corner/validations/nonexistent_offer_select_returns_not_found_before_state
    """
    resp = api.select_offer(NON_EXISTENT_UUID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_offer_create_before_solicitation_rejected(api):
    """PRD §3.3: "Submitting against a requirement that is not `SOLICITING` is
    rejected with `ERR_REQUIREMENT_NOT_SOLICITING`."

    The requirement is merely VALIDATED (market survey not completed).

    Design: Corner/validations/offer_create_before_solicitation_rejected
    """
    agency = create_agency()
    building = create_leased_building()
    set_clock("2026-10-01T00:00:00Z")
    req = create_requirement(agency)
    submit_requirement(req, agency)
    get_success_data(api.validate_requirement(req["id"], OFFICER))

    resp = api.create_offer(req["id"], create_offer_payload(building["id"]), LESSOR)
    validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_SOLICITING)
    offers, _ = validate_paginated(api.list_offers(
        OFFICER, params={"requirement_id": req["id"]}))
    assert offers == [], "no offer persisted"


def test_leased_oa_term_exceeding_lease_end_rejected(api):
    """PRD §3.5: "A leased agreement's window must lie within the lease's own
    term — no earlier than the lease's `commencement_date` and no later than
    its `end_date` — on pain of `ERR_OA_TERM_EXCEEDS_LEASE`"

    Design: Corner/validations/leased_oa_term_exceeding_lease_end_rejected
    """
    bundle = setup_commenced_lease()  # 2027-01-01 .. 2036-12-31
    resp = api.create_oa(
        {"lease_id": bundle["lease"]["id"], "agency_id": bundle["agency"]["id"],
         "assigned_sf": 10000, "start_date": "2027-01-01",
         "end_date": "2037-01-01"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_OA_TERM_EXCEEDS_LEASE)


def test_leased_oa_space_exactly_at_lease_capacity(api):
    """PRD §3.5: "on a lease the committed square feet across the lease's
    `DRAFT` and `ACTIVE` agreements must not exceed `leased_sf`
    (`ERR_LEASE_SPACE_EXCEEDED`)"

    Leased-space accounting admits equality: 50,000 + 18,300 == 68,300 fills
    the lease exactly; 50,000 + 18,301 is rejected.

    Design: Corner/validations/leased_oa_space_exactly_at_lease_capacity
    """
    bundle = setup_commenced_lease()
    lease, agency = bundle["lease"], bundle["agency"]
    create_leased_oa(lease, agency, assigned_sf=50000)

    over = api.create_oa(
        {"lease_id": lease["id"], "agency_id": agency["id"],
         "assigned_sf": 18301, "start_date": "2027-01-01",
         "end_date": "2036-12-31"}, OFFICER)
    validate_error(over, ApiErrorId.ERR_LEASE_SPACE_EXCEEDED)

    exact = validate_success(api.create_oa(
        {"lease_id": lease["id"], "agency_id": agency["id"],
         "assigned_sf": 18300, "start_date": "2027-01-01",
         "end_date": "2036-12-31"}, OFFICER), 201)
    assert exact["status"] == "DRAFT", "aggregate exactly 68,300 == leased_sf"


def test_bill_month_outside_term_rejected(api):
    """PRD §3.5: "the requested `billing_month`, in `YYYY-MM` form, must be
    unique for the agreement (`ERR_BILL_ALREADY_EXISTS`); and it must not fall
    before the lease's commencement month on a leased agreement nor after the
    agreement's own end month on any agreement (`ERR_BILL_MONTH_OUT_OF_TERM`)."

    Design: Corner/validations/bill_month_outside_term_rejected
    """
    bundle = setup_active_leased_oa(tax_year=None)  # term 2027-01 .. 2036-12
    oa = bundle["oa"]
    before = api.generate_bill(oa["id"], {"billing_month": "2026-12"}, PM)
    validate_error(before, ApiErrorId.ERR_BILL_MONTH_OUT_OF_TERM)
    after = api.generate_bill(oa["id"], {"billing_month": "2037-01"}, PM)
    validate_error(after, ApiErrorId.ERR_BILL_MONTH_OUT_OF_TERM)


def test_duplicate_bill_month_rejected(api):
    """PRD §3.5: "the requested `billing_month`, in `YYYY-MM` form, must be
    unique for the agreement (`ERR_BILL_ALREADY_EXISTS`)"

    Design: Corner/validations/duplicate_bill_month_rejected
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa = bundle["oa"]
    generate_bill(oa, "2027-04")
    resp = api.generate_bill(oa["id"], {"billing_month": "2027-04"}, PM)
    validate_error(resp, ApiErrorId.ERR_BILL_ALREADY_EXISTS)
    bills, meta = validate_paginated(api.list_bills(oa["id"], ADMIN))
    assert meta["total_count"] == 1


def test_duplicate_tax_year_statement_rejected(api):
    """PRD §3.4: "One statement per `tax_year` per lease: a duplicate year is
    rejected with `ERR_DUPLICATE_TAX_YEAR`."

    Design: Corner/validations/duplicate_tax_year_statement_rejected
    """
    bundle = setup_commenced_lease()
    lease = bundle["lease"]
    get_success_data(api.create_tax_statement(
        lease["id"], {"tax_year": 2027, "actual_tax_per_sf_yr_cents": 460},
        OFFICER))
    resp = api.create_tax_statement(
        lease["id"], {"tax_year": 2027, "actual_tax_per_sf_yr_cents": 470},
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAX_YEAR)
    lease_after = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert len(lease_after["tax_statements"]) == 1


def test_offer_expired_under_default_clock_without_any_set(api):
    """PRD §2.4: "The clock never falls back to wall-clock time: before any
    clock-setting call has been made, the logical clock reads exactly
    `2026-09-01T00:00:00Z`."
    PRD §3.3: "the offer's `valid_until` must not be earlier than the current
    logical clock (`ERR_OFFER_EXPIRED`)"

    No set_current_utc call is ever made: the pinned default governs, so an
    offer with valid_until 2026-08-31 is already expired at select.

    Design: Corner/validations/offer_expired_under_default_clock_without_any_set
    """
    agency = create_agency()
    building = create_leased_building()
    req = walk_requirement_to_soliciting(agency)  # clock untouched: 2026-09-01
    offer = get_success_data(api.create_offer(
        req["id"], create_offer_payload(
            building["id"], valid_until="2026-08-31T23:59:59Z"), LESSOR))
    get_success_data(api.evaluate_offer(offer["id"], OFFICER))

    resp = api.select_offer(offer["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
    req_after = validate_success(api.get_space_requirement(req["id"], OFFICER), 200)
    assert req_after["status"] == "SOLICITING"
    leases, _ = validate_paginated(api.list_leases(
        OFFICER, params={"requirement_id": req["id"]}))
    assert leases == []


def test_survey_measured_in_future_rejected(api):
    """PRD §3.8: "A `GSAPropertyManager` records one against an `ACTIVE`
    agreement (`ERR_OA_NOT_ACTIVE`), choosing a `method` of `SPACE_BASED` or
    `HEADCOUNT_BASED` and reporting the `measured_headcount` and `utilized_sf`
    observed (both zero or more) and a `measured_at` timestamp, which must not
    lie in the future of the logical clock (`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/survey_measured_in_future_rejected
    """
    bundle = setup_active_owned_oa()  # clock 2026-10-01
    resp = api.create_survey(
        bundle["oa"]["id"],
        {"method": "SPACE_BASED", "measured_headcount": 100,
         "utilized_sf": 12000, "measured_at": "2027-03-15T00:00:00Z"}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    surveys, meta = validate_paginated(api.list_surveys(bundle["oa"]["id"], ADMIN))
    assert surveys == [], "no survey persisted"


def test_second_open_plan_per_lease_rejected(api):
    """PRD §3.9: "A `GSALeasingOfficer` may open an expiration plan on any
    lease that is `COMMENCED` or `EXPIRING`; on a lease in any other state the
    attempt fails with `ERR_INVALID_STATE_TRANSITION`, and a lease that already
    has a plan in `OPEN` or `OPTION_SELECTED` refuses a second with
    `ERR_PLAN_ALREADY_OPEN`."

    Design: Corner/validations/second_open_plan_per_lease_rejected
    """
    bundle = setup_commenced_lease()
    lease = bundle["lease"]
    create_plan(lease)
    resp = api.create_expiration_plan(lease["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_OPEN)
    plans, meta = validate_paginated(api.list_expiration_plans(lease["id"], ADMIN))
    assert meta["total_count"] == 1


def test_select_option_deadline_boundary(api):
    """PRD §3.9: "The decision deadline is enforced first: the whole calendar
    months from the current date to the lease's `end_date` — twelve times the
    difference in years, plus the difference in months, minus one when the end
    date's day of month precedes the current day — must be at least twelve, or
    the selection fails with `ERR_OPTION_DEADLINE_PASSED`."

    At 2035-12-31 exactly 12 whole months remain to 2036-12-31 (allowed); at
    2036-01-01 only 11 remain (rejected).

    Design: Corner/validations/select_option_deadline_boundary
    """
    bundle_a = setup_commenced_lease()
    bundle_b = setup_commenced_lease()

    set_clock("2035-12-31T00:00:00Z")  # both leases sweep into EXPIRING
    plan_a = create_plan(bundle_a["lease"])
    plan_b = create_plan(bundle_b["lease"])

    selected = validate_success(api.select_plan_option(
        plan_a["id"], {
            "option": "SUCCEEDING_LEASE", "succeeding_shell_rate": 3200,
            "succeeding_operating_rate": 950, "succeeding_term_years": 10,
            "relocation_move_cost_cents": 50000000,
            "relocation_downtime_cost_cents": 0, "market_shell_rate": 3300,
            "market_operating_rate": 900, "construction_cost_cents": 5000000000,
            "construction_operating_rate": 700}, OFFICER), 200)
    assert selected["status"] == "OPTION_SELECTED", "12 whole months: allowed"

    set_clock("2036-01-01T00:00:00Z")
    resp = api.select_plan_option(
        plan_b["id"], {
            "option": "SUCCEEDING_LEASE", "succeeding_shell_rate": 3200,
            "succeeding_operating_rate": 950, "succeeding_term_years": 10,
            "relocation_move_cost_cents": 50000000,
            "relocation_downtime_cost_cents": 0, "market_shell_rate": 3300,
            "market_operating_rate": 900, "construction_cost_cents": 5000000000,
            "construction_operating_rate": 700}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_OPTION_DEADLINE_PASSED)
    plans, _ = validate_paginated(api.list_expiration_plans(
        bundle_b["lease"]["id"], ADMIN))
    assert plans[0]["status"] == "OPEN"
