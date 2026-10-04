"""Difficulty queue A: priority-pair validation conflicts."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    admin_of,
    admin_as,
    op_headers,
    ApiErrorId,
    activate_definition,
    add_step,
    create_active_unit,
    create_definition,
    create_feature_train,
    create_group_with_member,
    create_prod_sandbox_pair,
    create_tenant,
    create_worker,
    enroll,
    get_adoption,
    get_tenant,
    initiate,
    set_clock,
    setup_active_definition,
)


def _deferred_adoption_on_closed_train():
    """Tenant, feature train, and an adoption explicitly deferred while the
    window is open; the caller may then advance the clock past the window."""
    tenant = create_tenant("T-PP1")
    admin = admin_of(tenant)
    train = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")
    adoption = enroll(tenant["id"], train["id"], "F1", admin)
    get_success_data(api_client.defer_feature(tenant["id"], adoption["id"], admin))
    return tenant, admin, train, adoption


def test_record_testing_deferred_on_closed_train_reports_invalid_state(api):
    """PRD §2.7: "When several validation rules apply to one request, the
    platform evaluates them in a fixed priority order, and the first failure
    determines the error returned."
    PRD §2.7: "6. Target state — the entity being acted on is in a state that
    permits the requested transition, else `ERR_INVALID_STATE`."
    PRD §2.7: "12. Opt-in window timing — enrollment, record-testing, adopt,
    and defer are allowed only while the train is `OPT_IN_OPEN` (inclusive of
    `opt_in_window_end`), else `ERR_OPT_IN_WINDOW_CLOSED`."

    A record-testing call on a DEFERRED adoption whose train has left
    OPT_IN_OPEN violates both rule 6 and rule 12; rule 6 is earlier, so the
    response is ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_closed_train_record_testing
    """
    tenant, admin, train, adoption = _deferred_adoption_on_closed_train()
    tid = tenant["id"]
    set_clock("2026-09-11T00:00:00Z")  # window closed

    resp = api_client.record_testing(
        tid, adoption["id"], {"sandbox_test_evidence_id": "EV"}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_adoption(tid, adoption["id"], admin)["status"] == "DEFERRED"


def test_record_testing_deferred_on_open_train_reports_invalid_state(api):
    """PRD §3.7: "Recording sandbox testing moves a row from `ENROLLED` to
    `TESTING_PASSED`". A DEFERRED row has no transition back, so even while
    the train is OPT_IN_OPEN the call fails the target-state check.
    PRD §2.7: "6. Target state — the entity being acted on is in a state that
    permits the requested transition, else `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_closed_train_record_testing
    """
    tenant, admin, train, adoption = _deferred_adoption_on_closed_train()
    tid = tenant["id"]
    # Clock stays inside the opt-in window: only the state rule can fail.
    resp = api_client.record_testing(
        tid, adoption["id"], {"sandbox_test_evidence_id": "EV"}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_adoption(tid, adoption["id"], admin)["status"] == "DEFERRED"


def test_retire_production_with_open_transactions_reports_production_forbidden(api):
    """PRD §3.2: "Only `SANDBOX` and `IMPLEMENTATION` tenants may be retired;
    attempting to retire a `PRODUCTION` tenant is rejected with
    `ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN` (HTTP 422)."
    PRD §2.7: "8. Production-tenant protections — `PRODUCTION` tenants cannot
    be retired, and refresh jobs may only target `SANDBOX` tenants sourced from
    `PRODUCTION` tenants, else `ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN`."

    The production-tenant protection is categorical: even with an IN_PROGRESS
    transaction present, retiring a PRODUCTION tenant reports
    ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_group_disable
    """
    ctx = setup_active_definition("T-PP2", steps=[{"order": 1}])
    tid = ctx["tenant"]["id"]
    inst = initiate(ctx)
    assert inst["status"] == "IN_PROGRESS"

    resp = api_client.retire_tenant(tid, op_headers())
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_TENANT_RETIREMENT_FORBIDDEN)

    assert get_tenant(tid)["status"] == "ACTIVE"
    inst = get_success_data(api_client.get_transaction(tid, inst["id"], ctx["admin"]))
    assert inst["status"] == "IN_PROGRESS"


def test_retire_sandbox_with_open_transactions_reports_open_transactions(api):
    """PRD §3.2: "Retirement is also blocked — from either `ACTIVE` or
    `SUSPENDED` — while any transaction instance on the tenant remains
    `IN_PROGRESS`, surfacing `ERR_OPEN_TRANSACTIONS_EXIST` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_group_disable
    """
    _src, tgt = create_prod_sandbox_pair("T-PP3S", "T-PP3T")
    tid = tgt["id"]
    admin = admin_of(tgt)
    unit = create_active_unit(tid, "U1", admin)
    initiator = create_worker(tid, unit["id"], "INIT", admin)
    approver = create_worker(tid, unit["id"], "MGR", admin)
    group = create_group_with_member(tid, "G1", approver["id"], admin)
    definition = create_definition(tid, admin, transaction_type="HIRE", name="Flow")
    add_step(tid, definition["id"], 1, admin, group_id=group["id"])
    activate_definition(tid, definition["id"], admin)
    inst = get_success_data(api_client.create_transaction(
        tid,
        {"transaction_type": "HIRE", "target_org_unit_id": unit["id"], "amount": 0},
        admin_as(tgt, initiator["id"]),
    ), 201)
    assert inst["status"] == "IN_PROGRESS"

    resp = api_client.retire_tenant(tid, op_headers())
    validate_error(resp, ApiErrorId.ERR_OPEN_TRANSACTIONS_EXIST)
    assert get_tenant(tid)["status"] == "ACTIVE"
