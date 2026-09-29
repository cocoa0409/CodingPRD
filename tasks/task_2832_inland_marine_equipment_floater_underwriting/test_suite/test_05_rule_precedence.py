"""Which rule speaks first when two are broken at once."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.test_users import (
    ADJUSTER,
    ADJUSTER_USER_ID,
    MANAGER,
    MANAGER_2,
    MANAGER_USER_ID,
    UNDERWRITER,
    make_headers,
)
from test_helpers.types import Role


def site_with_one_autumn_floater(api):
    """A DRAFT installation file whose only floater runs September to December."""
    return fixtures.build_installation_file(
        api, jobsite_controls=factories.SURVEY_TIER_2,
        floater_kwargs=dict(coverage_start_date="2026-09-01",
                            coverage_end_date="2026-12-01",
                            installed_value_limit_cents=20000000,
                            project_name="Tower A fit-out"))


def test_a_floater_running_past_the_policy_term_fails_on_the_term_not_the_overlap(api):
    """Both rules are broken; the term rule is tested first and is the one reported.

    PRD: First, the whole closed interval must sit inside the policy term — `coverage_start_date` on or after the policy's `effective_date` and `coverage_end_date` on or before the policy's `expiration_date` — else `ERR_FLOATER_OUTSIDE_POLICY_TERM`.
    PRD: Second, a jobsite may carry at most one live floater at a time: the new floater's closed interval must not intersect the closed interval of any floater on the same jobsite whose status is `PENDING` or `ACTIVE`, and a single shared endpoint counts as an intersection, so a floater ending on a given day and another beginning on that same day collide.
    Design: Difficulty/priority_pair_validation_conflict/floater_term_temporal_beats_jobsite_overlap_constraint
    """
    ctx = site_with_one_autumn_floater(api)

    refused = api.create_installation_floater(
        ctx.part_id,
        factories.installation_floater(
            ctx.jobsite_id, project_name="Tower B fit-out",
            installed_value_limit_cents=15000000,
            coverage_start_date="2026-11-01", coverage_end_date="2027-09-30"),
        UNDERWRITER)

    validate_error(refused, "ERR_FLOATER_OUTSIDE_POLICY_TERM", 422)

    site = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert site["active_floater_count"] == 1
    assert get_success_data(api.get_installation_floater(
        ctx.floater_id, UNDERWRITER))["status"] == "PENDING"
    rows, meta = validate_paginated(api.list_installation_floaters(
        UNDERWRITER, limit=50, offset=0, jobsite_id=ctx.jobsite_id))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx.floater_id
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["status"] == "DRAFT"
    assert policy["written_premium_cents"] == 0


def test_the_overlap_rule_speaks_once_the_interval_sits_inside_the_term(api):
    """Pulling the end date back inside the term lets the losing rule fire.

    PRD: A collision is refused with `ERR_JOBSITE_FLOATER_OVERLAP`.
    PRD: The overlap test looks only at the jobsite, never at the coverage part, so two different policies competing for the same site collide with each other.
    Design: Difficulty/priority_pair_validation_conflict/floater_term_temporal_beats_jobsite_overlap_constraint
    """
    ctx = site_with_one_autumn_floater(api)

    collided = api.create_installation_floater(
        ctx.part_id,
        factories.installation_floater(
            ctx.jobsite_id, project_name="Tower B fit-out",
            installed_value_limit_cents=15000000,
            coverage_start_date="2026-11-01", coverage_end_date="2027-01-31"),
        UNDERWRITER)

    validate_error(collided, "ERR_JOBSITE_FLOATER_OVERLAP", 409)
    assert get_success_data(api.get_jobsite(
        ctx.jobsite_id, UNDERWRITER))["active_floater_count"] == 1

    accepted = validate_success(api.create_installation_floater(
        ctx.part_id,
        factories.installation_floater(
            ctx.jobsite_id, project_name="Tower B fit-out",
            installed_value_limit_cents=15000000,
            coverage_start_date="2026-12-02", coverage_end_date="2027-01-31"),
        UNDERWRITER), 201)

    assert accepted["status"] == "PENDING"
    _, meta = validate_paginated(api.list_installation_floaters(
        UNDERWRITER, limit=50, offset=0, jobsite_id=ctx.jobsite_id))
    assert meta["total_count"] == 2


def unsurveyed_site_file_on_risk(api):
    """An on-risk installation file whose floater sits on a never-surveyed site."""
    ctx = fixtures.build_installation_file(
        api, jobsite_controls=None,
        part_kwargs=dict(aggregate_limit_cents=10000000),
        floater_kwargs=dict(coverage_start_date="2026-09-01",
                            coverage_end_date="2026-12-01",
                            installed_value_limit_cents=20000000,
                            project_name="Tower A fit-out"),
        quote_it=True)
    fixtures.bind(api, ctx.policy_id)
    fixtures.activate(api, ctx.policy_id)
    return ctx


def test_an_unsecured_site_blocks_activation_before_the_capacity_test_is_reached(api):
    """The floater breaks the security gate and the capacity gate; security is reported.

    PRD: Activation requires the floater to be `PENDING`, else `ERR_FLOATER_NOT_IN_REQUIRED_STATE`; requires the owning policy to be `IN_FORCE`, else `ERR_POLICY_NOT_IN_FORCE`; requires the jobsite to be `SURVEYED` with a `security_tier` other than `TIER_0`, else `ERR_JOBSITE_SECURITY_INSUFFICIENT`; and requires `installed_value_limit_cents` to be no greater than the part's `aggregate_available_cents` at that moment, else `ERR_FLOATER_LIMIT_EXCEEDS_PART_AGGREGATE`.
    PRD: Because a `TIER_0` site can be priced but cannot be activated, the surcharge branch is only ever observable on a floater that is still `PENDING`.
    Design: Difficulty/priority_pair_validation_conflict/jobsite_safety_beats_floater_aggregate_fiscal
    """
    ctx = unsurveyed_site_file_on_risk(api)

    refused = api.activate_installation_floater(ctx.floater_id, UNDERWRITER)

    validate_error(refused, "ERR_JOBSITE_SECURITY_INSUFFICIENT", 422)

    floater = get_success_data(
        api.get_installation_floater(ctx.floater_id, UNDERWRITER))
    assert floater["status"] == "PENDING"
    assert floater["term_days"] == 92
    assert floater["rated_premium_cents"] == 88219
    site = get_success_data(api.get_jobsite(ctx.jobsite_id, UNDERWRITER))
    assert site["status"] == "UNSURVEYED"
    assert site["security_tier"] == "TIER_0"
    assert site["security_score"] == 0
    assert site["surveyed_at"] is None
    assert site["active_floater_count"] == 1
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["aggregate_available_cents"] == 10000000
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["written_premium_cents"] == 100000


def test_securing_the_site_leaves_the_capacity_gate_to_refuse_the_same_floater(api):
    """Surveying cures the security gate and does not re-price what is still too big.

    PRD: This last test is a comparison against remaining capacity, not against the original `aggregate_limit_cents`, so a part that has already paid claims may refuse a floater it would have accepted before.
    PRD: On success the floater moves `PENDING` → `ACTIVE`; the premium is not recomputed, so a jobsite re-survey between creation and activation does not re-price the floater.
    Design: Difficulty/priority_pair_validation_conflict/jobsite_safety_beats_floater_aggregate_fiscal
    """
    ctx = unsurveyed_site_file_on_risk(api)
    surveyed = fixtures.survey_jobsite(api, ctx.jobsite_id, factories.SURVEY_TIER_2)
    assert surveyed["status"] == "SURVEYED"
    assert surveyed["security_tier"] == "TIER_2"

    refused = api.activate_installation_floater(ctx.floater_id, UNDERWRITER)

    validate_error(refused, "ERR_FLOATER_LIMIT_EXCEEDS_PART_AGGREGATE", 422)
    floater = get_success_data(
        api.get_installation_floater(ctx.floater_id, UNDERWRITER))
    assert floater["status"] == "PENDING"
    assert floater["rated_premium_cents"] == 88219
    assert get_success_data(api.get_jobsite(
        ctx.jobsite_id, UNDERWRITER))["active_floater_count"] == 1


def settled_repair_claim(api):
    """The canonical file with one repair claim already paid and closed."""
    ctx = fixtures.build_in_force_file(api)
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    claim = fixtures.build_repair_claim(api, ctx, loss_date="2026-08-15",
                                        loss_type="COLLISION")
    ctx["claim"] = claim
    ctx["closed"] = fixtures.settle(api, claim["id"])
    return ctx


def assert_the_claim_was_paid_exactly_once(api, ctx):
    """Nothing about the paid claim, its part or its policy has moved."""
    claim = get_success_data(api.get_claim(ctx.claim["id"], UNDERWRITER))
    assert claim["adjustment_status"] == "CLOSED"
    assert claim["settlement_paid_cents"] == 2900000
    assert claim["settled_by_user_id"] == MANAGER_USER_ID
    _, meta = validate_paginated(api.list_claim_ledger_entries(
        ctx.claim["id"], UNDERWRITER, limit=50, offset=0))
    assert meta["total_count"] == 1
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 2900000
    assert part["aggregate_available_cents"] == 197100000
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["incurred_loss_cents"] == 2900000


def test_the_declaring_adjuster_wearing_a_manager_role_is_stopped_on_duties(api):
    """Segregation is tested before the closed claim's own state is consulted.

    PRD: Three further gates apply in order: the settling manager's `X-User-ID` must differ from `declared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; no report on the claim's coverage part may be in status `DELINQUENT`, else `ERR_REPORTING_DELINQUENT`; and `settlement_amount_cents` must not exceed the part's `aggregate_available_cents`, else `ERR_AGGREGATE_LIMIT_EXHAUSTED`.
    PRD: Either branch stores `adjustment_basis`, records the adjuster's `X-User-ID` in `declared_by_user_id`, and recomputes both variants.
    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_claim_state_on_resettle
    """
    ctx = settled_repair_claim(api)
    assert ctx.closed["adjustment_status"] == "CLOSED"
    assert ctx.claim["declared_by_user_id"] == ADJUSTER_USER_ID

    refused = api.settle_claim(
        ctx.claim["id"], make_headers(ADJUSTER_USER_ID, Role.UNDERWRITING_MANAGER))

    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
    assert_the_claim_was_paid_exactly_once(api, ctx)


def test_a_second_manager_is_stopped_on_the_claim_state_instead(api):
    """With duties satisfied the terminal adjustment axis is what refuses the payment.

    PRD: Only an `UnderwritingManager` settles, and only a claim whose `adjustment_status` is `REPAIR_APPROVED` or `TOTAL_LOSS_DECLARED`, else `ERR_CLAIM_NOT_IN_REQUIRED_STATE`.
    PRD: Either branch closes the join: `adjustment_status` advances `SETTLED` → `CLOSED`, `CLOSED` is terminal on the adjustment axis, and `RECOVERED` and `WAIVED` are terminal on the salvage axis.
    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_claim_state_on_resettle
    """
    ctx = settled_repair_claim(api)

    refused = api.settle_claim(ctx.claim["id"], MANAGER_2)

    validate_error(refused, "ERR_CLAIM_NOT_IN_REQUIRED_STATE", 409)
    assert_the_claim_was_paid_exactly_once(api, ctx)
