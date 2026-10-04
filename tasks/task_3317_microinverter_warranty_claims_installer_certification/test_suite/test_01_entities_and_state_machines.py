"""Entity shape, design-tool gating, and cyclic state machines.

Difficulty queue A: combinatorial_formula, non_linear_state_machine.
Corner queue B: entities, state_machines.
"""
from test_helpers import (
    ApiErrorId,
    NONEXISTENT_ID,
    activate_campaign,
    activate_installer,
    create_campaign,
    create_installer,
    create_lot,
    diagnose,
    dispatch_order,
    force_lot_recall,
    get_installer,
    get_lot,
    get_success_data,
    get_unit,
    install_order,
    list_orders,
    make_installer_headers,
    observe,
    open_design_project,
    set_clock,
    set_installer_level,
    setup_approved_design,
    setup_certified_installer,
    setup_failed_unit_claim,
    setup_submitted_design,
    setup_system_with_units,
    suspend_installer,
    validate_error,
)

from test_helpers import api_client


# ─── Queue A: the DC/AC approval gate (combinatorial_formula) ─────────

def test_dc_ac_ratio_above_one_point_five_is_refused_at_approval(api, platform_admin_headers):
    """PRD §3.2: "the system derives its sizing figure" and "the quotient is carried
    to four decimal places with round-half-up". PRD §3.2: "Approval is a
    `PlatformAdmin` action and it carries one arithmetic gate: a design whose
    `dc_ac_ratio` is greater than one and a half is refused with
    `ERR_DC_AC_RATIO_EXCEEDED`, because a DC array oversized beyond that ratio will
    clip in a way the manufacturer will not warrant."

    Design: Difficulty/combinatorial_formula/dc_ac_ratio_hard_gate_at_one_point_five
    """
    set_clock()
    installer = setup_certified_installer("INST-DC-A")
    installer = set_installer_level(installer["id"], "GOLD")
    project = setup_submitted_design(installer["id"], module_count=40,
                                     dc_capacity_watts=24600)
    assert project["dc_ac_ratio"] == 1.7571
    resp = api_client.approve_design_project(project["id"], platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_DC_AC_RATIO_EXCEEDED, 422)
    after = get_success_data(api_client.get_design_project(project["id"], platform_admin_headers))
    assert after["status"] == "SUBMITTED", (
        f"a refused approval must leave the project SUBMITTED, got {after['status']}"
    )


def test_dc_ac_ratio_at_one_point_five_is_approved(api, platform_admin_headers):
    """PRD §3.2: "Ratios at or below one and a half pass."

    Design: Difficulty/combinatorial_formula/dc_ac_ratio_hard_gate_at_one_point_five
    """
    set_clock()
    installer = setup_certified_installer("INST-DC-B")
    installer = set_installer_level(installer["id"], "GOLD")
    project = setup_submitted_design(installer["id"], module_count=40,
                                     dc_capacity_watts=21000)
    assert project["dc_ac_ratio"] == 1.5
    approved = get_success_data(api_client.approve_design_project(project["id"], platform_admin_headers))
    assert approved["status"] == "APPROVED"


# ─── Queue A: the cyclic Unit monitoring machine (non_linear_state_machine) ───

def _cycle_setup(code, model_code="IQ7"):
    ctx = setup_system_with_units(installer_code=code, unit_serials=[f"{code}-U1"],
                                  unit_models=[model_code], lot_code=f"LOT-{code}",
                                  embed_model_code=model_code, site_address=f"{code} Cycle Way")
    return ctx["units"][0]


def test_unit_monitoring_cycle_returns_to_online_after_repair(api):
    """PRD §3.4: "A commissioned unit that is `ONLINE` and reports a ratio below 0.95
    slips to `UNDERPERFORMING`; the system stores the observed figure in
    `last_performance_ratio`, adds one to `underperformance_streak_hours`". PRD §3.4:
    "When a unit is `FAILED` and an observation arrives with `telemetry_absent` set,
    the unit moves to `OFFLINE`, but its `failed_at` instant is preserved — a device
    that goes silent after failing does not erase the evidence that it failed".

    Design: Difficulty/non_linear_state_machine/unit_monitoring_cycle_failed_back_to_online
    """
    unit = _cycle_setup("CYCA")
    unit = observe(unit["id"], 0.80, "2026-08-01T00:00:00Z")
    assert unit["monitored_status"] == "UNDERPERFORMING"
    assert unit["underperformance_streak_hours"] == 1
    unit = observe(unit["id"], 0.80, "2026-08-02T00:00:00Z")
    assert unit["underperformance_streak_hours"] == 2
    unit = diagnose(unit["id"], "2026-08-03T00:00:00Z", performance_ratio=0.0)
    assert unit["monitored_status"] == "FAILED"
    failed_at = unit["failed_at"]
    unit = observe(unit["id"], 0.0, "2026-08-04T00:00:00Z", telemetry_absent=True)
    assert unit["monitored_status"] == "OFFLINE"
    assert unit["failed_at"] == failed_at, "going OFFLINE must not clear the failure instant"
    unit = observe(unit["id"], 0.97, "2026-08-05T00:00:00Z")
    assert unit["monitored_status"] == "ONLINE"
    assert unit["underperformance_streak_hours"] == 0


def test_unit_monitoring_cycle_online_to_failed_is_a_single_observation(api):
    """PRD §3.4: "An `ONLINE` unit fails outright when an observation carries a ratio
    of exactly zero; it moves straight to `FAILED` and stamps `failed_at` with the
    current logical clock." PRD §3.4: "An `OFFLINE` unit that reports a ratio back at
    or above 0.95 likewise returns to `ONLINE` with a zeroed streak."

    Design: Difficulty/non_linear_state_machine/unit_monitoring_cycle_failed_back_to_online
    """
    set_clock("2026-09-01T00:00:00Z")
    unit = _cycle_setup("CYCB")
    unit = observe(unit["id"], 0.0, "2026-08-01T00:00:00Z")
    assert unit["monitored_status"] == "FAILED"
    assert unit["failed_at"] == "2026-09-01T00:00:00.000Z", (
        "the failure instant is stamped from the logical clock, not the observation instant"
    )
    unit = observe(unit["id"], 0.0, "2026-08-02T00:00:00Z", telemetry_absent=True)
    assert unit["monitored_status"] == "OFFLINE"
    unit = observe(unit["id"], 0.96, "2026-08-03T00:00:00Z")
    assert unit["monitored_status"] == "ONLINE"
    assert unit["underperformance_streak_hours"] == 0


# ─── Queue A: the cyclic WarrantyClaim machine (non_linear_state_machine) ───

def test_claim_denied_reopens_clears_reason_and_diagnoses_again(api, platform_admin_headers,
                                                              monitoring_service_headers,
                                                              installer_headers):
    """PRD §3.6: "A `DENIED` claim may be reopened with no such restriction, and its
    `denial_reason` is cleared as part of the reopen because the earlier refusal is no
    longer the operative record." PRD §3.6: "A reopened claim goes back through
    diagnostics: the monitoring platform diagnosing it moves it from `REOPENED` to
    `DIAGNOSED` and sets `diagnostic_source` to `REMOTE_VERIFIED` once more."

    Design: Difficulty/non_linear_state_machine/claim_cycle_reopen_and_rediagnose
    """
    ctx = setup_failed_unit_claim(installer_code="INST-NL-A", claim_target="DIAGNOSED")
    claim = ctx["claim"]
    denied = get_success_data(api_client.deny_claim(
        claim["id"], {"denial_reason": "evidence incomplete"}, platform_admin_headers))
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "evidence incomplete"
    reopened = get_success_data(api_client.reopen_claim(claim["id"], platform_admin_headers))
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["denial_reason"] is None, "the earlier refusal is no longer the operative record"
    rediagnosed = get_success_data(api_client.diagnose_claim(
        claim["id"], monitoring_service_headers))
    assert rediagnosed["status"] == "DIAGNOSED"
    assert rediagnosed["diagnostic_source"] == "REMOTE_VERIFIED"


def test_claim_closed_reopens_only_while_unit_is_failed_or_offline(api, platform_admin_headers,
                                                                  installer_headers):
    """PRD §3.6: "A `CLOSED` claim may be reopened only while the unit is `FAILED` or
    `OFFLINE`, which is the evidence that the repair did not hold." PRD §3.6: "Either
    way the claim moves to `REOPENED` and `reopen_count` — the tally of times the claim
    has been reopened after being closed or denied — is incremented."

    Design: Difficulty/non_linear_state_machine/claim_cycle_reopen_and_rediagnose
    """
    ctx = setup_failed_unit_claim(installer_code="INST-NL-B", claim_target="DISPATCHED")
    unit, claim = ctx["unit"], ctx["claim"]
    assert claim["status"] == "DISPATCHED", (
        "an approved claim with a replacement in flight can only be dispatched, not closed"
    )
    assert unit["monitored_status"] == "FAILED"
    order = get_success_data(api_client.list_replacement_orders(
        platform_admin_headers, {"claim_id": claim["id"]}))[0]
    install_order(order["id"], "NLB-R1", "2026-08-20T00:00:00Z", ctx["installer"]["id"])
    closed = get_success_data(api_client.get_claim(claim["id"], platform_admin_headers))
    assert closed["status"] == "CLOSED"
    observe(unit["id"], 0.0, "2026-08-25T00:00:00Z")
    assert get_unit(unit["id"])["monitored_status"] == "FAILED", (
        "the repair did not hold, which is what admits the reopen"
    )
    reopened = get_success_data(api_client.reopen_claim(claim["id"], platform_admin_headers))
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1


# ─── Queue B: entities ────────────────────────────────────────────────

def test_fresh_design_project_starts_draft_with_derived_dc_ac_ratio(api):
    """PRD §3.2: "On creation the project opens in `DRAFT` and the system derives its
    sizing figure. The `dc_ac_ratio` is the total DC nameplate `dc_capacity_watts`
    divided by the array's AC nameplate, which is the `module_count` multiplied by
    three hundred and fifty watts per microinverter; the quotient is carried to four
    decimal places with round-half-up." PRD §3.2: "`rejection_reason` is null on every
    project that has not been rejected."

    Design: Corner/entities/design_project_defaults_and_computed_ratio
    """
    set_clock()
    installer = setup_certified_installer("INST-C1")
    installer = set_installer_level(installer["id"], "GOLD")
    project = open_design_project(installer["id"], module_count=20, dc_capacity_watts=10000)
    assert project["status"] == "DRAFT"
    assert project["dc_ac_ratio"] == 1.4286
    assert project["version"] == 1
    assert project["rejection_reason"] is None


def test_installer_missing_company_name_is_a_malformed_body(api, platform_admin_headers):
    """PRD §2.5: "structural validity of the body (missing required fields, wrong
    types, values outside their permitted domain, reported as
    `ERR_INVALID_REQUEST_BODY`)". PRD §3.1: "Registration records a `company_name`
    and the unique business identifier `installer_code`, optionally an
    `contact_email`".

    Design: Corner/entities/installer_missing_required_field_returns_invalid_request
    """
    set_clock()
    resp = api_client.create_installer({"installer_code": "INST-C2"}, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST_BODY, 400)


def test_unknown_installer_read_is_not_found(api, platform_admin_headers):
    """PRD §2.5: "the first identifier in the path that resolves to nothing produces
    `ERR_RESOURCE_NOT_FOUND` for the whole request".

    Design: Corner/entities/installer_not_found_on_read
    """
    set_clock()
    resp = api_client.get_installer(NONEXISTENT_ID, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)


def test_commissioning_synthesizes_a_commissioned_unit_on_the_system(api):
    """PRD §3.3: "A successful commissioning creates one `Unit` row per payload entry,
    each with `commissioning_state` set to `COMMISSIONED` and `monitored_status`
    beginning at `ONLINE`, and resolves each unit's `production_lot_id` from the lot
    code that was supplied. Each unit's `replacement_window_position` is seeded at
    five".

    Design: Corner/entities/unit_creation_after_registration_is_commissioned_and_subresources
    """
    ctx = setup_system_with_units(installer_code="INST-C5", unit_serials=["C5-U1"],
                                  unit_models=["IQ8"], lot_code="LOT-C5")
    system, unit = ctx["system"], ctx["units"][0]
    assert system["unit_count"] == 1
    assert unit["commissioning_state"] == "COMMISSIONED"
    assert unit["monitored_status"] == "ONLINE"
    assert unit["serial_number"] == "C5-U1"
    assert unit["production_lot_id"] == ctx["lot"]["id"]
    assert unit["replacement_window_position"] == 5


def test_duplicate_serial_is_rejected_and_no_unit_is_created(api, platform_admin_headers,
                                                            installer_headers):
    """PRD §3.3: "Every `serial_number` in the payload must then be globally unique
    across all `Unit` rows, because a serial number is the manufacturer's only handle
    on a physical device: a repeat is `ERR_SERIAL_ALREADY_REGISTERED`."

    Design: Corner/entities/serial_already_registered_conflict
    """
    ctx = setup_system_with_units(installer_code="INST-C6", unit_serials=["C6-U1"],
                                  lot_code="LOT-C6", site_address="24 Yankee Way")
    installer, lot = ctx["installer"], ctx["lot"]
    second = setup_approved_design(installer["id"], site_address="25 Yankee Way")
    resp = api_client.create_system_registration(
        {
            "installer_id": installer["id"],
            "design_project_id": second["id"],
            "site_address": "25 Yankee Way",
            "site_postal_code": "94025",
            "homeowner_name": "Y. Yankee",
            "homeowner_email": "y@yankee.example",
            "commissioned_at": "2026-05-01T00:00:00Z",
            "units": [{"serial_number": "C6-U1", "model_code": "IQ8",
                       "installed_at": "2026-05-01T00:00:00Z",
                       "production_lot_code": "LOT-C6"}],
        },
        make_installer_headers(installer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SERIAL_ALREADY_REGISTERED, 409)
    units = get_success_data(api_client.list_lot_units(lot["id"], platform_admin_headers))
    assert len(units) == 1, "the conflicting serial must not create a second unit row"


def test_production_lot_read_carries_id_and_created_at_only(api, platform_admin_headers):
    """PRD §2.4: "Three entities are deliberately outside it: `ProductionLot`,
    `WarrantyTransfer`, and `ReplacementOrder` expose only `id` and `created_at`. They
    carry no `updated_at` field and no `version` field at all".

    Design: Corner/entities/production_lot_is_immutable_without_version
    """
    set_clock()
    lot = create_lot("LOT-C7", replacement_model_code="IQ8HC", defect_threshold_pct=6.0)
    fetched = get_lot(lot["id"])
    assert fetched["id"] == lot["id"]
    assert fetched.get("version") is None
    assert fetched.get("updated_at") is None
    assert fetched["lot_status"] == "NORMAL"
    assert fetched["defect_threshold_pct"] == 6.0


# ─── Queue B: state_machines ──────────────────────────────────────────

def test_second_activation_of_an_active_installer_is_invalid_state(api, platform_admin_headers):
    """PRD §3.1: "Activation requires the installer to currently be `PENDING`; anything
    else is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/installer_activate_from_active_is_invalid_state
    """
    installer = create_installer("INST-SM1", "Zulu Solar")
    activated = activate_installer(installer["id"])
    certified_until = activated["certified_until"]
    resp = api_client.activate_installer(installer["id"], platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    still = get_installer(installer["id"])
    assert still["certification_status"] == "ACTIVE"
    assert still["certified_until"] == certified_until, "a refused activation must not re-issue the term"


def test_reinstatement_is_refused_while_a_claim_is_mid_flight(api, platform_admin_headers):
    """PRD §3.1: "Reinstatement carries an extra precondition beyond state — the
    installer must have zero `WarrantyClaim` rows sitting in `SUBMITTED` or
    `DIAGNOSED` — because a contractor suspended mid-investigation must finish that
    investigation before returning to work."

    Design: Corner/state_machines/suspended_installer_cannot_be_reinstated_while_claim_midflight
    """
    ctx = setup_failed_unit_claim(installer_code="INST-SM2", claim_target="DIAGNOSED")
    installer, claim = ctx["installer"], ctx["claim"]
    assert claim["status"] == "DIAGNOSED"
    suspended = suspend_installer(installer["id"])
    assert suspended["certification_status"] == "SUSPENDED"
    resp = api_client.reinstate_installer(installer["id"], platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_installer(installer["id"])["certification_status"] == "SUSPENDED"


def test_denying_an_approved_claim_is_invalid_state(api, platform_admin_headers):
    """PRD §3.6: "Denial is the other branch out of `DIAGNOSED`."

    Design: Corner/state_machines/claim_deny_from_approved_is_invalid_state
    """
    ctx = setup_failed_unit_claim(installer_code="INST-SM3", claim_target="APPROVED")
    claim = ctx["claim"]
    assert claim["status"] == "APPROVED"
    resp = api_client.deny_claim(claim["id"], {"denial_reason": "late paperwork"},
                                 platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = get_success_data(api_client.get_claim(claim["id"], platform_admin_headers))
    assert after["status"] == "APPROVED"
    assert after["denial_reason"] is None


def test_approved_claim_with_no_replacement_closes_as_a_write_off(api, platform_admin_headers):
    """PRD §3.6: "Closing it unreplaced moves the claim straight from `APPROVED` to
    `CLOSED`, and this is only permitted while no replacement order references the
    claim at all — a claim that already has an order in flight must be dispatched or
    cancelled, not closed."

    Design: Corner/state_machines/approved_claim_without_replacement_closes
    """
    ctx = setup_failed_unit_claim(installer_code="INST-SM4", claim_target="APPROVED")
    claim = ctx["claim"]
    closed = get_success_data(api_client.close_claim_unreplaced(claim["id"], platform_admin_headers))
    assert closed["status"] == "CLOSED"
    orders = get_success_data(api_client.list_replacement_orders(
        platform_admin_headers, {"claim_id": claim["id"]}))
    assert orders == [], "the write-off branch creates no replacement shipment"


def test_unit_ratio_strictly_below_point_nine_five_demotes_and_recovers(api):
    """PRD §3.4: "A commissioned unit that is `ONLINE` and reports a ratio below 0.95
    slips to `UNDERPERFORMING`; the system stores the observed figure in
    `last_performance_ratio`, adds one to `underperformance_streak_hours`". PRD §3.4:
    "An `UNDERPERFORMING` unit that reports a ratio of at least 0.95 recovers to
    `ONLINE` and has its streak reset to zero."

    Design: Corner/state_machines/unit_ratio_boundary_one_hundredth_below_threshold
    """
    ctx = setup_system_with_units(installer_code="INST-SM5", unit_serials=["SM5-U1"],
                                  unit_models=["IQ8"], lot_code="LOT-SM5",
                                  site_address="29 Delta Two Way")
    unit = ctx["units"][0]
    unit = observe(unit["id"], 0.95, "2026-08-01T00:00:00Z")
    assert unit["monitored_status"] == "ONLINE", "0.95 is not below the threshold"
    assert unit["underperformance_streak_hours"] == 0
    unit = observe(unit["id"], 0.94, "2026-08-02T00:00:00Z")
    assert unit["monitored_status"] == "UNDERPERFORMING"
    assert unit["underperformance_streak_hours"] == 1
    assert unit["last_performance_ratio"] == 0.94
    unit = observe(unit["id"], 0.96, "2026-08-03T00:00:00Z")
    assert unit["monitored_status"] == "ONLINE"
    assert unit["underperformance_streak_hours"] == 0


def test_campaign_close_installs_outstanding_orders_and_restores_units(api, platform_admin_headers,
                                                                       installer_headers):
    """PRD §3.5: "Closing a dispatching campaign stamps `window_end_at`, moves the
    campaign to `COMPLETED`, and drives every one of its `DISPATCHED` orders to
    `INSTALLED`, returning the affected units to `ONLINE`."

    Design: Corner/state_machines/campaign_close_completes_and_installs_outstanding_orders
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_system_with_units(installer_code="INST-SM6",
                                  unit_serials=[f"SM6-U{i}" for i in range(1, 4)],
                                  unit_models=["IQ7"] * 3, lot_code="LOT-SM6",
                                  embed_model_code="IQ7", site_address="30 Echo Two Way")
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=3)
    campaign = activate_campaign(campaign["id"])
    assert campaign["dispatched_count"] == 3
    for order in list_orders(campaign_id=campaign["id"], status="PENDING_DISPATCH"):
        dispatch_order(order["id"])
    closed = get_success_data(api_client.close_campaign(campaign["id"], platform_admin_headers))
    assert closed["status"] == "COMPLETED"
    assert closed["window_end_at"] == "2026-09-01T00:00:00.000Z"
    remaining = list_orders(campaign_id=campaign["id"], status="DISPATCHED")
    assert remaining == [], "every dispatched order is installed by the close transition"
    unit = get_unit(ctx["units"][2]["id"])
    assert unit["monitored_status"] == "ONLINE"
    assert unit["replacement_count"] == 1