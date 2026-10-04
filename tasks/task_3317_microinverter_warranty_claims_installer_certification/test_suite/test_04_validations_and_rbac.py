"""Validation gates and role segregation.

Difficulty queue A: priority_pair_validation_conflict.
Corner queue B: validations, rbac.
"""
from test_helpers import (
    ApiErrorId,
    NONEXISTENT_ID,
    TEST_USERS,
    create_installer,
    get_success_data,
    make_installer_headers,
    observe,
    open_design_project,
    set_clock,
    setup_certified_installer,
    setup_suspended_installer_with_claim_history,
    setup_system_with_units,
    suspend_installer,
    validate_error,
    validate_paginated,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]
MONITORING = TEST_USERS["monitoring_service_headers"]
INSTALLER = TEST_USERS["installer_headers"]


# ─── Queue A: business safety outranks the fiscal guard on a claim filing ───

def _suspended_installer_with_two_units(code: str):
    ctx = setup_system_with_units(
        installer_code=code, unit_serials=[f"{code}-U1", f"{code}-U2"],
        unit_models=["IQ8", "IQ8"], lot_code=f"LOT-{code}", embed_model_code="IQ8",
        replacement_model_code="IQ8", defect_threshold_pct=1e6,
        commissioned_at="2026-01-20T00:00:00Z", site_address=f"9 {code} Way",
    )
    installer = ctx["installer"]
    unit_one = observe(ctx["units"][0]["id"], 0.0, "2026-08-01T00:00:00Z")
    claim = get_success_data(api_client.create_claim(
        {
            "unit_id": unit_one["id"], "installer_id": installer["id"], "claim_kind": "DEFECT",
            "remote_diagnostic_ref": "DIAG-PP1", "expected_unit_version": unit_one["version"],
        },
        make_installer_headers(installer["id"]),
    ), 201)
    suspended = suspend_installer(installer["id"])
    assert suspended["certification_status"] == "SUSPENDED"
    ctx["unit_two"] = get_success_data(api_client.get_unit(ctx["units"][1]["id"], ADMIN))
    ctx["claim"] = claim
    return ctx


def test_claim_filed_by_a_suspended_installer_is_refused_for_certification(api):
    """PRD §3.6: "First, the acting installer must hold `ACTIVE` certification, or the
    request stops with `ERR_INSTALLER_NOT_CERTIFIED`." PRD §3.1: "Suspension moves the
    installer to `SUSPENDED`, forces `design_tool_enabled` and `commissioning_enabled`
    to false immediately".

    Design: Difficulty/priority_pair_validation_conflict/resubmit_conflict_business_safety_beats_fiscal
    """
    ctx = setup_suspended_installer_with_claim_history("PP1")
    unit_three = ctx["unit_three"]
    from test_helpers import create_claim_payload

    resp = api_client.create_claim(
        create_claim_payload(unit_id=unit_three["id"], installer_id=ctx["installer"]["id"],
                             remote_diagnostic_ref="DIAG-PP1-B",
                             expected_unit_version=unit_three["version"] - 1),
        make_installer_headers(ctx["installer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSTALLER_NOT_CERTIFIED, 403)
    claims = get_success_data(api_client.list_claims(ADMIN, {"unit_id": unit_three["id"]}))
    assert claims == [], "no claim row may be created by a refused filing"


def test_claim_filed_by_a_suspended_installer_is_refused_even_with_a_current_version(api):
    """PRD §3.6: "First, the acting installer must hold `ACTIVE` certification, or the
    request stops with `ERR_INSTALLER_NOT_CERTIFIED`." PRD §2.1: "An `Installer` whose
    `certification_status` is anything other than `ACTIVE` is barred from opening a
    design project, commissioning a system, filing a claim, submitting an existing
    claim, or commissioning a replacement in the field".

    Design: Difficulty/priority_pair_validation_conflict/resubmit_conflict_business_safety_beats_fiscal
    """
    ctx = setup_suspended_installer_with_claim_history("PP1B")
    unit_three = ctx["unit_three"]
    from test_helpers import create_claim_payload

    resp = api_client.create_claim(
        create_claim_payload(unit_id=unit_three["id"], installer_id=ctx["installer"]["id"],
                             remote_diagnostic_ref="DIAG-PP1-C",
                             expected_unit_version=unit_three["version"]),
        make_installer_headers(ctx["installer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSTALLER_NOT_CERTIFIED, 403)
    installer = get_success_data(api_client.get_installer(ctx["installer"]["id"], ADMIN))
    assert installer["certification_status"] == "SUSPENDED"
    assert installer["commissioning_enabled"] is False


def test_a_claim_filed_by_a_suspended_installer_leaves_the_suspended_state_intact(api):
    """PRD §3.6: "First, the acting installer must hold `ACTIVE` certification, or the
    request stops with `ERR_INSTALLER_NOT_CERTIFIED`." PRD §3.6: "The version guard from
    §2.8 is evaluated alongside these as `ERR_STALE_UNIT_VERSION`".

    Design: Difficulty/priority_pair_validation_conflict/resubmit_conflict_business_safety_beats_fiscal
    """
    ctx = setup_suspended_installer_with_claim_history("PP1C")
    unit_three = ctx["unit_three"]
    from test_helpers import create_claim_payload

    resp = api_client.create_claim(
        create_claim_payload(unit_id=unit_three["id"], installer_id=ctx["installer"]["id"],
                             remote_diagnostic_ref="DIAG-PP1-D",
                             expected_unit_version=unit_three["version"] - 1),
        make_installer_headers(ctx["installer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSTALLER_NOT_CERTIFIED, 403)
    yardstick = get_success_data(api_client.list_units(ADMIN, {"system_id": ctx["system"]["id"]}))
    assert len(yardstick) == 3
    after = get_success_data(api_client.get_installer(ctx["installer"]["id"], ADMIN))
    assert after["certification_status"] == "SUSPENDED", (
        "a refused filing must not disturb the installer's standing"
    )


# ─── Queue A: the referential design gate outranks the temporal window gate ───

def _installer_with_second_draft_design(code: str):
    ctx = setup_system_with_units(
        installer_code=code, unit_serials=[f"{code}-U1"], unit_models=["IQ8"],
        lot_code=f"LOT-{code}", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-15T00:00:00Z",
        site_address=f"10 {code} Way",
    )
    draft = open_design_project(ctx["installer"]["id"], site_address=f"10 {code} Way")
    assert draft["status"] == "DRAFT"
    ctx["draft_design"] = draft
    return ctx


def _second_registration_payload(ctx, serial: str, commissioned_at: str) -> dict:
    return {
        "installer_id": ctx["installer"]["id"],
        "design_project_id": ctx["draft_design"]["id"],
        "site_address": ctx["system"]["site_address"],
        "site_postal_code": ctx["system"]["site_postal_code"],
        "homeowner_name": "M. Mike",
        "homeowner_email": "m@mike.example",
        "commissioned_at": commissioned_at,
        "units": [{"serial_number": serial, "model_code": "IQ8",
                   "installed_at": commissioned_at, "production_lot_code": ctx["lot"]["lot_code"]}],
    }


def test_registration_citing_a_draft_design_is_refused_for_the_design_gate(api):
    """PRD §3.3: "Next the design must be in `APPROVED` status, otherwise the request
    stops with `ERR_DESIGN_NOT_APPROVED`, and it must belong to the same contractor that
    is commissioning, otherwise `ERR_DESIGN_NOT_OWNED`."

    Design: Difficulty/priority_pair_validation_conflict/coverage_gate_conflict_referential_beats_temporal
    """
    ctx = _installer_with_second_draft_design("PP2")
    payload = _second_registration_payload(ctx, "PP2-U1", "2026-06-01T00:00:00Z")
    resp = api_client.create_system_registration(
        payload, make_installer_headers(ctx["installer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_APPROVED, 409)
    systems = get_success_data(api_client.list_system_registrations(
        ADMIN, {"installer_id": ctx["installer"]["id"]}))
    assert len(systems) == 1, "the refused registration must not create a second system"


def test_registration_citing_a_draft_design_is_refused_before_the_serial_check(api):
    """PRD §3.3: "Next the design must be in `APPROVED` status, otherwise the request
    stops with `ERR_DESIGN_NOT_APPROVED`". PRD §3.3: "Every `serial_number` in the
    payload must then be globally unique across all `Unit` rows".

    Design: Difficulty/priority_pair_validation_conflict/coverage_gate_conflict_referential_beats_temporal
    """
    ctx = _installer_with_second_draft_design("PP2B")
    payload = _second_registration_payload(ctx, ctx["units"][0]["serial_number"],
                                           "2026-06-01T00:00:00Z")
    resp = api_client.create_system_registration(
        payload, make_installer_headers(ctx["installer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_APPROVED, 409)
    units = get_success_data(api_client.list_lot_units(ctx["lot"]["id"], ADMIN))
    assert len(units) == 1


# ─── Queue B: validations ─────────────────────────────────────────────

def test_installer_at_certified_level_cannot_open_a_design_project(api):
    """PRD §3.2: "a contractor holding `ACTIVE` certification but sitting at level
    `CERTIFIED` is then turned away with `ERR_DESIGN_TOOL_NOT_ENABLED`." PRD §2.6:
    "`design_tool_enabled` is true exactly when `certification_status` is `ACTIVE` and
    `certification_level` is either `GOLD` or `PLATINUM`."

    Design: Corner/validations/certified_installer_cannot_open_design_project
    """
    set_clock()
    installer = setup_certified_installer("INST-V3")
    reporter = get_success_data(api_client.get_installer(installer["id"], ADMIN))
    assert reporter["certification_status"] == "ACTIVE"
    assert reporter["certification_level"] == "CERTIFIED"
    assert reporter["design_tool_enabled"] is False
    assert reporter["commissioning_enabled"] is False
    resp = api_client.create_design_project(
        {"installer_id": installer["id"], "site_address": "34 India Two Way",
         "site_postal_code": "94034", "module_count": 20, "dc_capacity_watts": 10000},
        make_installer_headers(installer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_TOOL_NOT_ENABLED, 403)


def test_claim_against_a_unit_of_a_recalled_lot_is_refused(api):
    """PRD §3.6: "Third, the unit's lot must not currently be in `RECALL` — a unit from
    a recalled batch is handled by the campaign pipeline rather than one claim at a
    time, so the rejection is `ERR_LOT_RECALL_ACTIVE`."

    Design: Corner/validations/claim_on_recall_lot_is_rejected
    """
    serials = [f"V4-U{i}" for i in range(1, 11)]
    ctx = setup_system_with_units(
        installer_code="INST-V4", unit_serials=serials, unit_models=["IQ7"] * 10,
        lot_code="LOT-V4", embed_model_code="IQ7", replacement_model_code="IQ8",
        defect_threshold_pct=10.0, commissioned_at="2026-01-20T00:00:00Z",
        site_address="35 Juliet Two Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    for unit in ctx["units"]:
        observe(unit["id"], 0.0, "2026-08-01T00:00:00Z")
    from test_helpers import get_lot
    lot = get_lot(ctx["lot"]["id"])
    assert lot["lot_status"] == "RECALL"
    assert lot["corrective_action_required"] is True
    unit_one = get_success_data(api_client.get_unit(ctx["units"][0]["id"], ADMIN))
    resp = api_client.create_claim(
        {"unit_id": unit_one["id"], "installer_id": ctx["installer"]["id"],
         "claim_kind": "DEFECT", "remote_diagnostic_ref": "DIAG-V4",
         "expected_unit_version": unit_one["version"]},
        make_installer_headers(ctx["installer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LOT_RECALL_ACTIVE, 409)


def test_billing_correction_for_the_current_calendar_month_is_refused(api):
    """PRD §3.4: "The month being corrected must be strictly before the current
    calendar month, since the system refuses to restate a month that is still open — the
    rejection is `ERR_CORRECTION_PERIOD_CLOSED`."

    Design: Corner/validations/billing_correction_for_current_month_is_rejected
    """
    ctx = setup_system_with_units(
        installer_code="INST-V5", unit_serials=["V5-U1"], unit_models=["IQ8"],
        lot_code="LOT-V5", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-15T00:00:00Z",
        site_address="36 Kilo Two Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_billing_correction(
        {"system_id": ctx["system"]["id"], "period_month": "2026-09",
         "corrected_metering_fee_cents": 188},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CORRECTION_PERIOD_CLOSED, 409)


# ─── Queue B: rbac ────────────────────────────────────────────────────

def test_installer_cannot_approve_a_claim(api):
    """PRD §2.1: "Presenting a valid role for an operation that the role is not
    permitted to perform — including an attempt by one role to exercise another role's
    exclusive operation — is rejected with `ERR_UNAUTHORIZED`." PRD §2.1: "Both identity
    errors are evaluated before anything else in the request is inspected."

    Design: Corner/rbac/installer_cannot_approve_claim_returns_unauthorized
    """
    set_clock()
    resp = api_client.approve_claim(NONEXISTENT_ID, INSTALLER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_monitoring_service_cannot_change_an_installer_level(api):
    """PRD §2.1: "Presenting a valid role for an operation that the role is not
    permitted to perform — including an attempt by one role to exercise another role's
    exclusive operation — is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/monitoring_service_cannot_set_installer_level
    """
    installer = create_installer("INST-RB2", "Papa Two Solar")
    resp = api_client.set_installer_level(
        {"installer_id": installer["id"], "level": "GOLD"}, MONITORING)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
    after = get_success_data(api_client.get_installer(installer["id"], ADMIN))
    assert after["certification_level"] == "CERTIFIED"


def test_unknown_role_header_is_unauthenticated(api):
    """PRD §2.1: "a request missing either header, or carrying a value that names no
    known role, is rejected with `ERR_UNAUTHENTICATED`." PRD §2.1: "Both identity errors
    are evaluated before anything else in the request is inspected."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    from prd_bench_local_runner.testing import build_user_headers

    set_clock()
    resp = api_client.get_installer(NONEXISTENT_ID, build_user_headers("nobody", "NotARole"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_platform_admin_can_read_the_claim_collection(api):
    """PRD §2.1: "Four roles exist, spelled exactly as follows: `PlatformAdmin`,
    `Installer`, `MonitoringService`, and `Homeowner`." PRD §2.3: "Paginated responses
    carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object."

    Design: Corner/rbac/platform_admin_shared_read_succeeds
    """
    set_clock()
    resp = api_client.list_claims(ADMIN, {"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["total_count"] == 0
    assert meta["has_more"] is False