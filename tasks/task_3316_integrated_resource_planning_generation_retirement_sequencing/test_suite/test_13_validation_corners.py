"""Validation corners: auth, existence, uniqueness, referential checks, temporal gates (PRD §2.1, §2.8, §3.1–§3.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_forecast,
    add_portfolio,
    add_position,
    compute_snapshot,
    create_candidate_payload,
    create_draft_plan_with_basics,
    create_forecast_payload,
    create_plan,
    create_plan_payload,
    create_testimony_payload,
    get_success_data,
    issue_commitment,
    list_plan_conditions,
    open_plan_for_comment,
    register_candidate,
    register_intervenor,
    register_resource,
    retire_resource,
    set_clock,
    setup_approved_plan,
    setup_plan_under_review,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01
from test_helpers.fixtures import PLANNER
from test_helpers.test_users import make_commissioner_headers, make_intervener_headers


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or presenting a role this API does
    not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "Authentication comes first (missing or undeclared credentials yield
    `ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_FORBIDDEN`), then
    existence of every path and body-referenced identifier (the 404 family, validated
    left to right), then optimistic-concurrency staleness (the 412 family) on the two
    guarded endpoints, then state gates (the 409 state family: plan-status gates, frozen
    portfolios, locked forecasts, commitment and testimony state), then temporal window
    checks (comment window, retirement lead time, cycle deadline, candidate online year,
    forecast horizon — the 422 temporal family), then structural uniqueness constraints
    (duplicate snapshot, report, forecast, preferred-portfolio conflict, duplicate
    names, nameplate overcommit, duplicate position), then cross-entity referential
    checks (eligible-candidate, snapshot-plan mismatch, intervenor standing, referential
    integrity), and finally the reliability and fiscal gates on plan transitions
    (preferred-portfolio presence, reliability met, reopen limit, base-forecast and
    portfolio presence)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    resp = api.get_plan(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_plan_not_found_returns_404(api):
    """PRD §2.8: "Nested paths are validated left to right: for a path naming a plan and
    then a child, the plan's existence is checked first (a missing plan yields
    `ERR_PLAN_NOT_FOUND`), and only then the child under that plan (a missing child
    yields the child-specific not-found error such as `ERR_FORECAST_NOT_FOUND`,
    `ERR_PORTFOLIO_NOT_FOUND`, or `ERR_COMMENT_NOT_FOUND`)."

    Design: Corner/validations/plan_not_found_returns_404
    """
    resp = api.get_plan(NON_EXISTENT_UUID, PLANNER)
    error_data = validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)
    assert resp.status_code == 404
    assert isinstance(error_data.get("message"), str) and error_data["message"]


def test_duplicate_forecast_triple_rejected(api):
    """PRD §3.1: "Within one plan, the combination of scenario tag and forecast year is
    unique: a second row repeating an existing pair is rejected with
    `ERR_DUPLICATE_FORECAST` (HTTP 409)."

    Design: Corner/validations/duplicate_forecast_triple_rejected
    """
    plan1 = create_plan(plan_name="IRP DupF1")
    plan2 = create_plan(plan_name="IRP DupF2")
    add_forecast(plan1["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=10)

    resp = api.create_forecast(
        plan1["id"],
        create_forecast_payload(scenario_tag="BASE", forecast_year=2030,
                                residential_mw=20),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FORECAST)

    resp = api.create_forecast(
        plan2["id"],
        create_forecast_payload(scenario_tag="BASE", forecast_year=2030,
                                residential_mw=20),
        PLANNER,
    )
    validate_success(resp, expected_status=201)


def test_preferred_portfolio_conflict_rejected(api):
    """PRD §3.3: "At most one portfolio per plan may hold the preferred flag; creating a
    second preferred portfolio under the same plan is rejected with
    `ERR_PREFERRED_PORTFOLIO_CONFLICT` (HTTP 409)."

    Design: Corner/validations/preferred_portfolio_conflict_rejected
    """
    plan = create_plan(plan_name="IRP Pref")
    add_portfolio(plan["id"], portfolio_name="PF-1", preferred_flag=True)

    resp = api.create_portfolio(
        plan["id"], {"portfolio_name": "PF-2", "preferred_flag": True}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_PREFERRED_PORTFOLIO_CONFLICT)

    resp = api.create_portfolio(
        plan["id"], {"portfolio_name": "PF-3", "preferred_flag": False}, PLANNER
    )
    validate_success(resp, expected_status=201)


def test_duplicate_candidate_name_rejected(api):
    """PRD §3.2: "Registering a candidate takes a globally unique, case-sensitive
    `candidate_name` — a duplicate registration is rejected with
    `ERR_DUPLICATE_CANDIDATE_NAME` (HTTP 409) — plus its `resource_type` and `fuel_type`
    from the same enumerations as fleet units (again, `STORAGE` and `DEMAND_RESPONSE`
    candidates must use `NONE`), a strictly positive `nameplate_mw` of offered capacity,
    an `online_year` of first availability that must be 2026 or later, a strictly
    positive overnight capital cost `capex_usd_per_kw`, a fixed operating cost
    `fixed_om_usd_per_kw_year` of zero or more, and a `build_lead_years` count of at
    least 1 from procurement commitment to online date."

    Design: Corner/validations/duplicate_candidate_name_rejected
    """
    register_candidate(candidate_name="K-DUP")

    resp = api.create_candidate(
        create_candidate_payload(candidate_name="K-DUP", resource_type="WIND",
                                 nameplate_mw=50, online_year=2029,
                                 capex_usd_per_kw=1100, fixed_om_usd_per_kw_year=20,
                                 fuel_type="WIND", build_lead_years=2),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CANDIDATE_NAME)

    # Uniqueness is case-sensitive: the lowercase variant is a distinct name.
    resp = api.create_candidate(
        create_candidate_payload(candidate_name="k-dup", resource_type="WIND",
                                 nameplate_mw=50, online_year=2029,
                                 capex_usd_per_kw=1100, fixed_om_usd_per_kw_year=20,
                                 fuel_type="WIND", build_lead_years=2),
        PLANNER,
    )
    validate_success(resp, expected_status=201)


def test_duplicate_position_rejected_and_readdable_after_soft_remove(api):
    """PRD §3.3: "A portfolio may hold at most one selected position per candidate:
    adding a position for a `(portfolio, candidate)` pair that already has a selected
    position is rejected with `ERR_DUPLICATE_POSITION` (HTTP 409)."
    PRD §3.3: "Removing a position is a soft removal: the row's `selected` flag flips to
    false, the row is retained for audit, and the owning portfolio's `version` bumps
    by 1."

    Design: Corner/validations/duplicate_position_rejected
    """
    plan = create_plan(plan_name="IRP DupP")
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-DupP")
    candidate = register_candidate(candidate_name="K-DUPP")
    position = add_position(portfolio["id"], candidate["id"], committed_mw=30)

    resp = api.add_position(
        portfolio["id"], {"candidate_id": candidate["id"], "committed_mw": 20}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_POSITION)

    removed = validate_success(api.remove_position(portfolio["id"], position["id"], PLANNER))
    assert removed["selected"] is False

    resp = api.add_position(
        portfolio["id"], {"candidate_id": candidate["id"], "committed_mw": 20}, PLANNER
    )
    validate_success(resp, expected_status=201)

    old_row = get_success_data(api.get_position(position["id"], PLANNER))
    assert old_row["selected"] is False


def test_intervenor_no_standing_rejected(api):
    """PRD §3.10: "Testimony is filed while a plan is `UNDER_REVIEW`, by the intervenor
    acting as itself: the caller's `X-User-ID` must equal the payload's `intervenor_id`,
    and a mismatch — or an intervenor whose `standing_approved` is false — is rejected
    with `ERR_INTERVENOR_NO_STANDING` (HTTP 422); a plan in the wrong status yields
    `ERR_PLAN_NOT_UNDER_REVIEW`."

    Design: Corner/validations/intervenor_no_standing_rejected
    """
    intervenor = register_intervenor(legal_name="No Standing Group",
                                     party_type="ENVIRONMENTAL_ORG",
                                     standing_approved=False)
    plan, _portfolio = setup_plan_under_review(plan_name="IRP Stand")

    resp = api.create_testimony(
        plan["id"],
        create_testimony_payload(intervenor["id"], topic="Standing",
                                 body="Should be rejected."),
        make_intervener_headers(intervenor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INTERVENOR_NO_STANDING)


def test_snapshot_plan_mismatch_on_analysis(api):
    """PRD §3.6: "Creating one names the `plan_id` of the draft plan the analysis
    attaches to and the `snapshot_id` whose fuel price and capacity margin feed it; the
    snapshot must belong to a portfolio of the same plan, or creation is rejected with
    `ERR_SNAPSHOT_PLAN_MISMATCH` (HTTP 422), and the analysis is born in `DRAFT`
    status."

    Design: Corner/validations/snapshot_plan_mismatch_on_analysis
    """
    plan1 = create_plan(plan_name="IRP M1")
    plan2 = create_plan(plan_name="IRP M2")
    add_forecast(plan1["id"], scenario_tag="BASE", forecast_year=2031, residential_mw=10)
    portfolio = add_portfolio(plan1["id"], portfolio_name="PF-M1", preferred_flag=True)
    resource = register_resource(unit_name="COAL-MM", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1985, fuel_type="COAL")
    retire_resource(resource["id"], retirement_year=2031, plan_id=plan1["id"])
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2031, scenario_tag="BASE")

    resp = api.create_retirement_analysis(
        resource["id"], {"plan_id": plan2["id"], "snapshot_id": snapshot["id"]}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_SNAPSHOT_PLAN_MISMATCH)


def test_invalid_request_missing_required_field(api):
    """PRD §3.1: "A `UtilityPlanner` begins a planning cycle by creating a resource
    plan, supplying a human-readable `plan_name`, the statutory `cycle_year` the plan is
    filed under, and a `planning_horizon_years` count of modeled calendar years that
    must be at least 10."
    PRD §3.7: "a signed `delta_pct` perturbation fraction (a value of 0.25 means a
    twenty-five percent increase) that must lie between negative 0.50 and positive 0.50
    inclusive; a delta outside that band is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/validations/invalid_request_missing_required_field
    """
    resp = api.create_plan({"plan_name": "IRP Bad"}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400

    resp = api.create_plan(
        {"plan_name": "IRP Bad2", "cycle_year": 2026, "planning_horizon_years": 5},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400


def test_cycle_deadline_missed_on_open_comment(api):
    """PRD §2.4: "The cycle filing deadline is September 1 of the plan's `cycle_year`:
    a plan that would be opened for comment with a `submitted_on` date after September 1
    of its `cycle_year` is rejected at open-comment time with
    `ERR_CYCLE_DEADLINE_MISSED` (HTTP 422)."

    Design: Corner/validations/cycle_deadline_missed_on_open_comment
    """
    set_clock("2026-08-20T00:00:00Z")
    plan1, _pf1 = create_draft_plan_with_basics(plan_name="IRP D1", preferred=False)
    plan2, _pf2 = create_draft_plan_with_basics(plan_name="IRP D2", preferred=False)

    set_clock("2026-09-01T00:00:00Z")
    opened = open_plan_for_comment(plan1["id"])
    assert opened["status"] == "OPEN_FOR_COMMENT"

    set_clock("2026-09-02T00:00:00Z")
    resp = api.open_comment(plan2["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_CYCLE_DEADLINE_MISSED)


def test_retirement_too_early_rejected(api):
    """PRD §3.4: "And the retirement year must be at least two full calendar years ahead
    of the logical clock's current calendar year (the minimum retirement lead); a nearer
    year is rejected with `ERR_RETIREMENT_TOO_EARLY` (HTTP 422)."

    Design: Corner/validations/retirement_too_early_rejected
    """
    plan = create_plan(plan_name="IRP Lead")
    resource1 = register_resource(unit_name="COAL-EARLY", resource_type="COAL",
                                  nameplate_mw=100, in_service_year=1990,
                                  fuel_type="COAL")
    resource2 = register_resource(unit_name="COAL-OK", resource_type="COAL",
                                  nameplate_mw=100, in_service_year=1990,
                                  fuel_type="COAL")

    # Default clock year is 2026: 2027 is one year short of the two-year lead.
    resp = api.retire_resource(
        resource1["id"], {"retirement_year": 2027, "plan_id": plan["id"]}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_RETIREMENT_TOO_EARLY)

    # 2028 == clock year + 2: the lead-time comparison is inclusive.
    decided = retire_resource(resource2["id"], retirement_year=2028, plan_id=plan["id"])
    assert decided["status"] == "DECIDED"
    assert decided["retirement_year"] == 2028


def test_open_comment_requires_base_forecast_and_portfolio(api):
    """PRD §3.8: "a plan with no `BASE`-scenario forecast row is rejected with
    `ERR_PLAN_MISSING_BASE_FORECAST` (HTTP 422), a plan with no portfolio at all is
    rejected with `ERR_PLAN_MISSING_PORTFOLIO` (HTTP 422), and a plan whose filing would
    miss the cycle deadline is rejected with `ERR_CYCLE_DEADLINE_MISSED`."

    Design: Corner/validations/open_comment_requires_base_forecast_and_portfolio
    """
    plan1 = create_plan(plan_name="IRP M3")
    add_portfolio(plan1["id"], portfolio_name="PF-M3")

    plan2 = create_plan(plan_name="IRP M4")
    add_forecast(plan2["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=10)

    resp = api.open_comment(plan1["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PLAN_MISSING_BASE_FORECAST)

    resp = api.open_comment(plan2["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PLAN_MISSING_PORTFOLIO)


def test_submit_without_preferred_portfolio_rejected(api):
    """PRD §3.8: "It also requires exactly the preferred-portfolio marker: a plan with
    no portfolio carrying `preferred_flag` true is rejected with
    `ERR_NO_PREFERRED_PORTFOLIO` (HTTP 422)."

    Design: Corner/validations/submit_without_preferred_portfolio_rejected
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP NP", preferred=False)
    open_plan_for_comment(plan["id"])
    set_clock("2026-08-31T00:00:00Z")

    resp = api.submit_for_review(plan["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_NO_PREFERRED_PORTFOLIO)

    after = get_success_data(api.get_plan(plan["id"], PLANNER))
    assert after["status"] == "OPEN_FOR_COMMENT"


def test_cancel_commitment_with_discharged_condition_rejected(api):
    """PRD §3.9: "Cancelling instead moves `ISSUED → CANCELLED` at a planner's hand,
    frees the commitment's megawatts from the candidate's aggregate, and bumps the
    commitment's `version` — but only while every listed condition is still `OPEN`;
    cancelling a commitment whose listed condition has already been discharged would
    orphan the discharge and is rejected with `ERR_CONDITION_ALREADY_DISCHARGED`
    (HTTP 409)."

    Design: Corner/validations/cancel_commitment_with_discharged_condition_rejected
    """
    plan, _portfolio, _snapshot = setup_approved_plan(        plan_name="IRP CD", forecast_year=2031, load_mw=400,
        conditions=[{"description": "Procure 50 MW", "required_procurement_mw": 50}],
    )
    condition = list_plan_conditions(plan["id"])[0]
    candidate = register_candidate(candidate_name="K-CD", nameplate_mw=300)

    c1 = issue_commitment(plan["id"], candidate_id=candidate["id"], committed_mw=50,
                          condition_discharge_ids=[condition["id"]])
    c2 = issue_commitment(plan["id"], candidate_id=candidate["id"], committed_mw=50,
                          condition_discharge_ids=[condition["id"]])

    validate_success(api.award_commitment(c1["id"], make_commissioner_headers("commissioner-cd-1")))

    resp = api.cancel_commitment(c2["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_CONDITION_ALREADY_DISCHARGED)

    after = get_success_data(api.get_commitment(c2["id"], PLANNER))
    assert after["status"] == "ISSUED"
