"""The error catalogue: each code reached by the narrowest request that provokes it.

The not-found group runs against an empty database so identifier resolution is
isolated from every state rule behind it. The state group builds the precise
predecessor state, provokes the refusal, and then reads the ledgers back to prove
the refused request moved nothing.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    COMMITTEE_CREATIVE,
    COMMITTEE_FINANCE,
    CONTINGENCY_CASTING,
    CONTINGENCY_FAILED,
    CONTINGENCY_PENDING,
    CONTINGENCY_SATISFIED,
    DEAL_CUT_OFF,
    DECISION_APPROVED,
    DECISION_PENDING,
    DECISION_REJECTED,
    DEV_PILOT_DELIVERED,
    DEV_PILOT_ORDERED,
    FEASIBILITY_BASIS_PATTERN,
    GL_OPEN,
    GL_REJECTED,
    NEG_AGREED,
    POSTURE_OPEN,
    PRODUCTION_ORDERED,
    SCREENING_CERTIFIED,
    STEP_ACCEPTED,
    STEP_CUT_OFF,
    STEP_PENDING,
    STEP_POLISH,
    STEP_STORY,
    TURNAROUND_OFFERED,
    VERDICT_INFEASIBLE,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    USER_EXEC_CREATIVE_1,
    USER_EXEC_CREATIVE_2,
    USER_FIN_1,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
    platform_admin_headers,
    research_analyst_headers,
    studio_partner_headers,
)

CUT_OFF_LADDER = {
    "steps": [f.step_spec(STEP_STORY, 3000000), f.step_spec(STEP_POLISH, 1000000)],
    "guaranteed_step_count": 1,
}
CERTIFIED_STAMP = "2026-09-26T00:00:00.000Z"
TIGHT_DEFICIT_SLATE = {"max_deficit_per_episode_cents": 3000000}
DEEP_WATER = {
    "title": "Deep Water",
    "logline": "A salvage diver finds a submarine that should not exist.",
    "underlying_ip_key": "IP-DEEP-WATER",
}


def test_reading_an_agency_that_does_not_exist_is_an_agency_not_found(api):
    """A well-formed UUID naming no agency row is a 404, not an empty 200.

    PRD 2.6: "Each entity has its own not-found code: `ERR_AGENCY_NOT_FOUND` ...
    all with HTTP status 404."

    Design: Corner/errors/agency_read_with_an_unknown_id_returns_agency_not_found
    """
    missing = api.get_agency(NON_EXISTENT_UUID, platform_admin_headers())
    validate_error(missing, e.ERR_AGENCY_NOT_FOUND, 404)
    a.assert_response_type(missing, "error")


def test_reading_a_slate_that_does_not_exist_is_a_slate_not_found(api):
    """The slate lookup carries its own code, distinct from every other 404.

    PRD 2.6: "Each entity has its own not-found code: ... `ERR_SLATE_NOT_FOUND`
    ... all with HTTP status 404."

    Design: Corner/errors/slate_read_with_an_unknown_id_returns_slate_not_found
    """
    missing = api.get_slate(NON_EXISTENT_UUID, finance_controller_headers())
    validate_error(missing, e.ERR_SLATE_NOT_FOUND, 404)
    a.assert_response_type(missing, "error")


def test_terminating_a_holding_deal_that_does_not_exist_is_a_holding_deal_not_found(api):
    """A complete body and the right role still lose to path resolution.

    PRD 2.11 priority 7: "Every identifier in the path exists, resolved left to
    right, else that entity's not-found code."

    Design: Corner/errors/terminating_an_unknown_holding_deal_returns_holding_deal_not_found
    """
    missing = api.terminate_holding_deal(
        NON_EXISTENT_UUID,
        f.terminate_holding_deal_payload(),
        business_affairs_headers(),
    )
    validate_error(missing, e.ERR_HOLDING_DEAL_NOT_FOUND, 404)
    a.assert_response_type(missing, "error")


def test_reading_a_pilot_order_that_does_not_exist_is_a_pilot_order_not_found(api):
    """The pilot-order 404 is reachable with no domain data at all.

    PRD 2.6: "Each entity has its own not-found code: ...
    `ERR_PILOT_ORDER_NOT_FOUND` ... all with HTTP status 404."

    Design: Corner/errors/pilot_order_read_with_an_unknown_id_returns_pilot_order_not_found
    """
    missing = api.get_pilot_order(NON_EXISTENT_UUID, development_exec_headers())
    validate_error(missing, e.ERR_PILOT_ORDER_NOT_FOUND, 404)
    a.assert_response_type(missing, "error")


def test_certifying_a_screening_that_does_not_exist_is_a_screening_not_found(api):
    """The id is resolved before the panel size, so this is never a sample-size error.

    PRD 2.6: "Path resolution and body-key resolution both happen before any state,
    business or fiscal rule is consulted."

    Design: Corner/errors/certifying_an_unknown_screening_returns_screening_not_found
    """
    missing = api.certify_screening(NON_EXISTENT_UUID, research_analyst_headers())
    validate_error(missing, e.ERR_SCREENING_NOT_FOUND, 404)
    a.assert_response_type(missing, "error")


def test_countering_a_negotiation_that_does_not_exist_is_a_negotiation_not_found(api):
    """Path resolution short-circuits ahead of the term-sheet coherence check.

    PRD 2.11 priority 7: "Every identifier in the path exists, resolved left to
    right, else that entity's not-found code."

    Design: Corner/errors/countering_an_unknown_negotiation_returns_negotiation_not_found
    """
    missing = api.table_round(
        NON_EXISTENT_UUID,
        f.round_payload(10, 29000000, 1800, 60, 40),
        studio_partner_headers(),
    )
    validate_error(missing, e.ERR_NEGOTIATION_NOT_FOUND, 404)
    a.assert_response_type(missing, "error")


def test_reading_a_greenlight_request_that_does_not_exist_is_a_greenlight_not_found(api):
    """The greenlight 404 is its own code, separate from the project's.

    PRD 2.6: "Each entity has its own not-found code: ... `ERR_GREENLIGHT_NOT_FOUND`
    ... all with HTTP status 404."

    Design: Corner/errors/greenlight_read_with_an_unknown_id_returns_greenlight_not_found
    """
    missing = api.get_greenlight_request(NON_EXISTENT_UUID, finance_controller_headers())
    validate_error(missing, e.ERR_GREENLIGHT_NOT_FOUND, 404)
    a.assert_response_type(missing, "error")


def test_exercising_a_step_that_belongs_to_no_deal_is_a_deal_step_not_found(api):
    """The parent deal resolves and the nested step does not, so the child code wins.

    PRD 2.6: "A request naming a deal step under a script deal resolves the script
    deal first: if that deal does not exist the answer is
    `ERR_SCRIPT_DEAL_NOT_FOUND`, and only once the deal is found does the server
    look for the step."

    Design: Corner/errors/exercising_an_unknown_step_under_a_real_deal_returns_deal_step_not_found
    """
    ctx = build_scenario(api, "deal")

    missing = api.exercise_step(ctx.deal_id, NON_EXISTENT_UUID, business_affairs_headers())
    validate_error(missing, e.ERR_DEAL_STEP_NOT_FOUND, 404)

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    only = a.find_step(steps, 1)
    assert only["status"] == STEP_PENDING
    assert only["exercised_at"] is None

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["open_step_count"] == 0


def test_a_second_cutoff_on_a_cut_off_deal_does_not_release_the_money_twice(api):
    """CUT_OFF is terminal, so the repeat instruction is refused and nothing moves.

    PRD 3.4: "`BusinessAffairs` submits a `cutoff_reason` on a deal that is still
    `EXECUTED`." and "cutting an optional step that was still `PENDING` moves no
    money at all, because an unexercised option was never encumbered in the first
    place."

    Design: Corner/errors/a_second_cutoff_on_an_already_cut_off_deal_returns_invalid_deal_state
    """
    ctx = build_scenario(api, "deal", deal=dict(CUT_OFF_LADDER))
    fx.accept_step(api, ctx.deal_id, ctx.step_ids[0])
    validate_success(
        api.cutoff_deal(ctx.deal_id, f.cutoff_payload(), business_affairs_headers())
    )

    refused = api.cutoff_deal(
        ctx.deal_id,
        f.cutoff_payload("duplicate instruction"),
        business_affairs_headers(),
    )
    validate_error(refused, e.ERR_INVALID_DEAL_STATE, 409)

    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    assert deal["deal_status"] == DEAL_CUT_OFF
    # PRD 3.4 has BusinessAffairs *submit* a cutoff_reason but, unlike the holding
    # deal's termination_reason (PRD 3.3), never states that the deal records or
    # exposes it, so the refusal is asserted on the state and the money instead.
    a.assert_cents(deal["encumbered_cents"], 4375000, "encumbered_cents")

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    assert a.find_step(steps, 1)["status"] == STEP_ACCEPTED
    assert a.find_step(steps, 2)["status"] == STEP_CUT_OFF

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=4375000, available=395625000)


def test_delivering_a_step_that_was_never_exercised_is_an_invalid_step_state(api):
    """Delivery is defined only from EXERCISED, and the refusal costs no step capacity.

    PRD 3.4: "a step that is `EXERCISED` moves `EXERCISED -> DELIVERED`, and a step
    that is `NOTES_ISSUED` moves `NOTES_ISSUED -> DELIVERED` as a redelivery ...
    Any other starting status is `ERR_INVALID_DEAL_STEP_STATE`."

    Design: Corner/errors/delivering_a_step_that_was_never_exercised_returns_invalid_deal_step_state
    """
    ctx = build_scenario(api, "deal")

    refused = api.deliver_step(
        ctx.deal_id, ctx.step_ids[0], business_affairs_headers()
    )
    validate_error(refused, e.ERR_INVALID_DEAL_STEP_STATE, 409)

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    only = a.find_step(steps, 1)
    assert only["status"] == STEP_PENDING
    assert only["exercised_at"] is None
    assert only["delivered_at"] is None

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["open_step_count"] == 0


def test_the_already_resolved_guard_is_per_dimension_and_not_per_pilot(api):
    """CASTING is settled so a second CASTING clearance is refused while LOCATION waits.

    PRD 3.5: "the dimension named by `kind` must still be `PENDING`, else
    `ERR_CONTINGENCY_ALREADY_RESOLVED`."

    Design: Corner/errors/clearing_the_same_contingency_twice_returns_contingency_already_resolved
    """
    ctx = build_scenario(api, "pilot_ordered")
    fx.clear_contingency(
        api, ctx.pilot_order_id, CONTINGENCY_CASTING, CONTINGENCY_SATISFIED
    )

    refused = api.clear_contingency(
        ctx.pilot_order_id,
        f.contingency_payload(
            CONTINGENCY_CASTING,
            CONTINGENCY_FAILED,
            overrides={"note": "late change of heart"},
        ),
        development_exec_headers(),
    )
    validate_error(refused, e.ERR_CONTINGENCY_ALREADY_RESOLVED, 409)

    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )
    assert pilot["casting_status"] == CONTINGENCY_SATISFIED
    assert pilot["location_status"] == CONTINGENCY_PENDING
    assert pilot["production_status"] == PRODUCTION_ORDERED
    assert pilot["collapsed_reason"] is None

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_ORDERED
    a.assert_cents(
        project["cumulative_dev_cost_cents"], 37375000, "cumulative_dev_cost_cents"
    )


def test_recertifying_a_certified_screening_does_not_restamp_it(api):
    """CERTIFIED is terminal, and the original certification instant is kept.

    PRD 3.6: "The screening must still be `FIELDED` - a screening that is already
    `CERTIFIED`, or that a newer screening has `INVALIDATED`, is refused with
    `ERR_INVALID_SCREENING_STATE`."

    Design: Corner/errors/certifying_an_already_certified_screening_returns_invalid_screening_state
    """
    ctx = build_scenario(api, "certified")
    fx.set_clock(api, "2026-09-27T00:00:00Z")

    refused = api.certify_screening(ctx.screening_id, research_analyst_headers())
    validate_error(refused, e.ERR_INVALID_SCREENING_STATE, 409)

    rows, meta = validate_paginated(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    a.assert_ids(rows, [ctx.screening_id])
    a.assert_pagination_meta(meta, total_count=1)
    assert rows[0]["status"] == SCREENING_CERTIFIED
    a.assert_instant(rows[0]["certified_at"], CERTIFIED_STAMP, "certified_at")
    a.assert_score(rows[0]["norm_adjusted_score"], 63.8, "norm_adjusted_score")


def test_countering_an_agreed_term_sheet_leaves_the_commitment_where_it_is(api):
    """AGREED is terminal, and the ten committed episodes do not slide back to reserved.

    PRD 3.7: "A counter on an `AGREED` or `WITHDRAWN` negotiation is refused with
    `ERR_INVALID_NEGOTIATION_STATE`."

    Design: Corner/errors/countering_an_agreed_term_sheet_returns_invalid_negotiation_state
    """
    ctx = build_scenario(api, "agreed")

    refused = api.table_round(
        ctx.negotiation_id,
        f.round_payload(8, 28000000, 1200, 80, 20),
        studio_partner_headers(),
    )
    validate_error(refused, e.ERR_INVALID_NEGOTIATION_STATE, 409)

    rows = validate_success(
        api.list_project_negotiations(ctx.project_id, business_affairs_headers())
    )
    agreed = next(row for row in rows if row["id"] == ctx.negotiation_id)
    assert agreed["status"] == NEG_AGREED
    assert agreed["episode_count"] == 10
    assert agreed["round_number"] == 1
    a.assert_cents(
        agreed["license_fee_per_episode_cents"], 30000000, "license_fee_per_episode_cents"
    )
    a.assert_cents(
        agreed["total_license_commitment_cents"],
        300000000,
        "total_license_commitment_cents",
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(slate, committed=10, reserved=0, available=10)


def test_a_rejected_request_is_closed_to_the_committees_that_never_voted(api):
    """FINANCE rejected, so the still-pending CREATIVE vote loses on request status.

    PRD 3.8: "the request must still be `OPEN`, else `ERR_INVALID_GREENLIGHT_STATE`,
    and the named committee's own decision must still be `PENDING`, else
    `ERR_COMMITTEE_ALREADY_DECIDED`."

    Design: Corner/errors/a_committee_vote_on_a_rejected_request_returns_invalid_greenlight_state
    """
    ctx = build_scenario(api, "greenlight")
    fx.record_finance_decision(api, ctx.greenlight_id, DECISION_REJECTED)

    refused = api.record_decision(
        ctx.greenlight_id,
        f.decision_payload(COMMITTEE_CREATIVE, DECISION_APPROVED),
        development_exec_headers(USER_EXEC_CREATIVE_1),
    )
    validate_error(refused, e.ERR_INVALID_GREENLIGHT_STATE, 409)

    request = validate_success(
        api.get_greenlight_request(ctx.greenlight_id, finance_controller_headers())
    )
    assert request["status"] == GL_REJECTED
    assert request["creative_decision"] == DECISION_PENDING
    assert request["finance_decision"] == DECISION_REJECTED

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_DELIVERED


def test_a_second_creative_vote_from_another_exec_cannot_overwrite_the_first(api):
    """A different user keeps segregation quiet, isolating the per-committee guard.

    PRD 3.8: "the named committee's own decision must still be `PENDING`, else
    `ERR_COMMITTEE_ALREADY_DECIDED`."

    Design: Corner/errors/a_second_creative_vote_from_a_different_exec_returns_committee_already_decided
    """
    ctx = build_scenario(api, "greenlight")
    fx.record_creative_decision(
        api, ctx.greenlight_id, DECISION_APPROVED, USER_EXEC_CREATIVE_1
    )

    refused = api.record_decision(
        ctx.greenlight_id,
        f.decision_payload(COMMITTEE_CREATIVE, DECISION_REJECTED, note="second thoughts"),
        development_exec_headers(USER_EXEC_CREATIVE_2),
    )
    validate_error(refused, e.ERR_COMMITTEE_ALREADY_DECIDED, 409)

    request = validate_success(
        api.get_greenlight_request(ctx.greenlight_id, finance_controller_headers())
    )
    assert request["status"] == GL_OPEN
    assert request["creative_decision"] == DECISION_APPROVED
    assert request["creative_decided_by_user_id"] == USER_EXEC_CREATIVE_1
    assert request["business_decision"] == DECISION_PENDING
    assert request["finance_decision"] == DECISION_PENDING

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_DELIVERED


def test_exercising_the_turnaround_after_the_window_has_shut_recoups_nothing(api):
    """At 2027-03-26 the offer of 2026-09-26 is past its 180 days.

    PRD 3.9: "an exercise at or after the instant 180 days past
    `turnaround_offered_at` is refused with `ERR_TURNAROUND_WINDOW_CLOSED`."

    Design: Corner/errors/exercising_turnaround_one_day_past_the_window_returns_turnaround_window_closed
    """
    ctx = fx.turnaround_offered(api, "wrapped")
    fx.set_clock(api, "2027-03-26T00:00:00Z")

    refused = api.exercise_turnaround(
        ctx.project_id, f.turnaround_exercise_payload(), business_affairs_headers()
    )
    validate_error(refused, e.ERR_TURNAROUND_WINDOW_CLOSED, 422)

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["turnaround_status"] == TURNAROUND_OFFERED
    assert project["turnaround_window_open"] is False
    a.assert_cents(project["recoupment_paid_cents"], 0, "recoupment_paid_cents")
    a.assert_cents(project["writeoff_cents"], 37375000, "writeoff_cents")

    rows, meta = validate_paginated(
        api.list_projects(
            business_affairs_headers(),
            {"predecessor_project_id": ctx.project_id, "limit": 10, "offset": 0},
        )
    )
    assert rows == [], "no successor project may exist"
    a.assert_pagination_meta(meta, total_count=0)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    # The wrapped pilot's 33000000 stays committed because that money was spent, and
    # the frozen 37375000 write-off is held out of the available figure permanently.
    a.assert_slate_dollar_ledger(
        slate, committed=33000000, writeoff=37375000, recouped=0, available=329625000
    )


def test_a_twenty_one_episode_offer_on_a_twenty_episode_slate_is_a_capacity_refusal(api):
    """The sheet is coherent and the fee sits exactly at the cap, so only inventory fails.

    PRD 3.7: "the slate must have the inventory: `available_episode_count` must be
    at least the `episode_count` being reserved, else
    `ERR_EPISODE_CAPACITY_EXCEEDED`."

    Design: Corner/errors/a_twenty_one_episode_offer_on_a_twenty_episode_slate_returns_episode_capacity_exceeded
    """
    ctx = build_scenario(api, "certified")

    refused = api.create_negotiation(
        f.negotiation_payload(
            ctx.project_id,
            episode_count=21,
            license_fee_per_episode_cents=30000000,
            backend_points_bps=1500,
            network_ownership_pct=70,
            studio_ownership_pct=30,
        ),
        business_affairs_headers(),
    )
    validate_error(refused, e.ERR_EPISODE_CAPACITY_EXCEEDED, 422)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=0, available=20, posture=POSTURE_OPEN
    )

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_DELIVERED


def test_only_the_finance_approval_re_runs_feasibility_and_it_can_refuse(api):
    """Creative and business approve the same request; the finance approval is the 422.

    PRD 3.8: "One further gate applies to a `FINANCE` vote of `APPROVED` only: the
    server re-evaluates the feasibility computation on the `PATTERN` basis at the
    `episode_count` of the negotiation attached to the request, and refuses the
    approval with `ERR_FEASIBILITY_FAILED` when the verdict comes back
    `INFEASIBLE`. A `FINANCE` vote of `REJECTED` faces no such check."

    Design: Corner/errors/a_finance_approval_on_an_infeasible_deficit_returns_feasibility_failed
    """
    ctx = build_scenario(api, "greenlight", slate=dict(TIGHT_DEFICIT_SLATE))
    fx.record_creative_decision(api, ctx.greenlight_id)
    fx.record_business_decision(api, ctx.greenlight_id)

    refused = api.record_decision(
        ctx.greenlight_id,
        f.decision_payload(COMMITTEE_FINANCE, DECISION_APPROVED),
        finance_controller_headers(USER_FIN_1),
    )
    validate_error(refused, e.ERR_FEASIBILITY_FAILED, 422)

    projection = validate_success(
        api.get_feasibility(
            ctx.project_id,
            finance_controller_headers(),
            {"basis": FEASIBILITY_BASIS_PATTERN, "episode_count": 10},
        )
    )
    # 37375000 of development over 10 episodes is 3737500 amortised, so the cost is
    # 35737500 and the deficit 5737500 - above the slate's 3000000 tolerance.
    a.assert_feasibility(
        projection,
        per_episode_cost_cents=35737500,
        tier_factor_bps=9000,
        license_fee_final_cents=30000000,
        deficit_per_episode_cents=5737500,
        total_deficit_cents=57375000,
        verdict=VERDICT_INFEASIBLE,
    )

    request = validate_success(
        api.get_greenlight_request(ctx.greenlight_id, finance_controller_headers())
    )
    assert request["status"] == GL_OPEN
    assert request["creative_decision"] == DECISION_APPROVED
    assert request["business_decision"] == DECISION_APPROVED
    assert request["finance_decision"] == DECISION_PENDING

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_DELIVERED

    rejected = validate_success(
        api.record_decision(
            ctx.greenlight_id,
            f.decision_payload(COMMITTEE_FINANCE, DECISION_REJECTED),
            finance_controller_headers(USER_FIN_1),
        )
    )
    assert rejected["finance_decision"] == DECISION_REJECTED, (
        "the refusal was the feasibility gate and not the committee wiring"
    )


def test_a_request_pairing_one_project_with_another_projects_sheet_is_a_mismatch(api):
    """Both ids resolve, both states are right, and only the pairing is wrong.

    PRD 3.8: "the negotiation must belong to the project named in the same request,
    else `ERR_NEGOTIATION_PROJECT_MISMATCH`."

    Design: Corner/errors/a_greenlight_request_pairing_one_project_with_another_projects_negotiation_returns_negotiation_project_mismatch
    """
    ctx = build_scenario(api, "certified")
    project2 = fx.second_project_through(api, ctx, "pilot_ordered", pitch=dict(DEEP_WATER))
    fx.greenlight_the_shoot(api, ctx.pilot_order2_id)
    wrapped = fx.wrap_pilot(api, ctx.pilot_order2_id)
    screening2 = fx.field_screening(api, ctx.pilot_order2_id, wrapped["version"])["id"]
    fx.certify_screening(api, screening2)
    negotiation2 = fx.open_negotiation(api, project2)["id"]
    fx.accept_negotiation_as_studio(api, negotiation2)

    version1 = fx.project_version(api, ctx.project_id)
    refused = api.create_greenlight_request(
        f.greenlight_payload(ctx.project_id, negotiation2, version1),
        business_affairs_headers(),
    )
    validate_error(refused, e.ERR_NEGOTIATION_PROJECT_MISMATCH, 422)

    rows, meta = validate_paginated(
        api.list_greenlight_requests(
            business_affairs_headers(),
            {"project_id": ctx.project_id, "limit": 10, "offset": 0},
        )
    )
    assert rows == [], "the refused filing leaves no request behind"
    a.assert_pagination_meta(meta, total_count=0)

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_DELIVERED
    assert project["version"] == version1, "a refused request bumps no version"

    sheets = validate_success(
        api.list_project_negotiations(project2, business_affairs_headers())
    )
    a.assert_ids(sheets, [negotiation2])
    assert sheets[0]["status"] == NEG_AGREED
    assert sheets[0]["episode_count"] == 10

    accepted = validate_success(
        api.create_greenlight_request(
            f.greenlight_payload(
                project2, negotiation2, fx.project_version(api, project2)
            ),
            business_affairs_headers(),
        ),
        201,
    )
    assert accepted["project_id"] == project2, "only the pairing had been wrong"
    assert accepted["negotiation_id"] == negotiation2
    assert accepted["status"] == GL_OPEN
