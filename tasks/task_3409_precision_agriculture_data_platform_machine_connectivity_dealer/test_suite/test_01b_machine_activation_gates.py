"""Machine activation gates and the modem provisioning retry loop."""

from test_helpers import (
    ApiErrorId,
    SYSTEM,
    add_machine,
    begin_provisioning,
    complete_provisioning,
    create_plan,
    provision_modem_success,
    read_machine,
    setup_connected_machine,
    setup_org_dealer,
    suspend_dealer,
    validate_error,
)


def test_provisioning_attempts_exhausted_at_limit(api):
    """PRD section 3.1: "the begin is allowed only while fewer than five
    attempts have been recorded, so the fifth begin is the last legal one and
    any further begin is rejected with
    `ERR_PROVISIONING_ATTEMPTS_EXHAUSTED`."

    Design: Corner/validations/provisioning_attempts_exhausted_at_limit
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]
    for _ in range(5):
        begin_provisioning(ctx, api, machine_id)
        complete_provisioning(api, machine_id, outcome="PROVISION_FAILED")

    response = api.provision_modem(machine_id, headers=ctx["dealer_headers"])
    validate_error(response, ApiErrorId.ERR_PROVISIONING_ATTEMPTS_EXHAUSTED)
    machine = read_machine(ctx, api, machine_id)
    assert machine["provisioning_attempts"] == 5
    assert machine["modem_status"] == "PROVISION_FAILED"


def test_dealer_suspended_blocks_machine_activation(api):
    """PRD section 3.1: "Suspending a dealer — again a `PlatformAdmin` action —
    flips it to `SUSPENDED` and blocks every new machine activation, diagnostic
    session, and warranty claim attempted by that dealer with
    `ERR_DEALER_SUSPENDED`, while existing `OPEN` sessions and
    already-`SUBMITTED` claims are deliberately left unaffected."

    Design: Corner/validations/dealer_suspended_blocks_machine_activation
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    suspend_dealer(api, ctx["dealer"]["id"])

    response = api.activate_machine(machine_id, headers=ctx["dealer_headers"])
    validate_error(response, ApiErrorId.ERR_DEALER_SUSPENDED)
    machine = read_machine(ctx, api, machine_id)
    assert machine["lifecycle_status"] == "REGISTERED"


def test_activate_without_provisioning_reports_modem_first(api):
    """PRD section 3.1: "Its preconditions are evaluated in order: the caller's
    dealer must be `ACTIVE` (`ERR_DEALER_SUSPENDED`), the owning organization
    must be `ACTIVE` (`ERR_ORG_SUSPENDED`), the modem must be `PROVISIONED`
    (`ERR_MODEM_NOT_PROVISIONED`), and a data plan for the machine must exist
    in `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`)."

    Design: Corner/validations/activate_without_provisioning_reports_modem_first
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    response = api.activate_machine(machine["id"], headers=ctx["dealer_headers"])
    error = validate_error(response, ApiErrorId.ERR_MODEM_NOT_PROVISIONED)
    assert error["error_id"] != "ERR_PLAN_NOT_ACTIVE"


def test_modem_retry_cycle_ends_provisioned_with_two_attempts(api):
    """PRD section 3.1: "The modem dimension runs `UNPROVISIONED` →
    `PROVISIONING` → `PROVISIONED`, with a retry loop `PROVISION_FAILED` →
    `PROVISIONING`." and "`PROVISION_SUCCEEDED` moves the modem to
    `PROVISIONED` and recomputes posture (to `NO_PLAN` if no active plan
    exists, or to `CONNECTED` if an active plan with `NORMAL` usage exists)".

    Design: Difficulty/non_linear_state_machine/machine_modem_retry_cycle_with_parallel_lifecycle
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]

    begin_provisioning(ctx, api, machine_id)
    complete_provisioning(api, machine_id, outcome="PROVISION_FAILED")
    begin_provisioning(ctx, api, machine_id)
    complete_provisioning(api, machine_id, outcome="PROVISION_SUCCEEDED")

    machine = read_machine(ctx, api, machine_id)
    assert machine["modem_status"] == "PROVISIONED"
    assert machine["provisioning_attempts"] == 2
    assert machine["connectivity_posture"] == "NO_PLAN"


def test_modem_retry_cycle_leaves_lifecycle_registered(api):
    """PRD section 3.1: "A machine therefore carries two parallel state
    dimensions plus the derived gate." — the modem dimension's retry loop never
    touches the lifecycle dimension: "The lifecycle dimension runs `REGISTERED`
    → `ACTIVATED` → `IN_SERVICE`." and only the dealer handshake and the first
    accepted telemetry batch move it.

    Design: Difficulty/non_linear_state_machine/machine_modem_retry_cycle_with_parallel_lifecycle
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]

    begin_provisioning(ctx, api, machine_id)
    complete_provisioning(api, machine_id, outcome="PROVISION_FAILED")
    begin_provisioning(ctx, api, machine_id)
    complete_provisioning(api, machine_id, outcome="PROVISION_SUCCEEDED")

    machine = read_machine(ctx, api, machine_id)
    assert machine["lifecycle_status"] == "REGISTERED"
    assert machine["connectivity_posture"] == "NO_PLAN"


def test_machine_activate_with_pending_plan_rejected(api):
    """PRD section 3.1: "the modem must be `PROVISIONED`
    (`ERR_MODEM_NOT_PROVISIONED`), and a data plan for the machine must exist
    in `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`)." With the modem provisioned but the
    plan still `PENDING`, the activation fails on the plan gate.

    Design: Difficulty/cross_entity_state_dependency/machine_activate_gated_by_plan_state
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]
    provision_modem_success(ctx, api, machine_id)
    create_plan(ctx, api, machine_id)

    response = api.activate_machine(machine_id, headers=ctx["dealer_headers"])
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_ACTIVE)


def test_machine_activate_with_pending_plan_leaves_lifecycle_registered(api):
    """PRD section 3.1: "On success the machine moves from `REGISTERED` to
    `ACTIVATED`" — a rejected handshake is not a success, so the lifecycle
    dimension of a machine whose activation failed the plan gate stays
    `REGISTERED`.

    Design: Difficulty/cross_entity_state_dependency/machine_activate_gated_by_plan_state
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]
    provision_modem_success(ctx, api, machine_id)
    create_plan(ctx, api, machine_id)

    response = api.activate_machine(machine_id, headers=ctx["dealer_headers"])
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
    machine = read_machine(ctx, api, machine_id)
    assert machine["lifecycle_status"] == "REGISTERED"
