"""Initial states, declared transitions, terminal lockdown and side-effect execution."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BASELINE_NOT_MET,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_instant_equals,
    assert_integer,
    assert_is_null,
    assert_load,
    assert_pagination_meta,
    assert_trading_gate,
    assert_version_is,
)
from test_helpers.constants import CLOCK_BASE
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    BASELINE_VERIFIER,
    IMPLEMENTATION_VERIFIER,
    REGISTRY,
)


def test_approving_the_first_assessment_is_what_opens_the_program(api):
    """One call stamps the approval and flips the watershed out of PROVISIONAL.

    "if the watershed's `program_status` is still `PROVISIONAL`, the watershed
    transitions `PROVISIONAL → ACTIVE`, `trading_enabled` becomes true, and the
    watershed's `version` increments by 1 — this is the only way a program opens
    for trading."

    Design: Corner/state_machines/watershed_activates_when_its_first_tmdl_assessment_is_approved
    """
    world = fx.scr_allocated(api)
    published = fx.publish_assessment(api, world["assessment_id"])
    assert published["status"] == "PUBLIC_COMMENT", published
    before = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(before, "PROVISIONAL")

    approved = validate_success(
        api.set_assessment_status(
            world["assessment_id"], f.assessment_status_payload("APPROVED"), ADMIN
        )
    )

    assert approved["status"] == "APPROVED", approved
    assert_instant_equals(approved["approved_at"], CLOCK_BASE, "approved_at")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(watershed, "ACTIVE")
    assert watershed["version"] > before["version"], watershed


def test_a_fresh_assessment_opens_in_draft_with_nothing_allocated(api):
    """The declared initial state carries zeroed roll-ups and null derivations.

    "A draft opens in status `DRAFT` with `revision_round` at 0,
    `allocation_variant` and `effective_background_lbs_yr` both null, `version` at 1,
    and every allocation roll-up ... at 0.00."

    Design: Corner/state_machines/tmdl_assessment_starts_in_draft_with_zero_revision_round
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)

    created = validate_success(
        api.create_tmdl_assessment(f.tmdl_assessment_payload(watershed["id"]), ANALYST), 201
    )

    assert created["status"] == "DRAFT", created
    assert_integer(created["revision_round"], 0, "revision_round")
    assert_is_null(created["approved_at"], "approved_at")
    assert_load(created["margin_of_safety_lbs_yr"], 0.00, "margin_of_safety_lbs_yr")
    assert_load(created["allocable_load_lbs_yr"], 0.00, "allocable_load_lbs_yr")
    assert_load(created["wla_total_lbs_yr"], 0.00, "wla_total_lbs_yr")
    assert_load(created["la_total_lbs_yr"], 0.00, "la_total_lbs_yr")
    assert_load(created["reserve_allocation_lbs_yr"], 0.00, "reserve_allocation_lbs_yr")
    assert_is_null(created["effective_background_lbs_yr"], "effective_background_lbs_yr")
    assert_is_null(created["allocation_variant"], "allocation_variant")
    assert_version_is(created, 1)

    still_provisional = get_success_data(api.get_watershed(watershed["id"], ADMIN))
    assert_trading_gate(still_provisional, "PROVISIONAL")


def test_a_withdrawn_assessment_refuses_every_further_status_change(api):
    """WITHDRAWN is terminal, so all three follow-up targets are refused.

    "The full state set is `DRAFT`, `PUBLIC_COMMENT`, `REVISION`, `APPROVED`,
    `WITHDRAWN` and `SUPERSEDED`, with `WITHDRAWN` and `SUPERSEDED` terminal."

    Design: Corner/state_machines/withdrawn_tmdl_assessment_rejects_any_further_status_change
    """
    world = fx.scr_base(api)
    assessment_id = world["assessment_id"]
    withdrawn = validate_success(
        api.set_assessment_status(
            assessment_id,
            f.assessment_status_payload("WITHDRAWN", "Loading capacity study invalidated."),
            ADMIN,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN", withdrawn

    validate_error(
        api.set_assessment_status(
            assessment_id, f.assessment_status_payload("PUBLIC_COMMENT"), ANALYST
        ),
        ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.set_assessment_status(assessment_id, f.assessment_status_payload("APPROVED"), ADMIN),
        ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.set_assessment_status(assessment_id, f.assessment_status_payload("WITHDRAWN"), ADMIN),
        ERR_INVALID_STATE,
        409,
    )

    frozen = get_success_data(api.get_tmdl_assessment(assessment_id, ANALYST))
    assert frozen["status"] == "WITHDRAWN", frozen
    assert_is_null(frozen["approved_at"], "approved_at")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(watershed, "PROVISIONAL")


def test_revision_cannot_be_requested_while_the_assessment_is_still_a_draft(api):
    """REVISION is declared only out of PUBLIC_COMMENT.

    "A `ProgramAdministrator` moves `PUBLIC_COMMENT → REVISION` when comments
    require rework, and that transition increments `revision_round` by 1."

    Design: Corner/state_machines/revision_target_from_draft_is_rejected_as_invalid_state
    """
    world = fx.scr_base(api)

    refused = api.set_assessment_status(
        world["assessment_id"], f.assessment_status_payload("REVISION"), ADMIN
    )

    validate_error(refused, ERR_INVALID_STATE, 409)

    unchanged = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert unchanged["status"] == "DRAFT", unchanged
    assert_integer(unchanged["revision_round"], 0, "revision_round")


def test_a_second_adaptive_hold_on_a_held_watershed_is_refused_without_a_write(api):
    """The hold transition is declared only from ACTIVE, so a repeat is not idempotent.

    "`ACTIVE → ADAPTIVE_HOLD` suspends the market. ... `TERMINATED` is terminal,
    and `PROVISIONAL → ACTIVE` is not available through this operation at all"

    Design: Corner/state_machines/second_adaptive_hold_request_on_a_held_watershed_is_rejected
    """
    world = fx.scr_active_program(api)
    held = fx.set_program_status(api, world["watershed_id"], "ADAPTIVE_HOLD", "First hold.")
    assert_trading_gate(held, "ADAPTIVE_HOLD")
    version_after_hold = held["version"]

    refused = api.set_program_status(
        world["watershed_id"],
        f.program_status_payload("ADAPTIVE_HOLD", "Second hold attempt."),
        ADMIN,
    )

    validate_error(refused, ERR_INVALID_STATE, 409)

    reread = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(reread, "ADAPTIVE_HOLD")
    assert_integer(reread["version"], version_after_hold, "version after a rejected transition")


def test_the_baseline_verifier_may_not_also_verify_the_implementation(api):
    """The second inspection must come from a different principal.

    "It requires that the acting `X-User-ID` differs from the stored
    `baseline_verifier_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES` otherwise"

    Design: Corner/state_machines/implementation_event_by_the_baseline_verifier_is_rejected
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    reaches = fx.scr_reaches(api, watershed["id"])
    producer_id = fx.make_producer(api)["id"]
    project = fx.make_practice_project(api, producer_id, reaches["r_up"]["id"], "T-101")
    fx.verify_baseline_pass(api, project["id"])

    self_inspection = api.create_verification_event(
        f.verification_event_payload(
            project["id"],
            "IMPLEMENTATION",
            "PASS",
            narrative="Self-inspection by the baseline verifier.",
            verified_acres=80.00,
        ),
        BASELINE_VERIFIER,
    )

    validate_error(self_inspection, ERR_SEGREGATION_OF_DUTIES, 409)

    stalled = get_success_data(api.get_practice_project(project["id"], REGISTRY))
    assert stalled["status"] == "BASELINE_VERIFIED", stalled
    assert_is_null(stalled["verified_acres"], "verified_acres")
    _, meta = validate_paginated(
        api.list_verification_events(REGISTRY, {"practice_project_id": project["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 1, False)

    independent = validate_success(
        api.create_verification_event(
            f.verification_event_payload(
                project["id"],
                "IMPLEMENTATION",
                "PASS",
                narrative="Independent inspection of the cover crop stand.",
                verified_acres=80.00,
            ),
            IMPLEMENTATION_VERIFIER,
        ),
        201,
    )
    assert independent["resulting_project_status"] == "IMPLEMENTED", independent

    implemented = get_success_data(api.get_practice_project(project["id"], REGISTRY))
    assert implemented["status"] == "IMPLEMENTED", implemented
    assert_load(implemented["verified_acres"], 80.00, "verified_acres")
    assert implemented["implementation_verifier_user_id"] == "verifier-2", implemented


def test_a_baseline_pass_is_refused_on_a_tract_that_has_not_met_baseline(api):
    """The regulatory baseline cannot be traded around; only a FAIL is available.

    "requires `baseline_met` to be true — the regulatory baseline requirement
    cannot be traded around, and an attempt to pass the baseline of a project whose
    `baseline_met` is false is rejected with `ERR_BASELINE_NOT_MET`."

    Design: Corner/state_machines/baseline_pass_on_a_project_that_fails_the_baseline_is_rejected
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    reaches = fx.scr_reaches(api, watershed["id"])
    producer_id = fx.make_producer(api)["id"]
    project = fx.make_practice_project(
        api,
        producer_id,
        reaches["r_up"]["id"],
        "T-500",
        enrolled_acres=50.00,
        baseline_met=False,
        pre_load_lbs_yr=500.00,
        post_load_lbs_yr=200.00,
    )

    refused = api.create_verification_event(
        f.verification_event_payload(
            project["id"],
            "BASELINE",
            "PASS",
            narrative="Attempting to pass a tract that has not met baseline.",
        ),
        BASELINE_VERIFIER,
    )

    validate_error(refused, ERR_BASELINE_NOT_MET, 422)

    unchanged = get_success_data(api.get_practice_project(project["id"], REGISTRY))
    assert unchanged["status"] == "REGISTERED", unchanged
    assert_is_null(unchanged["baseline_verifier_user_id"], "baseline_verifier_user_id")
    _, meta = validate_paginated(
        api.list_verification_events(REGISTRY, {"practice_project_id": project["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 0, False)

    failed = fx.file_verification_event(
        api,
        project["id"],
        "BASELINE",
        "FAIL",
        BASELINE_VERIFIER,
        narrative="Tract T-500 does not meet the regulatory baseline.",
    )
    assert failed["resulting_project_status"] == "REVOKED", failed
    revoked = get_success_data(api.get_practice_project(project["id"], REGISTRY))
    assert revoked["status"] == "REVOKED", revoked


def test_a_second_allocation_run_supersedes_the_first_and_replaces_its_reserve(api):
    """The new run takes over every source row and the reserve pool is not doubled.

    "Creating a run when another run on the same assessment is already `ACTIVE`
    moves that older run `ACTIVE → SUPERSEDED` ... the watershed's
    `reserve_pool_lbs` ... is replaced rather than accumulated."

    Design: Corner/state_machines/creating_a_second_allocation_run_supersedes_the_first
    """
    world = fx.scr_allocated(api)

    second = fx.make_allocation_run(api, world["assessment_id"], "RUN-2")

    assert second["status"] == "ACTIVE", second
    assert_load(second["reserve_allocation_lbs_yr"], 2400.00, "reserve_allocation_lbs_yr")

    first = get_success_data(api.get_allocation_run(world["run_id"], ANALYST))
    assert first["status"] == "SUPERSEDED", first

    _, meta = validate_paginated(
        api.list_allocation_runs(
            ANALYST, {"tmdl_assessment_id": world["assessment_id"], "status": "ACTIVE"}
        )
    )
    assert_pagination_meta(meta, 10, 0, 1, False)

    expected = {"sa_p1": 21888.00, "sa_p2": 5472.00, "sa_n1": 13680.00, "sa_n2": 4560.00}
    for key, amount in expected.items():
        source = get_success_data(api.get_source_assessment(world[key]["id"], ANALYST))
        assert_load(source["allocated_load_lbs_yr"], amount, "{} allocation".format(key))
        assert source["allocation_run_id"] == second["id"], source

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs is replaced, not added")
    assert_load(watershed["allocated_wla_total_lbs_yr"], 27360.00, "allocated_wla_total_lbs_yr")
    assert_load(watershed["allocated_la_total_lbs_yr"], 18240.00, "allocated_la_total_lbs_yr")


def test_partial_retirement_keeps_the_batch_issued_then_the_balance_locks_it(api):
    """Retirement moves two buckets and only the exhausting move changes the status.

    "The status change to `RETIRED` fires only when the move leaves `available_lbs`
    at exactly 0.00; a partial retirement ... moves the buckets and bumps the version
    but leaves the batch's `status` unchanged"

    Design: Corner/state_machines/partial_retirement_moves_buckets_then_full_retirement_locks_the_batch
    """
    world = fx.scr_active_program(api)
    producer_id = fx.make_producer(api)["id"]
    project = fx.implemented_project(api, producer_id, world["reaches"]["r_up"]["id"], "T-101")
    batch = fx.certify_project(api, project["id"])
    assert_integer(batch["issued_lbs"], 520, "issued_lbs")
    assert_batch_buckets(batch, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)

    partial = fx.retire_batch(
        api, batch["id"], 120.00, "Voluntary partial retirement into the reserve pool."
    )

    assert partial["status"] == "ISSUED", partial
    assert_batch_buckets(partial, available=400.00, reserved=0.00, retired=120.00, invalidated=0.00)
    after_partial = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(after_partial["reserve_pool_lbs"], 2520.40, "reserve_pool_lbs")

    remainder = fx.retire_batch(api, batch["id"], 400.00, "Retiring the balance of the batch.")

    assert remainder["status"] == "RETIRED", remainder
    assert_batch_buckets(remainder, available=0.00, reserved=0.00, retired=520.00, invalidated=0.00)
    after_full = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(after_full["reserve_pool_lbs"], 2920.40, "reserve_pool_lbs")

    exhausted = api.retire_credit_batch(
        batch["id"], f.retire_payload(10.00, "Attempt to retire from an exhausted batch."), REGISTRY
    )
    validate_error(exhausted, ERR_INVALID_STATE, 409)

    final = get_success_data(api.get_credit_batch(batch["id"], REGISTRY))
    assert_integer(final["issued_lbs"], 520, "issued_lbs")
    assert_batch_buckets(final, available=0.00, reserved=0.00, retired=520.00, invalidated=0.00)
