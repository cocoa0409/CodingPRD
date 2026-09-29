"""Operations refused because of the state of a row they only reference.

The gross-to-net submission is legal against its own cycle but forbidden by the
standing of the provider engaged two rows away, and the transition completion is
legal for the engagement but forbidden by a period that is still mid-flight.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CYCLE_INVALID_STATE, ERR_PROVIDER_SUSPENDED
from test_helpers.constants import (
    CYCLE_INPUTS_LOCKED,
    DECISION_APPROVE,
    DECISION_COMPLETE,
    ENGAGEMENT_REMEDIATION_REQUIRED,
    ENGAGEMENT_TRANSITION_IN_PROGRESS,
    ENGAGEMENT_TRANSITION_PLANNED,
    PROVIDER_ACTIVE,
    PROVIDER_SUSPENDED,
    SEV1,
)
from test_helpers.test_users import CONTROLLER_HEADERS, PLATFORM_ADMIN_HEADERS


def _suspended_provider_locked_cycle(api):
    """A locked period whose provider has been suspended by three confirmed SEV1s."""
    ctx = fx.setup_locked_cycle(api)
    for _ in range(3):
        fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(provider, status=PROVIDER_SUSPENDED, service_score=25.00)
    return ctx


def _transition_in_progress_over_a_live_cycle(api):
    """An approved transition plan while one period of the engagement is still locked."""
    ctx = fx.setup_locked_cycle(api)
    rival = fx.create_rival_provider(api)
    engagement = fx.read_engagement(api, ctx["engagement_id"])

    planned = fx.plan_transition(
        api, ctx["engagement_id"], rival["id"], engagement["version"]
    )
    assert planned["status"] == ENGAGEMENT_TRANSITION_PLANNED, (
        f"a written plan moves the engagement, got {planned['status']}"
    )
    in_progress = fx.decide_transition(
        api, ctx["engagement_id"], {"decision": DECISION_APPROVE}
    )
    assert in_progress["status"] == ENGAGEMENT_TRANSITION_IN_PROGRESS, (
        f"APPROVE starts the transition, got {in_progress['status']}"
    )
    ctx = dict(ctx)
    ctx["rival_id"] = rival["id"]
    return ctx


def _complete_transition(api, engagement_id):
    return api.transition_decision(
        engagement_id,
        {"decision": DECISION_COMPLETE, "knowledge_transfer_confirmed": True},
        PLATFORM_ADMIN_HEADERS,
    )


def test_suspended_provider_may_not_submit_results_for_its_locked_cycle(api):
    """The cycle is in exactly the state a submission requires, but the suspension of
    the engaged provider forbids new results.

    PRD 3.8: "Suspension carries one additional prohibition beyond the holds: no new
    gross-to-net run may be created for any cycle of a suspended provider, which is
    the `ERR_PROVIDER_SUSPENDED` rejection described with the results workflow."

    Design: Difficulty/cross_entity_state_dependency/gtn_run_creation_gated_by_engaged_provider_suspension
    """
    ctx = _suspended_provider_locked_cycle(api)
    cycle = fx.read_cycle(api, ctx["cycle_id"])

    response = api.create_gtn_run(
        f.gtn_run_payload(ctx["cycle_id"], ctx["input_file_id"], cycle["version"]),
        ctx["provider_headers"],
    )
    validate_error(response, ERR_PROVIDER_SUSPENDED, 409)

    runs, meta = validate_paginated(
        api.list_gtn_runs(CONTROLLER_HEADERS, {"cycle_id": ctx["cycle_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert runs == [], f"no run should have been created, got {runs}"


def test_suspension_holds_no_cycle_that_had_already_left_draft(api):
    """The suspension cascade moved the engagement into remediation but could not
    hold a period that was already locked, which keeps a null hold reason.

    PRD 3.8: "When a provider becomes `PROBATION` or `SUSPENDED`, every engagement of
    that provider whose `status` is `ACTIVE` moves `ACTIVE → REMEDIATION_REQUIRED` and
    has its `transition_required` set to true, and every cycle of those engagements
    sitting in `DRAFT` moves `DRAFT → ON_HOLD` with `hold_reason` set to
    `PROVIDER_PROBATION` when the provider is on probation or `PROVIDER_SUSPENSION`
    when the provider is suspended."

    Design: Difficulty/cross_entity_state_dependency/gtn_run_creation_gated_by_engaged_provider_suspension
    """
    ctx = _suspended_provider_locked_cycle(api)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_REMEDIATION_REQUIRED, (
        f"the engagement is in remediation, got {engagement['status']}"
    )
    assert engagement["transition_required"] is True, (
        f"transition_required is set, got {engagement['transition_required']}"
    )


def test_transition_completion_is_refused_while_a_period_is_mid_flight(api):
    """Even with the knowledge transfer confirmed, a locked period blocks the
    cutover, because the live-cycle check is taken first.

    PRD 3.8: "First, at the state rank, no cycle of the engagement may be mid-flight:
    if any cycle of the engagement is in `INPUTS_LOCKED`, `RESULTS_APPROVED` or
    `FUNDED`, the completion is rejected with `ERR_CYCLE_INVALID_STATE` (HTTP 409) — a
    period that is already running must finish or be cancelled before the provider
    changes hands."

    Design: Difficulty/cross_entity_state_dependency/transition_completion_gated_by_live_payroll_cycle_state
    """
    ctx = _transition_in_progress_over_a_live_cycle(api)

    response = _complete_transition(api, ctx["engagement_id"])
    validate_error(response, ERR_CYCLE_INVALID_STATE, 409)

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_TRANSITION_IN_PROGRESS, (
        f"the engagement stays mid-transition, got {engagement['status']}"
    )


def test_refused_cutover_reassigns_nothing(api):
    """The plan survives intact, the incumbent is still the engaged provider and the
    incoming provider has taken nothing over.

    PRD 3.8: "On success, the outgoing provider is noted, `provider_id` is reassigned
    to `transition_incoming_provider_id`, all four `transition_*` plan fields are
    reset to null, `transition_required` is cleared to false, and the engagement moves
    `TRANSITION_IN_PROGRESS → ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/transition_completion_gated_by_live_payroll_cycle_state
    """
    ctx = _transition_in_progress_over_a_live_cycle(api)

    _complete_transition(api, ctx["engagement_id"])

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["provider_id"] == ctx["provider_id"], (
        "the engaged provider is unchanged, got "
        f"{engagement['provider_id']!r}"
    )
    assert engagement["transition_incoming_provider_id"] == ctx["rival_id"], (
        "the plan still names the incoming provider, got "
        f"{engagement['transition_incoming_provider_id']!r}"
    )

    incumbent = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(incumbent, status=PROVIDER_ACTIVE)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)
