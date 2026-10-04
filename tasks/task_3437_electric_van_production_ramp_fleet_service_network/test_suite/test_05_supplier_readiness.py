"""Supplier readiness scoring: tier boundaries, the quarantine / supply-risk
cascade and its recovery mirror, and the registrar/auditor separation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    audit_supplier,
    audit_supplier_to_tier_c,
    create_confirmed_order,
    create_supplier,
    make_quality_inspector_headers,
    readiness_audit_payload,
    read_order,
    register_module,
    set_logical_clock,
    setup_customer_with_depot,
    transition_module,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLANNER = TEST_USERS["production_planner_headers"]


def _module_by_id(api, supplier_id, module_id):
    rows, _meta = validate_paginated(api.list_supplier_battery_modules(supplier_id, _PLANNER))
    for row in rows:
        if row["id"] == module_id:
            return row
    raise AssertionError(f"module {module_id} not listed for supplier {supplier_id}")


def test_supplier_readiness_tier_boundary_values(api):
    """PRD section 3.3: "Scoring is conjunctive and checked tier `A` first,
    then `B`, else `C`. Tier `A` requires on-time delivery of at least 95.0
    percent, first-pass yield of at least 98.0 percent, and exactly zero open
    corrective actions. Tier `B` requires on-time of at least 85.0 percent,
    yield of at least 92.0 percent, and no more than 2 open corrective
    actions. Anything else is tier `C`. All boundaries are inclusive, so
    exactly 95.0 on-time with a 98.0 yield and zero corrective actions earns
    `A`."; audits are recorded: "its three measurements are recorded on the
    supplier as `last_on_time_pct`, `last_first_pass_yield_pct`, and
    `open_corrective_actions`."

    Design: Corner/calculations/supplier_readiness_tier_boundary_values
    """
    set_logical_clock()
    sup_a = create_supplier()
    sup_b = create_supplier(name="VoltBeta", contact_email="s@voltbeta.test")
    sup_c = create_supplier(name="VoltGamma", contact_email="s@voltgamma.test")
    tier_a = audit_supplier(sup_a["id"], 95.0, 98.0, 0)
    assert tier_a["readiness_tier"] == "A", "95.0 / 98.0 / 0 hits the inclusive A boundary"
    assert tier_a["last_on_time_pct"] == 95.0
    assert tier_a["last_first_pass_yield_pct"] == 98.0
    assert tier_a["open_corrective_actions"] == 0
    tier_b = audit_supplier(sup_b["id"], 94.9, 98.0, 0)
    assert tier_b["readiness_tier"] == "B", (
        "94.9 < 95.0 misses A but 94.9 >= 85.0, 98.0 >= 92.0, 0 <= 2 earns B"
    )
    tier_c = audit_supplier(sup_c["id"], 94.9, 91.9, 3)
    assert tier_c["readiness_tier"] == "C", "91.9 < 92.0 misses B as well"


def test_supplier_downgrade_quarantines_and_recovery_releases(api):
    """PRD section 3.3: "When an audit drops a supplier to `C`, two cascades
    fire in the same response. First, every battery module of that supplier
    currently in `REGISTERED`, `IN_QA`, `REWORK`, or `FAILED` is moved to
    `QUARANTINED`, freezing the questionable stock. Second, every vehicle
    order that nominated this supplier through `battery_supplier_id` and is
    currently `CONFIRMED` or `IN_PRODUCTION` has its `supply_risk_flag` set
    true and its `promised_delivery_date` pushed out by 14 days. When a later
    audit recovers the supplier from `C` to `A` or `B`, the mirror cascade
    runs: `QUARANTINED` modules re-enter inspection at `IN_QA` from scratch —
    their `failure_count` is NOT reset — and flagged orders clear
    `supply_risk_flag` to false, but their promised dates are NOT pulled
    back."

    Design: Corner/state_machines/supplier_downgrade_quarantines_and_recovery_releases
    """
    customer, depot = setup_customer_with_depot()
    supplier = create_supplier()
    module_passed = register_module(supplier["id"], module_serial="M-001")
    transition_module(module_passed["id"], "IN_QA")
    transition_module(module_passed["id"], "PASSED")
    module_in_qa = register_module(supplier["id"], module_serial="M-002")
    transition_module(module_in_qa["id"], "IN_QA")
    order = create_confirmed_order(customer, depot, supplier)
    assert order["promised_delivery_date"] == "2026-10-06", (
        "quantity 2 confirmed 2026-09-01 promises 35 days later"
    )
    assert order["supply_risk_flag"] is False

    downgraded = audit_supplier_to_tier_c(supplier["id"])
    assert downgraded["readiness_tier"] == "C"
    m1 = _module_by_id(api, supplier["id"], module_passed["id"])
    m2 = _module_by_id(api, supplier["id"], module_in_qa["id"])
    assert m1["quality_status"] == "PASSED", "the conditional cascade spares PASSED modules"
    assert m2["quality_status"] == "QUARANTINED"
    order_c = read_order(order["id"])
    assert order_c["supply_risk_flag"] is True
    assert order_c["promised_delivery_date"] == "2026-10-20", "2026-10-06 pushed +14 days"

    recovered = audit_supplier(supplier["id"], 90.0, 93.0, 1)
    assert recovered["readiness_tier"] == "B"
    m2_after = _module_by_id(api, supplier["id"], module_in_qa["id"])
    assert m2_after["quality_status"] == "IN_QA", "recovery re-enters quarantined stock at IN_QA"
    assert m2_after["failure_count"] == 0, "failure_count is NOT reset by the recovery cascade"
    order_b = read_order(order["id"])
    assert order_b["supply_risk_flag"] is False
    assert order_b["promised_delivery_date"] == "2026-10-20", (
        "recovery never pulls the promised date back"
    )


def test_downgrade_cascade_noop_without_matching_children(api):
    """PRD section 3.3: the cascade reaches "every battery module of that
    supplier currently in `REGISTERED`, `IN_QA`, `REWORK`, or `FAILED`" and
    "every vehicle order that nominated this supplier through
    `battery_supplier_id` and is currently `CONFIRMED` or `IN_PRODUCTION`" —
    with neither present the tier change stands alone and succeeds.

    Design: Corner/complexity_layers/downgrade_cascade_noop_without_matching_children
    """
    set_logical_clock()
    supplier = create_supplier()
    downgraded = audit_supplier_to_tier_c(supplier["id"])
    assert downgraded["readiness_tier"] == "C"
    rows, meta = validate_paginated(api.list_supplier_battery_modules(supplier["id"], _PLANNER))
    assert rows == [] and meta["total_count"] == 0


def test_supplier_registrar_cannot_audit_own_supplier(api):
    """PRD section 2.9: "A `QualityInspector` may not audit a supplier they
    registered: the audit caller's `X-User-ID` must differ from the supplier's
    `created_by_user_id`." — each surfacing `ERR_SEGREGATION_VIOLATION`
    (HTTP 403).

    Design: Corner/rbac/supplier_registrar_cannot_audit_own_supplier
    """
    set_logical_clock()
    supplier = create_supplier()
    assert supplier["created_by_user_id"] == "pp-1"
    resp = api.create_readiness_audit(
        supplier["id"],
        readiness_audit_payload(96.0, 99.0, 0),
        make_quality_inspector_headers("pp-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION)
    audited = audit_supplier(supplier["id"], 96.0, 99.0, 0)
    assert audited["readiness_tier"] == "A", "a distinct auditor computes the tier normally"
