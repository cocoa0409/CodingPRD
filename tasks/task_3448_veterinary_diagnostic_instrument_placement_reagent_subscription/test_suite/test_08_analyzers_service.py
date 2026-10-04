"""Analyzer dimensions, installation gates, and service-case mechanics (PRD §3.7, §3.8)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_agreement,
    assert_analyzer_fresh_dimensions,
    assert_version_incremented,
    cancel_service_case,
    create_analyzer_payload,
    create_clinic,
    dispatch_service_case,
    draft_purchase_agreement,
    enter_service,
    get_agreement,
    get_analyzer,
    install_analyzer,
    list_service_cases,
    make_clinic_manager_headers,
    open_service_case,
    patch_analyzer_payload,
    patch_lab_test_order_payload,
    patch_service_case_payload,
    place_patient_order,
    set_connectivity,
    setup_clinic_with_active_purchase,
    setup_clinic_with_rc_and_purchase_agreements,
    setup_in_service_analyzer,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_ENGINEER = TEST_USERS["field_service_engineer_headers"]


def test_analyzer_create_ignores_client_supplied_system_fields(api):
    """PRD §3.7: "A new analyzer starts `INSTALLED`, `NOT_CONFIGURED`, and
    `LAPSED` across its three independent dimensions, with `qc_valid_until`
    null, `total_downtime_hours` at 0, and both uptime ratios —
    `reported_uptime_pct` and `breach_uptime_pct` — at 1.0." PRD §3.7: "The
    unit's `model` is copied from the agreement, never supplied by the
    caller." PRD §3.7: "an optional `is_loaner_unit` flag, defaulting to
    false".

    Design: Corner/entities/analyzer_create_system_fields_input_ignored
    """
    scenario = setup_clinic_with_active_purchase()
    resp = api_client.create_analyzer(
        create_analyzer_payload(
            scenario["clinic"]["id"], scenario["agreement"]["id"],
            serial_number="SN-SYS-1",
            operational_status="IN_SERVICE",  # smuggled system fields
            proficiency_standing="CURRENT",
            version=99,
        ),
        _ENGINEER,
    )
    data = validate_success(resp, 201)
    assert_analyzer_fresh_dimensions(data)  # INSTALLED / NOT_CONFIGURED / LAPSED, version 1
    assert data["model"] == "VETHEMAT_500"  # copied from the agreement
    assert data["is_loaner_unit"] is False


def test_analyzer_install_requires_active_agreement(api):
    """PRD §3.7: "that agreement must be `ACTIVE`, `RENEGOTIATION`, or
    `BREACHED`, or installation fails with `ERR_AGREEMENT_INVALID_STATE`".

    Design: Corner/validations/analyzer_install_requires_active_agreement
    """
    clinic = create_clinic()
    draft = draft_purchase_agreement(clinic["id"])
    approve_agreement(draft["id"])  # APPROVED, never activated

    resp = api_client.create_analyzer(
        create_analyzer_payload(clinic["id"], draft["id"], serial_number="SN-EARLY-1"),
        _ENGINEER,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)

    rows, _meta = validate_paginated(api_client.list_analyzers(
        _ENGINEER, params={"agreement_id": draft["id"]}
    ))
    assert rows == []


def test_analyzer_dimensions_evolve_independently(api):
    """PRD §3.7: "Opening a `REPAIR` or `PREVENTIVE_CALIBRATION` case moves
    the serviced unit `IN_SERVICE` → `UNDER_SERVICE`". PRD §3.7: "From
    `NOT_CONFIGURED` the engineer brings it `ACTIVE`, and thereafter it
    oscillates `ACTIVE` ↔ `DEGRADED`." — connectivity keeps cycling while the
    open case holds the operational dimension at UNDER_SERVICE, and the
    proficiency dimension is untouched by both.

    Design: Difficulty/non_linear_state_machine/analyzer_parallel_dimensions
    """
    scenario = setup_in_service_analyzer()
    analyzer = scenario["analyzer"]
    open_service_case(analyzer["id"], case_type="REPAIR")

    held = get_analyzer(analyzer["id"])
    assert held["operational_status"] == "UNDER_SERVICE"

    active = set_connectivity(analyzer["id"], "ACTIVE")
    assert active["connectivity_status"] == "ACTIVE"
    assert active["operational_status"] == "UNDER_SERVICE"

    degraded = set_connectivity(analyzer["id"], "DEGRADED")
    assert degraded["connectivity_status"] == "DEGRADED"
    assert degraded["operational_status"] == "UNDER_SERVICE"

    final = get_analyzer(analyzer["id"])
    assert final["operational_status"] == "UNDER_SERVICE"
    assert final["connectivity_status"] == "DEGRADED"
    assert final["proficiency_standing"] == "LAPSED"


def test_analyzer_version_marks_each_dimension_hop(api):
    """PRD §2.5: "`version` is an integer that increments by 1 on every
    mutation of the resource, including system-driven cascades and
    computed-field recomputes." Install, enter-service, the case-open
    cascade, and two connectivity drives are five distinct observable states
    on one row.

    Design: Difficulty/non_linear_state_machine/analyzer_parallel_dimensions
    """
    scenario = setup_clinic_with_active_purchase()
    installed = install_analyzer(
        scenario["clinic"]["id"], scenario["agreement"]["id"]
    )
    in_service = enter_service(installed["id"])
    assert_version_incremented(installed["version"], in_service["version"])

    open_service_case(in_service["id"], case_type="REPAIR")
    held = get_analyzer(in_service["id"])
    assert held["version"] == in_service["version"] + 1  # cascade counts

    active = set_connectivity(in_service["id"], "ACTIVE")
    assert_version_incremented(held["version"], active["version"])
    degraded = set_connectivity(in_service["id"], "DEGRADED")
    assert_version_incremented(active["version"], degraded["version"])

    final = get_analyzer(in_service["id"])
    assert final["version"] == installed["version"] + 4
    assert final["proficiency_standing"] == "LAPSED"


def test_service_case_double_dispatch_rejected(api):
    """PRD §3.7: "A case is dispatched `OPEN` → `DISPATCHED`, then resolved
    `DISPATCHED` → `RESOLVED`; each step rejects a wrong starting state with
    `ERR_SERVICE_CASE_INVALID_STATE`."

    Design: Corner/state_machines/service_case_double_dispatch_rejected
    """
    scenario = setup_in_service_analyzer()
    case = open_service_case(scenario["analyzer"]["id"], case_type="REPAIR")
    dispatched = dispatch_service_case(case["id"])
    assert dispatched["status"] == "DISPATCHED"
    assert_version_incremented(case["version"], dispatched["version"])

    resp = api_client.update_service_case(
        case["id"], patch_service_case_payload("DISPATCH"), _ENGINEER
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_CASE_INVALID_STATE)

    cases = list_service_cases(scenario["analyzer"]["id"])
    mine = [c for c in cases if c["id"] == case["id"]][0]
    assert mine["status"] == "DISPATCHED"
    assert mine["version"] == dispatched["version"]


def test_service_case_cancel_returns_loaner_and_leaves_no_downtime(api):
    """PRD §3.7: "assigning a loaner moves the loaner `IN_SERVICE` →
    `ON_LOAN`, and the borrowing case's resolution or cancellation returns
    it." PRD §3.7: "Cancellation from `OPEN` or `DISPATCHED` performs the
    same unit-return compensation but accrues no downtime and recomputes
    nothing."

    Design: Corner/cross_cutting_layers/service_case_cancel_returns_loaner_and_leaves_no_downtime
    """
    scenario = setup_in_service_analyzer()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    unit = scenario["analyzer"]

    loaner = install_analyzer(
        clinic["id"], agreement["id"], serial_number="SN-LOAN-1", is_loaner_unit=True
    )
    enter_service(loaner["id"])
    case = open_service_case(
        unit["id"], case_type="REPAIR", loaner_analyzer_id=loaner["id"]
    )
    assert get_analyzer(unit["id"])["operational_status"] == "UNDER_SERVICE"
    assert get_analyzer(loaner["id"])["operational_status"] == "ON_LOAN"

    cancelled = cancel_service_case(case["id"])
    assert cancelled["status"] == "CANCELLED"

    serviced = get_analyzer(unit["id"])
    returned = get_analyzer(loaner["id"])
    assert serviced["operational_status"] == "IN_SERVICE"
    assert returned["operational_status"] == "IN_SERVICE"
    assert serviced["total_downtime_hours"] == 0
    assert returned["total_downtime_hours"] == 0
    assert get_agreement(agreement["id"])["service_credit_cents"] == 0


def test_analyzers_filter_by_agreement_reverse_lookup(api):
    """PRD §3.7: "Analyzers list with `clinic_id`, `agreement_id`, and
    `operational_status` filters." PRD §2.10: "foreign keys travel in request
    bodies and filter parameters rather than in nested paths."

    Design: Corner/endpoints/analyzers_filter_by_agreement_reverse_lookup
    """
    scenario = setup_clinic_with_rc_and_purchase_agreements()
    clinic = scenario["clinic"]
    install_analyzer(clinic["id"], scenario["rc_agreement"]["id"], serial_number="SN-FK-1")
    install_analyzer(clinic["id"], scenario["purchase_agreement"]["id"], serial_number="SN-FK-2")

    by_agreement, _meta = validate_paginated(api_client.list_analyzers(
        _ADMIN, params={"agreement_id": scenario["purchase_agreement"]["id"]}
    ))
    assert len(by_agreement) == 1
    assert by_agreement[0]["serial_number"] == "SN-FK-2"
    assert by_agreement[0]["model"] == "VETHEMAT_500"

    by_clinic, _meta = validate_paginated(api_client.list_analyzers(
        _ADMIN, params={"clinic_id": clinic["id"]}
    ))
    assert len(by_clinic) == 2

    by_status, _meta = validate_paginated(api_client.list_analyzers(
        _ADMIN, params={"operational_status": "INSTALLED"}
    ))
    assert len(by_status) == 2


def test_state_errors_sweep_analyzer_and_service_case(api):
    """PRD §3.8: "the analyzer must be `IN_SERVICE`
    (`ERR_ANALYZER_INVALID_STATE`)" — the operational gate fires before
    connectivity or proficiency, so a unit held UNDER_SERVICE fails result
    recording. PRD §3.7: "Decommissioning is manual from `INSTALLED` or
    `IN_SERVICE`"; per PRD §2.9 ("a request that fails several checks
    reports the failure from the earliest tier"), the tier-6 state-legality
    error (`ERR_ANALYZER_INVALID_STATE`) pre-empts the tier-9
    decommission-blocked-by-open-cases constraint when the unit is
    `UNDER_SERVICE` — an `OPEN`/`DISPATCHED` case always implies the unit
    left `IN_SERVICE`, so the tier-9 code can never surface first here.

    Design: Corner/errors/state_errors_sweep_analyzer_and_service_case
    """
    scenario = setup_in_service_analyzer()
    clinic = scenario["clinic"]
    analyzer = scenario["analyzer"]
    order = place_patient_order(clinic["id"], analyzer["id"])
    case = open_service_case(analyzer["id"], case_type="REPAIR")  # → UNDER_SERVICE

    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("RECORD_RESULT", result_value=7.7),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ANALYZER_INVALID_STATE)

    resp2 = api_client.update_analyzer(
        analyzer["id"],
        patch_analyzer_payload(operational_status="DECOMMISSIONED"),
        _ENGINEER,
    )
    validate_error(resp2, ApiErrorId.ERR_ANALYZER_INVALID_STATE)

    assert get_analyzer(analyzer["id"])["operational_status"] == "UNDER_SERVICE"
    cases = list_service_cases(analyzer["id"])
    assert [c["id"] for c in cases] == [case["id"]]
    assert cases[0]["status"] == "OPEN"
