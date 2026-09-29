"""Boundaries, asymmetric rules, aggregates and one ladder collision.

Covers the minimum-term gate at rung 24, the lead-time boundary at rung 13, the
shape-before-lookup ordering of rungs 3 and 4, the permit window at rung 10, the
crew day cap at rung 15 and the wind-load flag at rung 11, all of PRD §2.7.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_BELOW_MINIMUM_TERM,
    ERR_CREW_CAPACITY_EXCEEDED,
    ERR_PERMIT_LEAD_TIME_NOT_MET,
    ERR_PERMIT_WINDOW_ELAPSED,
    ERR_VALIDATION,
    ERR_WIND_LOAD_NOT_PERMITTED,
    ERR_WORK_ORDER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_integer,
    assert_labor_hours,
)

UNKNOWN_WORK_ORDER_ID = "00000000-0000-4000-8000-000000000999"


def test_the_minimum_term_rule_is_asymmetric_between_the_two_families(api):
    """PRD §3.2: "at rung 24, the committed term is checked against the contract
    family: a `CONSTRUCTION` configuration requires `term_months` of at least 3,
    and an `EVENT` configuration requires `term_months` of exactly 1 ... A
    violation of either is `ERR_BELOW_MINIMUM_TERM`."

    Design: Corner/validations/construction_term_two_and_event_term_two_rejected
    """
    world = FX.seed_world(api)
    jobsite_id = world["jobsite"]["id"]
    assert_integer(world["jobsite"]["version"], 1, "version")

    validate_error(
        api.create_quote(
            jobsite_id,
            F.quote_payload(1, linear_feet=500, term_months=2),
            U.ACCOUNT_MANAGER,
        ),
        ERR_BELOW_MINIMUM_TERM,
        409,
    )

    # Two months clears the construction floor's direction and is still refused,
    # because an event fence is quoted for exactly one billing month.
    validate_error(
        api.create_quote(
            jobsite_id,
            F.quote_payload(
                1,
                contract_type=C.CONTRACT_TYPE_EVENT,
                linear_feet=500,
                term_months=2,
            ),
            U.ACCOUNT_MANAGER,
        ),
        ERR_BELOW_MINIMUM_TERM,
        409,
    )

    # Neither refusal mutated the jobsite, so the same token is still current.
    assert_integer(FX.read_jobsite(api, jobsite_id)["version"], 1, "version")

    accepted = validate_success(
        api.create_quote(
            jobsite_id,
            F.quote_payload(
                1,
                contract_type=C.CONTRACT_TYPE_EVENT,
                linear_feet=500,
                term_months=1,
            ),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    assert_integer(accepted["term_months"], 1, "term_months")
    assert accepted["contract_type"] == C.CONTRACT_TYPE_EVENT
    # 27000 surged by the unconditional 1.25; term_months never discounts an event.
    assert_cents(accepted["monthly_recurring_cents"], 33750, "monthly_recurring_cents")
    assert_cents(accepted["one_time_cents"], 78500, "one_time_cents")


def test_a_closure_starting_exactly_on_the_lead_time_boundary_is_admitted(api):
    """PRD §3.4: "the lead-time rule requires `closure_start_utc` to be at least
    `permit_lead_time_days` whole days after the logical clock — that is, at or
    after the clock advanced by `permit_lead_time_days` multiplied by 86,400
    seconds. Sitting exactly on that boundary is admitted; falling short of it is
    `ERR_PERMIT_LEAD_TIME_NOT_MET`."

    Design: Corner/validations/permit_submitted_at_exactly_the_lead_time_boundary_admitted
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Dock Street North",
            "address_line": "8 Dock Street",
            "site_condition": C.CONDITION_ASPHALT,
            "requires_sidewalk_closure": True,
        },
    )
    jobsite_id = world["jobsite"]["id"]

    on_the_boundary = FX.seed_permit(
        api,
        jobsite_id,
        closure_linear_feet=300,
        closure_start_utc="2026-08-06T00:00:00Z",
        closure_end_utc="2026-08-16T00:00:00Z",
    )
    one_second_short = FX.seed_permit(
        api,
        jobsite_id,
        closure_linear_feet=200,
        closure_start_utc="2026-08-05T23:59:59Z",
        closure_end_utc="2026-08-15T00:00:00Z",
        sidewalk_closure_type=C.CLOSURE_LANE_SHIFT,
    )

    submitted = validate_success(
        api.submit_permit(on_the_boundary["id"], U.MUNICIPAL_LIAISON, F.submit_payload())
    )
    assert submitted["status"] == C.PERMIT_SUBMITTED
    assert_instant(submitted["submitted_at_utc"], C.CLOCK_AUG_01, "submitted_at_utc")
    assert_integer(submitted["revision_round"], 0, "revision_round")

    validate_error(
        api.submit_permit(one_second_short["id"], U.MUNICIPAL_LIAISON, F.submit_payload()),
        ERR_PERMIT_LEAD_TIME_NOT_MET,
        409,
    )

    unmoved = FX.read_permit(api, one_second_short["id"])
    assert unmoved["status"] == C.PERMIT_DRAFT
    assert unmoved["submitted_at_utc"] is None


def test_a_malformed_instant_outranks_an_unresolvable_path_id(api):
    """PRD §2.7: rung 3 is request-shape integrity and rung 4 is path-parameter
    resolution, and "this ordering decides which failure a caller sees when several
    apply at once". A malformed instant therefore answers 400 even though the path
    id resolves to nothing.

    Design: Corner/validations/malformed_timestamp_outranks_unknown_path_id_and_returns_400
    """
    FX.set_clock(api, C.CLOCK_AUG_01)
    crew = FX.seed_crew(api)

    malformed = api.dispatch_work_order(
        UNKNOWN_WORK_ORDER_ID,
        {"crew_id": crew["id"], "scheduled_start_utc": "2026-08-03 08:00"},
        U.DISPATCH_COORDINATOR,
    )
    validate_error(malformed, ERR_VALIDATION, 400)
    assert malformed.json()["response_type"] == "error", malformed.json()
    assert malformed.json()["data"]["message"], malformed.json()

    well_formed = api.dispatch_work_order(
        UNKNOWN_WORK_ORDER_ID,
        {"crew_id": crew["id"], "scheduled_start_utc": "2026-08-03T08:00:00Z"},
        U.DISPATCH_COORDINATOR,
    )
    validate_error(well_formed, ERR_WORK_ORDER_NOT_FOUND, 404)
    assert well_formed.json()["response_type"] == "error", well_formed.json()
    assert well_formed.json()["data"]["message"], well_formed.json()

    # Neither call committed an interval against the crew.
    unchanged = FX.read_crew(api, crew["id"])
    assert_integer(unchanged["version"], crew["version"], "version")
    assert unchanged["daily_capacity_hours"] == crew["daily_capacity_hours"]


def test_the_permit_window_must_contain_the_computed_end_not_only_the_start(api):
    """PRD §3.5: "its half-open closure window must contain **both**
    `scheduled_start_utc` and `scheduled_end_utc` — each of the two instants must
    be at or after `closure_start_utc` and strictly before `closure_end_utc` — and
    a visit whose interval is not entirely inside the window is refused with
    `ERR_PERMIT_WINDOW_ELAPSED`."

    Design: Corner/validations/dispatch_window_must_contain_the_computed_end_not_only_the_start
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Dock Street North",
            "address_line": "8 Dock Street",
            "site_condition": C.CONDITION_SOIL,
            "requires_sidewalk_closure": True,
        },
    )
    jobsite_id = world["jobsite"]["id"]
    permit = FX.seed_approved_permit(api, jobsite_id, closure_linear_feet=500)
    assert permit["status"] == C.PERMIT_APPROVED

    contract, _quote = FX.seed_contract(
        api, jobsite_id, world["account"]["id"], linear_feet=500
    )
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)

    # 22:00 is inside [2026-08-10, 2026-08-20), but 22:00 + 4.25 h is not.
    validate_error(
        api.dispatch_work_order(
            install["id"],
            F.dispatch_payload(world["crew"]["id"], "2026-08-19T22:00:00Z"),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_PERMIT_WINDOW_ELAPSED,
        409,
    )

    refused = FX.read_work_order(api, install["id"])
    assert refused["status"] == C.WO_PLANNED
    assert refused["crew_id"] is None
    assert refused["estimated_labor_hours"] is None

    scheduled = validate_success(
        api.dispatch_work_order(
            install["id"],
            F.dispatch_payload(world["crew"]["id"], "2026-08-19T18:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )
    assert scheduled["status"] == C.WO_SCHEDULED
    assert_labor_hours(scheduled["estimated_labor_hours"], 4.25)
    assert_instant(
        scheduled["scheduled_end_utc"], "2026-08-19T22:15:00Z", "scheduled_end_utc"
    )

    assert FX.read_permit(api, permit["id"])["status"] == C.PERMIT_APPROVED


def test_the_crew_day_cap_is_breached_only_by_the_collective(api):
    """PRD §3.5: "The crew's committed hours for a UTC calendar date are the sum of
    `estimated_labor_hours` over its `SCHEDULED` visits whose `scheduled_start_utc`
    falls on that same UTC calendar date. That sum, plus the candidate's own
    `estimated_labor_hours`, must be at or below the crew's `daily_capacity_hours`;
    equality is admitted ... Each visit fits individually — only the day's
    collective can breach the cap."

    Design: Corner/validations/crew_day_capacity_is_breached_only_by_the_collective
    """
    world = FX.seed_world(
        api,
        crews=(C.CREW_B,),
        crew_overrides={"depot_code": "DEP-2", "daily_capacity_hours": 8.0},
        jobsite={
            "site_label": "Foundry Road North Pad",
            "address_line": "402 Foundry Road",
        },
    )
    crew_id = world["crew"]["id"]
    assert world["crew"]["daily_capacity_hours"] == 8.0
    south = FX.add_jobsite(
        world, api, site_label="Foundry Road South Pad", address_line="406 Foundry Road"
    )

    north_contract, _q1 = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    south_contract, _q2 = FX.seed_contract(
        api, south["id"], world["account"]["id"], linear_feet=500
    )

    first = FX.plan_work_order(
        api, north_contract["id"], C.WO_DELIVERY_INSTALL, 500
    )
    FX.dispatch(api, first["id"], crew_id, "2026-08-03T08:00:00Z")

    too_big = FX.plan_work_order(
        api, south_contract["id"], C.WO_DELIVERY_INSTALL, 500
    )
    just_fits = FX.plan_work_order(
        api, south_contract["id"], C.WO_DELIVERY_INSTALL, 450
    )

    # 14:00 is clear of the first visit's buffered end of 13:45, so the collision
    # gate at rung 14 passes and the day's cap at rung 15 is the one that answers.
    validate_error(
        api.dispatch_work_order(
            too_big["id"],
            F.dispatch_payload(crew_id, "2026-08-03T14:00:00Z"),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_CREW_CAPACITY_EXCEEDED,
        409,
    )

    refused = FX.read_work_order(api, too_big["id"])
    assert refused["status"] == C.WO_PLANNED
    assert refused["crew_id"] is None

    scheduled = validate_success(
        api.dispatch_work_order(
            just_fits["id"],
            F.dispatch_payload(crew_id, "2026-08-03T14:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )

    assert scheduled["status"] == C.WO_SCHEDULED
    assert_labor_hours(scheduled["estimated_labor_hours"], 3.75)
    assert_instant(
        scheduled["scheduled_end_utc"], "2026-08-03T17:45:00Z", "scheduled_end_utc"
    )
    assert scheduled["reserved_unit_counts"] == [
        {"product_code": C.PANEL_CODE, "unit_count": 45}
    ]


def test_the_solid_screen_is_a_jurisdictional_question_decided_before_pricing(api):
    """PRD §3.2: "at rung 11, a `SOLID_130` screen is refused with
    `ERR_WIND_LOAD_NOT_PERMITTED` when the jobsite's jurisdiction has
    `allows_solid_wind_screen` false — a 130 mph solid screen is a jurisdictional
    wind-load question, decided before any pricing arithmetic runs."

    Design: Corner/validations/solid_screen_allowed_by_one_municipality_and_refused_by_another
    """
    world = FX.seed_world(api, jobsite={"site_label": "Harbor Point Yard"})
    refusing = FX.seed_municipality(
        api,
        name="Township of Westbrook",
        jurisdiction_code="WSTB-02",
        allows_solid_wind_screen=False,
    )
    assert world["municipality"]["allows_solid_wind_screen"] is True
    assert refusing["allows_solid_wind_screen"] is False

    westbrook_site = FX.seed_jobsite(
        api,
        world["account"]["id"],
        refusing["id"],
        site_label="Westbrook Yard",
        address_line="19 Mill Lane",
    )

    priced = validate_success(
        api.create_quote(
            world["jobsite"]["id"],
            F.quote_payload(
                FX.jobsite_version(api, world["jobsite"]["id"]),
                linear_feet=500,
                wind_screen=C.SCREEN_SOLID_130,
            ),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert priced["wind_screen"] == C.SCREEN_SOLID_130
    # 27000 x 1.35 is 36450, plus a 26-cent-per-foot adder of 13000.
    assert_cents(priced["monthly_recurring_cents"], 49450, "monthly_recurring_cents")
    assert_cents(priced["one_time_cents"], 78500, "one_time_cents")

    validate_error(
        api.create_quote(
            westbrook_site["id"],
            F.quote_payload(
                westbrook_site["version"],
                linear_feet=500,
                wind_screen=C.SCREEN_SOLID_130,
            ),
            U.ACCOUNT_MANAGER,
        ),
        ERR_WIND_LOAD_NOT_PERMITTED,
        409,
    )

    assert_integer(FX.read_jobsite(api, westbrook_site["id"])["version"], 1, "version")

    body = api.list_quotes(
        U.ACCOUNT_MANAGER,
        params={"jobsite_id": westbrook_site["id"], "limit": C.MAX_LIMIT},
    ).json()
    assert body["data"] == [], body
    assert_integer(body["meta"]["total_count"], 0, "total_count")
