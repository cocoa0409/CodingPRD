"""State-machine corners: invalid transitions rejected, lazy auto-transitions
for activations and grants, and the deliverable reject-and-resubmit loop."""

from test_helpers import (
    account_with_contract,
    create_activation,
    create_approved_grant,
    create_approved_segment,
    create_cycle,
    create_deliverable,
    create_grant,
    create_ready_report,
    get_success_data,
    ingest_category_households,
    make_data_steward_headers,
    read_contract,
    read_grant,
    set_clock,
    validate_error,
)
from test_helpers import ApiErrorId
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]
MANAGER = TEST_USERS["category_manager_headers"]
SCIENTIST = TEST_USERS["insights_scientist_headers"]
STEWARD = TEST_USERS["data_steward_headers"]


def _ready_report_world(api, name, activation_budget_cents=100000):
    """Contract + SNACKS scope + 20 households + one READY CATEGORY report."""
    world = account_with_contract(
        api,
        name=name,
        scope_category="SNACKS",
        scope_brands=["ACME"],
        activation_budget_cents=activation_budget_cents,
    )
    ingest_category_households(api, 20, "c")
    report = create_ready_report(api, world["contract"]["id"], world["analyst_headers"])
    return world, report


def test_cancel_ready_report_returns_not_cancellable(api):
    """A READY report rejects cancellation and keeps its finalized credit.

    PRD: "A `SupplierAnalyst` may cancel a report while it is still `REQUESTED` (any other state fails with `ERR_REPORT_NOT_CANCELLABLE`)"
    PRD: "If all cells pass, the report moves to `READY` and the reservation finalizes: the reserved counter decreases by `credit_cost` and the consumed counter increases by the same amount."
    Design: Corner/state_machines/cancel_ready_report_returns_not_cancellable
    """
    world, report = _ready_report_world(api, "Sigma Soup")
    validate_error(
        api.cancel_report(report["id"], world["analyst_headers"]),
        ApiErrorId.REPORT_NOT_CANCELLABLE.value,
        409,
    )
    observed = get_success_data(api.get_insight_report(report["id"], ADMIN))
    assert observed["status"] == "READY"
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_consumed"] == 1


def test_grant_double_approve_rejected(api):
    """Approving an already-APPROVED grant fails; the grant stays APPROVED.

    PRD: "Approval requires the grant to be `REQUESTED` (else `ERR_GRANT_NOT_APPROVABLE`)"
    Design: Corner/state_machines/grant_double_approve_rejected
    """
    world = account_with_contract(api, name="Tau Thyme")
    grant = create_grant(api, world["account"]["id"])
    steward = make_data_steward_headers("steward-8")
    get_success_data(api.approve_grant(grant["id"], steward))
    validate_error(api.approve_grant(grant["id"], steward), ApiErrorId.GRANT_NOT_APPROVABLE.value, 409)
    observed = read_grant(api, grant["id"])
    assert observed["status"] == "APPROVED"


def test_cycle_lock_from_scheduled_rejected(api):
    """At the default clock a cycle whose open_at is still in the future rejects locking.

    PRD: "A `CategoryManager` locks a cycle only from `OPEN` (else `ERR_CYCLE_NOT_LOCKABLE`), moving it to `LOCKED`."
    Design: Corner/state_machines/cycle_lock_from_scheduled_rejected
    """
    cycle = create_cycle(api, category_code="DAIRY", window_start="2026-10-01", window_end="2026-10-15")
    validate_error(api.lock_cycle(cycle["id"], MANAGER), ApiErrorId.CYCLE_NOT_LOCKABLE.value, 409)
    from test_helpers import read_cycle

    assert read_cycle(api, cycle["id"])["status"] == "SCHEDULED"


def test_activation_auto_completes_after_measurement_window(api):
    """Twenty-eight days after launch, the activation reads as COMPLETED.

    PRD: "when the logical clock reaches the instant twenty-eight days after `launched_at` — the standard measurement window — the activation completes automatically, moving to the terminal `COMPLETED` state."
    Design: Corner/state_machines/activation_auto_completes_after_measurement_window
    """
    world = account_with_contract(api, name="Phi Fig", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 25, "a")
    segment = create_approved_segment(api, world["contract"]["id"], world["analyst_headers"], segment_name="Auto")
    activation = create_activation(api, segment, world["analyst_headers"])
    launched = get_success_data(api.launch_activation(activation["id"], world["analyst_headers"]))
    assert launched["status"] == "LAUNCHED"
    set_clock(api, "2026-09-29T00:00:00Z")
    activations = get_success_data(
        api.list_segment_activations(segment["id"], world["analyst_headers"])
    )
    assert activations[0]["status"] == "COMPLETED"


def _deliverable_world(api, name):
    """READY report + cycle (open_at 2026-09-06) + PLANNED deliverable, clock 2026-09-07."""
    world, report = _ready_report_world(api, name)
    cycle = create_cycle(api)
    deliverable = create_deliverable(api, cycle["id"], world["contract"]["id"], report["id"])
    set_clock(api, "2026-09-07T00:00:00Z")
    return world, report, cycle, deliverable


def test_deliverable_reject_resubmit_cycle(api):
    """A REJECTED deliverable may be resubmitted, and neither pass was late.

    PRD: "A deliverable may be submitted from `PLANNED` or from `REJECTED` — resubmission after rejection is expected"
    PRD: "Rejection moves it back to `REJECTED`, from which it may be resubmitted"
    Design: Corner/state_machines/deliverable_reject_resubmit_cycle
    """
    _, _, _, deliverable = _deliverable_world(api, "Chi Chips")
    first = get_success_data(api.submit_deliverable(deliverable["id"], SCIENTIST))
    assert first["status"] == "SUBMITTED"
    assert first["is_late"] is False
    rejected = get_success_data(api.reject_deliverable(deliverable["id"], MANAGER))
    assert rejected["status"] == "REJECTED"
    resubmitted = get_success_data(api.submit_deliverable(deliverable["id"], SCIENTIST))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["is_late"] is False


def test_grant_lazy_expiry_at_valid_until(api):
    """At clock == valid_until the half-open window is closed: the query fails and the grant flips EXPIRED.

    PRD: "the logical clock must be before `valid_until` (a submission at or after the window's end flips the grant to `EXPIRED` and fails with `ERR_GRANT_EXPIRED`)"
    Design: Corner/state_machines/grant_lazy_expiry_at_valid_until
    """
    world = account_with_contract(api, name="Psi Plums")
    grant = create_approved_grant(
        api,
        world["account"]["id"],
        steward_user_id="steward-10",
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-10-01T00:00:00Z",
    )
    set_clock(api, "2026-10-01T00:00:00Z")
    resp = api.submit_query(
        grant["id"],
        {"dataset_joins": ["SALES"], "estimated_rows": 1000},
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.GRANT_EXPIRED.value, 409)
    observed = read_grant(api, grant["id"])
    assert observed["status"] == "EXPIRED"
