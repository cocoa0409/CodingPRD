"""Care plans and staged procedures: one-in-flight gating, defer/replan cycle,
completion bubble-up, due-date gating, and the parallel funding dimension."""
from test_helpers import (
    ApiErrorId,
    add_stage,
    commit_allocation,
    create_allocation,
    create_fund,
    get_application,
    get_care_plan,
    get_stage,
    schedule_stage,
    set_clock,
    setup_accepted_staged_application,
    setup_care_plan_with_scheduled_stage,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine
# ---------------------------------------------------------------------------

def test_care_plan_parallel_clinical_and_funding_dimensions_schedule(api):
    """PRD §3.6: "Scheduling the plan's very first stage moves the plan from `PLANNING` to `ACTIVE_TREATMENT` automatically."

    Design: Difficulty/non_linear_state_machine/care_plan_parallel_clinical_and_funding_dimensions
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, plan = setup_accepted_staged_application()
    stage = add_stage(plan["id"])
    schedule_stage(stage["id"])

    after_schedule = get_care_plan(plan["id"])
    assert after_schedule["clinical_status"] == "ACTIVE_TREATMENT"
    assert after_schedule["funding_status"] == "UNFUNDED"


def test_care_plan_parallel_clinical_and_funding_dimensions_commit(api):
    """PRD §3.9: "Whenever an allocation naming a `care_plan_id` is committed or released, the designated plan's funding dimension is recomputed."

    Design: Difficulty/non_linear_state_machine/care_plan_parallel_clinical_and_funding_dimensions
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, plan = setup_accepted_staged_application()
    stage = add_stage(plan["id"])  # cost 200000
    schedule_stage(stage["id"])

    hospital_id = _hospital_of(plan)
    fund = create_fund(fund_name="Burn Fund 2026", total_committed_cents=500000)
    allocation = create_allocation(
        fund["id"], hospital_id, care_plan_id=plan["id"], amount_cents=200000,
    )
    commit_allocation(allocation["id"], expected_fund_version=fund["version"])

    after_commit = get_care_plan(plan["id"])
    assert after_commit["clinical_status"] == "ACTIVE_TREATMENT"
    assert after_commit["funding_status"] == "FULLY_FUNDED"

    fund_after = __import__("test_helpers").get_fund(fund["id"])
    assert fund_after["allocated_cents"] == 200000
    assert fund_after["available_cents"] == 300000


def _hospital_of(plan):
    from test_helpers import api_client, get_success_data, make_admin_headers
    application = get_application(plan["application_id"])
    program = get_success_data(
        api_client.get_program(application["program_id"], make_admin_headers("admin-1"))
    )
    return program["hospital_id"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade
# ---------------------------------------------------------------------------

def test_acceptance_cascade_funding_recompute_on_stage_creation(api, care_headers):
    """PRD §3.9: "The plan is `UNFUNDED` when the designated amount is 0; `FULLY_FUNDED` when the designated amount is at least the remaining need and the remaining need is above 0 — and also when the remaining need has fallen to 0 (all stages terminal) while designated funds remain; and `PARTIALLY_FUNDED` when the designated amount is above 0 but below the remaining need."

    Design: Difficulty/transitive_cascade/acceptance_cascade_application_to_billing_to_careplan_funding
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, plan = setup_accepted_staged_application()
    hospital_id = _hospital_of(plan)
    fund = create_fund(fund_name="Burn Fund 2026", total_committed_cents=500000)
    allocation = create_allocation(
        fund["id"], hospital_id, care_plan_id=plan["id"], amount_cents=150000,
    )
    commit_allocation(allocation["id"], expected_fund_version=fund["version"])

    # No stages yet: remaining need 0 with designated 150000 -> FULLY_FUNDED.
    funded = get_care_plan(plan["id"])
    assert funded["funding_status"] == "FULLY_FUNDED"

    # Adding a 200000-cent stage grows remaining need above designated.
    stage = add_stage(plan["id"])
    partial = get_care_plan(plan["id"])
    assert partial["funding_status"] == "PARTIALLY_FUNDED"
    assert get_stage(stage["id"])["status"] == "PLANNED"


def test_acceptance_cascade_partial_funding_blocks_discharge(api, care_headers):
    """PRD §3.6: "From `SURVEILLANCE`, the plan may be discharged provided its funding dimension is not `PARTIALLY_FUNDED` — a plan holding a partial designation cannot close until its allocations resolve to `COMMITTED` or are withdrawn, else `ERR_PLAN_FUNDING_UNRESOLVED` (HTTP 409)."

    Design: Difficulty/transitive_cascade/acceptance_cascade_application_to_billing_to_careplan_funding
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, plan = setup_accepted_staged_application()
    hospital_id = _hospital_of(plan)
    fund = create_fund(fund_name="Burn Fund 2026", total_committed_cents=500000)
    allocation = create_allocation(
        fund["id"], hospital_id, care_plan_id=plan["id"], amount_cents=150000,
    )
    commit_allocation(allocation["id"], expected_fund_version=fund["version"])
    add_stage(plan["id"])
    assert get_care_plan(plan["id"])["funding_status"] == "PARTIALLY_FUNDED"

    resp = api.discharge_care_plan(plan["id"], care_headers)
    validate_error(resp, ApiErrorId.ERR_PLAN_FUNDING_UNRESOLVED.value, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency (stages)
# ---------------------------------------------------------------------------

def test_stage_one_in_flight_gate_and_defer_replan_cycle_gate(api, care_headers):
    """PRD §3.6: "and only when no other stage of the same plan is already `SCHEDULED` — one stage in flight at a time — else `ERR_STAGE_ALREADY_IN_FLIGHT` (HTTP 409)."

    Design: Corner/state_machines/stage_one_in_flight_gate_and_defer_replan_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, plan = setup_accepted_staged_application()
    sp1 = add_stage(plan["id"], stage_index=1, min_age_months=60, max_age_months=120,
                    scheduled_date="2026-10-01T00:00:00Z", estimated_cost_cents=100000)
    sp2 = add_stage(plan["id"], stage_index=2, min_age_months=70, max_age_months=130,
                    scheduled_date="2026-11-01T00:00:00Z", estimated_cost_cents=100000)
    schedule_stage(sp1["id"])

    resp = api.schedule_stage(sp2["id"], care_headers)
    validate_error(resp, ApiErrorId.ERR_STAGE_ALREADY_IN_FLIGHT.value, expected_status=409)


def test_stage_one_in_flight_defer_replan_reenables_second_stage(api, care_headers):
    """PRD §3.6: "A scheduled stage may instead be deferred to `DEFERRED`, and a deferred stage may be replanned back to `PLANNED` by supplying a `new_scheduled_date` — which re-checks the same age window against the new date (failing again with `ERR_AGE_WINDOW_VIOLATION`) and rewrites `scheduled_date`."

    Design: Corner/state_machines/stage_one_in_flight_gate_and_defer_replan_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, plan = setup_accepted_staged_application()
    sp1 = add_stage(plan["id"], stage_index=1, min_age_months=60, max_age_months=120,
                    scheduled_date="2026-10-01T00:00:00Z", estimated_cost_cents=100000)
    sp2 = add_stage(plan["id"], stage_index=2, min_age_months=70, max_age_months=130,
                    scheduled_date="2026-11-01T00:00:00Z", estimated_cost_cents=100000)
    schedule_stage(sp1["id"])

    validate_success(api.defer_stage(sp1["id"], care_headers))
    assert get_stage(sp1["id"])["status"] == "DEFERRED"

    replanned = validate_success(api.replan_stage(
        sp1["id"], "2026-12-01T00:00:00Z", care_headers,
    ))
    assert replanned["status"] == "PLANNED"
    assert replanned["scheduled_date"] == "2026-12-01T00:00:00Z"

    scheduled2 = validate_success(api.schedule_stage(sp2["id"], care_headers))
    assert scheduled2["status"] == "SCHEDULED"
    assert get_care_plan(plan["id"])["clinical_status"] == "ACTIVE_TREATMENT"


# ---------------------------------------------------------------------------
# Corner/state_machines (stages)
# ---------------------------------------------------------------------------

def test_stage_completion_bubbles_plan_to_surveillance(api, care_headers):
    """PRD §3.6: "Once the logical clock reaches the `scheduled_date`, a `CareCoordinator` may complete the stage (completing early fails with `ERR_STAGE_NOT_DUE`, HTTP 409), incrementing `completed_stage_count`; when the completed count reaches `planned_stage_count`, the plan advances automatically from `ACTIVE_TREATMENT` to `SURVEILLANCE`."

    Design: Corner/state_machines/stage_completion_bubbles_plan_to_surveillance
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, plan, stage = setup_care_plan_with_scheduled_stage(
        stage_overrides={"estimated_cost_cents": 100000},
    )
    set_clock("2026-10-01T00:00:00Z")
    completed = validate_success(api.complete_stage(stage["id"], care_headers))
    assert completed["status"] == "COMPLETED"

    plan_after = get_care_plan(plan["id"])
    assert plan_after["completed_stage_count"] == 1
    assert plan_after["planned_stage_count"] == 1
    assert plan_after["clinical_status"] == "SURVEILLANCE"
    assert plan_after["funding_status"] == "UNFUNDED"


def test_complete_before_scheduled_date_rejected(api, care_headers):
    """PRD §3.6: "Once the logical clock reaches the `scheduled_date`, a `CareCoordinator` may complete the stage (completing early fails with `ERR_STAGE_NOT_DUE`, HTTP 409), incrementing `completed_stage_count`; when the completed count reaches `planned_stage_count`, the plan advances automatically from `ACTIVE_TREATMENT` to `SURVEILLANCE`."

    Design: Corner/state_machines/complete_before_scheduled_date_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, _, _, _, stage = setup_care_plan_with_scheduled_stage(
        stage_overrides={"estimated_cost_cents": 100000},
    )
    set_clock("2026-09-30T00:00:00Z")
    resp = api.complete_stage(stage["id"], care_headers)
    validate_error(resp, ApiErrorId.ERR_STAGE_NOT_DUE.value, expected_status=409)

    set_clock("2026-10-01T00:00:00Z")
    completed = validate_success(api.complete_stage(stage["id"], care_headers))
    assert completed["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Corner/state_machines (billing) — settle gate
# ---------------------------------------------------------------------------

def test_settle_blocked_by_open_claim_then_succeeds(api, billing_headers):
    """PRD §3.5: "Settlement is blocked while any claim is still open (`ERR_OPEN_CLAIMS_EXIST`, HTTP 409); when it proceeds, the settle recomputes `family_balance_cents`, sweeps any nonzero residue into `charity_writeoff_cents` before storing — the no-balance-billing invariant's final enforcement — and moves the account to the terminal `SETTLED` state."

    Design: Corner/state_machines/settle_blocked_by_open_claim_then_succeeds
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_claim_payload, setup_accepted_application
    _, _, _, _, account = setup_accepted_application(
        with_insurance=True, patient_full_name="Kid Settle",
    )
    claim = validate_success(api.create_claim(
        account["id"], create_claim_payload(), billing_headers,
    ), expected_status=201)

    blocked = api.settle_billing_account(account["id"], billing_headers)
    validate_error(blocked, ApiErrorId.ERR_OPEN_CLAIMS_EXIST.value, expected_status=409)

    validate_success(api.adjudicate_claim(claim["id"], billing_headers))
    mid = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert mid["open_claim_cents"] == 0

    settled = validate_success(api.settle_billing_account(account["id"], billing_headers))
    assert settled["status"] == "SETTLED"
    assert settled["family_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/state_machines (billing) — no-coverage gate
# ---------------------------------------------------------------------------

def test_claim_submit_on_uninsured_account_rejected(api, billing_headers):
    """PRD §3.5: "Claim submission requires the account's `insurance_policy_id` to reference a policy with `coverage_exists` true and status `VERIFIED`; without billable coverage the submission is rejected with `ERR_NO_BILLABLE_COVERAGE` (HTTP 409)."

    Design: Corner/state_machines/claim_submit_on_uninsured_account_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_claim_payload, setup_accepted_application
    _, _, _, _, account = setup_accepted_application(
        patient_full_name="Kid Uninsured",
    )
    assert account["insurance_policy_id"] is None

    resp = api.create_claim(account["id"], create_claim_payload(), billing_headers)
    validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_COVERAGE.value, expected_status=409)

    after = validate_success(api.get_billing_account(account["id"], billing_headers))
    assert after["open_claim_cents"] == 0
