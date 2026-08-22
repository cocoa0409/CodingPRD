"""Funding the assignment: routing to the adjuster, the directive decision, the
benefit premium split, and the gates on activation."""
from test_helpers import (
    ApiErrorId,
    assert_adjuster_directive,
    assert_seat_ledger,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_routing_to_the_adjuster_takes_one_job_seat(api):
    """PRD §3.5: "The new directive's id is written into the placement's `current_adjuster_directive_id`, the chosen job's `filled_seats` rises by 1 — the seat is taken at routing time, not at activation — and the placement's `version` rises by 1."
    PRD §3.3: "thereafter `filled_seats` counts the placements on that job whose `placement_status` is `ADJUSTER_PENDING`, `ACTIVE` or `PROGRESSION_HOLD`, and is recomputed before any read of the job."

    Design: Difficulty/compensating_invariant/job_seat_occupancy_conserved_across_submit_and_terminate
    """
    ctx = fixtures.setup_proposed_placement()
    before = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(before, 0)

    routed = validate_success(
        api.submit_placement_to_adjuster(ctx["placement_id"], fixtures.COORD)
    )

    assert routed["placement_status"] == "ADJUSTER_PENDING"
    assert routed["current_adjuster_directive_id"] is not None
    after = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(after, 1)


def test_declining_the_placement_returns_the_seat_and_supersedes_the_directive(api):
    """PRD §3.6: "When instead the placement is `PROPOSED` or `ADJUSTER_PENDING`, it lands on `DECLINED` — that is, `PROPOSED → DECLINED` or `ADJUSTER_PENDING → DECLINED`: the supplied `reason` is copied into `decline_reason`, the job's `filled_seats` is lowered by 1 only when the placement was `ADJUSTER_PENDING` and therefore already holding a seat, every live directive moves to `SUPERSEDED`, and `version` rises by 1."

    Design: Difficulty/compensating_invariant/job_seat_occupancy_conserved_across_submit_and_terminate
    """
    ctx = fixtures.setup_routed_placement()
    held = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(held, 1)

    declined = validate_success(
        api.terminate_placement(
            ctx["placement_id"], {"reason": "Worker declined the assignment"}, fixtures.COORD
        )
    )

    assert declined["placement_status"] == "DECLINED"
    assert declined["decline_reason"] == "Worker declined the assignment"
    released = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(released, 0)
    assert released["filled_seats"] == held["filled_seats"] - 1, (
        "the compensating terminate returns the seat count to exactly where it started"
    )
    directives, _ = validate_paginated(
        api.list_placement_directives(ctx["placement_id"], fixtures.COORD)
    )
    assert directives[0]["directive_status"] == "SUPERSEDED"


def test_a_coordinator_may_not_decide_the_directive(api):
    """PRD §3.5: "The adjuster who owns the claim — the operator whose `X-User-ID` equals the claim's `adjuster_user_id` — decides the directive by supplying a `decision`, which is `AUTHORIZED`, `AUTHORIZED_WITH_CONDITIONS` or `DENIED`."
    PRD §2.1: "When a caller's role is not listed among an endpoint's authorized roles in §4, the request is refused with `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/coordinator_cannot_decide_an_adjuster_directive
    """
    ctx = fixtures.setup_routed_placement()

    resp = api.decide_adjuster_directive(
        ctx["directive_id"],
        {"decision": "AUTHORIZED", "authorized_weekly_cost_cents": 120_000},
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    directive = validate_success(
        api.get_placement(ctx["placement_id"], fixtures.COORD)
    )
    assert directive["placement_status"] == "ADJUSTER_PENDING"
    directives, _ = validate_paginated(
        api.list_placement_directives(ctx["placement_id"], fixtures.COORD)
    )
    assert directives[0]["directive_status"] == "PENDING"


def test_authorizing_above_the_claim_ceiling_is_refused(api):
    """PRD §3.5: "On a decision, the `authorized_weekly_cost_cents` the adjuster grants may not exceed the claim's `max_authorized_weekly_cost_cents`; a grant exactly equal to the ceiling is allowed."
    PRD §3.5: "Two ceilings bound the money, and both raise `ERR_ADJUSTER_AUTHORIZATION_EXCEEDED` with HTTP 422 at priority 40."

    Design: Corner/validations/authorization_above_claim_ceiling_is_rejected_on_decide
    """
    ctx = fixtures.setup_routed_placement()

    resp = api.decide_adjuster_directive(
        ctx["directive_id"],
        {"decision": "AUTHORIZED", "authorized_weekly_cost_cents": 200_000},
        fixtures.ADJUSTER,
    )

    validate_error(resp, ApiErrorId.ERR_ADJUSTER_AUTHORIZATION_EXCEEDED, 422)
    directives, _ = validate_paginated(
        api.list_placement_directives(ctx["placement_id"], fixtures.COORD)
    )
    assert directives[0]["directive_status"] == "PENDING", "the directive stays PENDING"


def test_deciding_a_directive_twice_is_refused(api):
    """PRD §3.5: "The directive must still be `PENDING`, or the request answers `ERR_DIRECTIVE_ALREADY_DECIDED` at priority 12."
    PRD §3.5: "An `AUTHORIZED` decision moves the directive `PENDING → AUTHORIZED` and requires `authorized_weekly_cost_cents`, the weekly spend the carrier will fund."

    Design: Corner/errors/second_decide_on_the_same_directive_returns_already_decided
    """
    ctx = fixtures.setup_authorized_placement()

    resp = api.decide_adjuster_directive(
        ctx["directive_id"],
        {"decision": "DENIED", "denial_reason": "Changed my mind"},
        fixtures.ADJUSTER,
    )

    validate_error(resp, ApiErrorId.ERR_DIRECTIVE_ALREADY_DECIDED, 409)
    directives, _ = validate_paginated(
        api.list_placement_directives(ctx["placement_id"], fixtures.COORD)
    )
    surviving = directives[0]
    assert_adjuster_directive(surviving)
    assert surviving["directive_status"] == "AUTHORIZED"
    assert surviving["authorized_weekly_cost_cents"] == 120_000


def test_activation_is_refused_while_the_directive_is_still_pending(api):
    """PRD §3.5: "At priority 38 the placement must have a current directive at all and that directive must no longer be `PENDING`; a missing directive or a still-pending one answers `ERR_ADJUSTER_AUTHORIZATION_MISSING` with HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_adjuster_directive_decision
    """
    ctx = fixtures.setup_routed_placement()

    resp = api.activate_placement(ctx["placement_id"], fixtures.COORD)

    validate_error(resp, ApiErrorId.ERR_ADJUSTER_AUTHORIZATION_MISSING, 409)
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["placement_status"] == "ADJUSTER_PENDING"


def test_activation_is_refused_once_the_directive_is_denied(api):
    """PRD §3.5: "A `DENIED` directive passes that first check and is caught by the second: at priority 39 the current directive's `directive_status` must be `AUTHORIZED` or `AUTHORIZED_WITH_CONDITIONS`, and a denial answers `ERR_ADJUSTER_DIRECTIVE_DENIED` with HTTP 409."
    PRD §3.5: "A `DENIED` decision moves it `PENDING → DENIED` and requires a non-empty `denial_reason`; it forces `authorized_weekly_cost_cents` to zero and writes the reason."
    PRD §3.5: "A denial deliberately leaves the placement sitting at `ADJUSTER_PENDING` rather than ending it, so the coordinator may re-route the case or terminate the placement outright."

    Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_adjuster_directive_decision
    """
    ctx = fixtures.setup_routed_placement()

    denied = validate_success(
        api.decide_adjuster_directive(
            ctx["directive_id"],
            {"decision": "DENIED", "denial_reason": "Transitional wage above reserve"},
            fixtures.ADJUSTER,
        )
    )
    assert denied["directive_status"] == "DENIED"
    assert denied["authorized_weekly_cost_cents"] == 0

    resp = api.activate_placement(ctx["placement_id"], fixtures.COORD)

    validate_error(resp, ApiErrorId.ERR_ADJUSTER_DIRECTIVE_DENIED, 409)
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["placement_status"] == "ADJUSTER_PENDING"


def test_the_subsidy_tier_is_keyed_on_the_provisional_employer_share(api):
    """PRD §3.6: "First, the monthly premium total is read from the worker's `benefit_tier`: 68000 cents for `TIER_A`, 52000 cents for `TIER_B`, 41000 cents for `TIER_C`. Second, a provisional employee contribution is that total multiplied by the base contribution rate of 0.28, rounded half up to whole cents. Third, the provisional employer share is the total minus that provisional employee contribution, computed as an exact integer subtraction. Fourth, the subsidy factor is chosen from the provisional employer share: 0.90 when that provisional employer share is at most 38000 cents, otherwise 0.70 when it is at most 55000 cents, otherwise 0.55. Fifth, `employee_premium_share_cents` is the provisional employee contribution multiplied by that subsidy factor, rounded half up to whole cents. Sixth, `employer_premium_share_cents` is the monthly premium total minus `employee_premium_share_cents`, again an exact integer subtraction."
    PRD §3.6: "The evaluation order below is normative, and in particular the subsidy tier is keyed on the *provisional* employer share, never re-keyed on the final one."

    Design: Difficulty/combinatorial_formula/premium_split_tier_keyed_on_provisional_employer_share
    """
    ctx = fixtures.setup_active_placement()

    data = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))

    assert data["employee_premium_share_cents"] == 13104, (
        f"TIER_B's 52000-cent premium keys the 0.90 tier off the 37440-cent provisional "
        f"employer share, got {data['employee_premium_share_cents']}"
    )
    assert data["employer_premium_share_cents"] == 38896
    assert data["employee_premium_share_cents"] != 10192, (
        "re-keying the tier on the final employer share would give 10192"
    )
    assert data["employer_premium_share_cents"] != 41808


def test_the_projected_weekly_cost_sums_three_separately_rounded_addends(api):
    """PRD §3.5: "It is the sum of three separately rounded addends. The first is the transitional wage: the job's `hourly_rate_cents` multiplied by the placement's `scheduled_hours_per_day` multiplied by the five workdays in a week, rounded half up to whole cents. The second is the wage differential the employer expects to owe: take the worker's `pre_injury_weekly_wage_cents`, subtract that same weekly transitional wage figure — the job's `hourly_rate_cents` times `scheduled_hours_per_day` times five — floor the difference at zero so a transitional job that outpays the pre-injury wage never produces a negative differential, multiply by the statutory replacement rate of 0.6667, and round half up to whole cents. The third is the benefit share: the placement's `employer_premium_share_cents` divided by the four premium weeks in a month, rounded half up to whole cents. Each addend is rounded before they are added, and the three rounded addends are then summed exactly."
    PRD §3.6: "`EMPLOYER_SUBSIDIZED` when it is `ACTIVE`, `PROGRESSION_HOLD` or `SUSPENDED` and the worker's `benefit_tier` is `TIER_A` or `TIER_B`"

    Design: Difficulty/combinatorial_formula/premium_split_tier_keyed_on_provisional_employer_share
    """
    ctx = fixtures.setup_active_placement()

    data = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))

    assert data["benefit_continuation_status"] == "EMPLOYER_SUBSIDIZED"
    assert data["projected_weekly_cost_cents"] == 102227, (
        f"37500 transitional wage + 55003 differential + 9724 benefit share, got "
        f"{data['projected_weekly_cost_cents']}"
    )


def test_the_activation_response_already_carries_every_derived_field(api):
    """PRD §3.6: "When all gates pass, the placement advances `ADJUSTER_PENDING → ACTIVE`, `activated_on` is set to the placement's `start_date`, the benefit premium split and `benefit_continuation_status` are computed, the first progression review is created with `step_index` 1, `review_status` `SCHEDULED` and a `due_date` 30 days after `start_date`, that review's id is written into `current_progression_review_id`, the claim's `cumulative_transitional_days` and `rtw_posture` are recomputed, and the placement's `version` rises by 1."
    PRD §2.9: "a placement's `match_score`, `reinjury_risk_score`, `cumulative_days`, premium shares and `projected_weekly_cost_cents`, and a panel's tally fields all reflect the post-cascade world in the very response that caused the cascade."

    Design: Corner/consistency_model/activation_response_carries_every_derived_field_immediately
    """
    ctx = fixtures.setup_authorized_placement()

    data = validate_success(api.activate_placement(ctx["placement_id"], fixtures.COORD))

    assert data["placement_status"] == "ACTIVE"
    assert data["activated_on"] == "2026-08-03"
    assert data["employer_premium_share_cents"] == 38896
    assert data["employee_premium_share_cents"] == 13104
    assert data["benefit_continuation_status"] == "EMPLOYER_SUBSIDIZED"
    assert data["projected_weekly_cost_cents"] == 102227
    assert data["current_progression_review_id"] is not None, (
        "no follow-up read is needed to learn the step-1 review's id"
    )
