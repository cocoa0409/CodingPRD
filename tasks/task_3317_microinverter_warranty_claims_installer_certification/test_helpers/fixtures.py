"""Composite setup helpers built from PRD-declared endpoints.

Every helper drives the API only through endpoints the PRD declares and rebuilds
its preconditions from scratch, because the runner restarts the server before
every test and each test therefore begins against an empty database.
"""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    commission_unit_entry,
    create_campaign_payload,
    create_claim_payload,
    create_design_project_payload,
    create_installer_payload,
    create_labor_reimbursement_payload,
    create_production_lot_payload,
    create_replacement_order_payload,
    create_system_registration_payload,
    create_warranty_transfer_payload,
    diagnostics_payload,
    observation_payload,
)
from .test_users import TEST_USERS, make_installer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
MONITORING = TEST_USERS["monitoring_service_headers"]
HOMEOWNER = TEST_USERS["homeowner_headers"]

NOT_FOUND_ID = NON_EXISTENT_UUID


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START_ISO) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Installer ────────────────────────────────────────

def create_installer(installer_code: str, company_name: str = "Test Solar Co", **overrides) -> dict:
    payload = create_installer_payload(installer_code=installer_code,
                                       company_name=company_name, **overrides)
    return get_success_data(api_client.create_installer(payload, ADMIN), 201)


def activate_installer(installer_id: str) -> dict:
    return get_success_data(api_client.activate_installer(installer_id, ADMIN))


def suspend_installer(installer_id: str, reason: str = "review") -> dict:
    return get_success_data(api_client.suspend_installer(installer_id, ADMIN, {"reason": reason}))


def reinstate_installer(installer_id: str) -> dict:
    return get_success_data(api_client.reinstate_installer(installer_id, ADMIN))


def set_installer_level(installer_id: str, level: str) -> dict:
    return get_success_data(
        api_client.set_installer_level({"installer_id": installer_id, "level": level}, ADMIN)
    )


def get_installer(installer_id: str) -> dict:
    return get_success_data(api_client.get_installer(installer_id, ADMIN))


def get_portfolio(installer_id: str) -> dict:
    return get_success_data(api_client.get_installer_portfolio(installer_id, ADMIN))


def setup_active_installer(installer_code: str, level: str = "GOLD",
                           company_name: str = "Test Solar Co") -> dict:
    """Register an installer, activate it, and raise it to `level`.

    The level change is applied one rung at a time because the PRD only admits a
    single-step promotion, and each rung requires a hundred decided claims; the
    fixtures therefore walk CERTIFIED -> level directly only for GOLD, which the
    PRD documents as one step above CERTIFIED.
    """
    installer = create_installer(installer_code, company_name)
    installer = activate_installer(installer["id"])
    if level != "CERTIFIED":
        installer = set_installer_level(installer["id"], level)
    return installer


def setup_certified_installer(installer_code: str) -> dict:
    """ACTIVE installer left at the default CERTIFIED level."""
    installer = create_installer(installer_code)
    return activate_installer(installer["id"])


# ─── Design project ───────────────────────────────────

def open_design_project(installer_id: str, site_address: str = "1 Test Way",
                        site_postal_code: str = "94000", module_count: int = 20,
                        dc_capacity_watts: int = 10000) -> dict:
    payload = create_design_project_payload(
        installer_id=installer_id, site_address=site_address,
        site_postal_code=site_postal_code, module_count=module_count,
        dc_capacity_watts=dc_capacity_watts,
    )
    return get_success_data(
        api_client.create_design_project(payload, make_installer_headers(installer_id)), 201
    )


def submit_design_project(project_id: str, installer_id: str) -> dict:
    return get_success_data(
        api_client.submit_design_project(project_id, make_installer_headers(installer_id))
    )


def approve_design_project(project_id: str) -> dict:
    return get_success_data(api_client.approve_design_project(project_id, ADMIN))


def setup_approved_design(installer_id: str, site_address: str = "1 Test Way",
                          site_postal_code: str = "94000", module_count: int = 20,
                          dc_capacity_watts: int = 10000) -> dict:
    """Create a design project, submit it, and approve it (the only reference a
    commissioning may cite)."""
    project = open_design_project(installer_id, site_address, site_postal_code,
                                  module_count, dc_capacity_watts)
    submit_design_project(project["id"], installer_id)
    return approve_design_project(project["id"])


def setup_submitted_design(installer_id: str, site_address: str = "1 Test Way",
                           module_count: int = 20, dc_capacity_watts: int = 10000) -> dict:
    project = open_design_project(installer_id, site_address, module_count=module_count,
                                  dc_capacity_watts=dc_capacity_watts)
    return submit_design_project(project["id"], installer_id)


# ─── Production lot ───────────────────────────────────

def create_lot(lot_code: str, embed_model_code: str = "IQ8",
               replacement_model_code: str = "IQ8",
               defect_threshold_pct: float = 5.0,
               manufacture_month: str = "2026-01") -> dict:
    payload = create_production_lot_payload(
        lot_code=lot_code, embed_model_code=embed_model_code,
        replacement_model_code=replacement_model_code,
        defect_threshold_pct=defect_threshold_pct,
        manufacture_month=manufacture_month,
    )
    return get_success_data(api_client.create_production_lot(payload, ADMIN), 201)


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_production_lot(lot_id, ADMIN))


def force_lot_recall(lot_id: str, reason: str = "operator review") -> dict:
    """Operator action that marks a lot RECALL without waiting for a real trend."""
    return get_success_data(
        api_client.lot_action({"lot_id": lot_id, "action": "OPEN_CAMPAIGN_BY_HAND",
                               "reason": reason}, ADMIN)
    )


def clear_lot_recall(lot_id: str) -> dict:
    return get_success_data(
        api_client.lot_action({"lot_id": lot_id, "action": "CLEAR_RECALL"}, ADMIN)
    )


# ─── System registration + units ──────────────────────

def list_system_units(system_id: str) -> list:
    return get_success_data(api_client.list_system_units(system_id, ADMIN))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, ADMIN))


def commission_system(installer_id: str, design_project_id: str,
                      site_address: str = "1 Test Way", site_postal_code: str = "94000",
                      units: list = None, commissioned_at: str = "2026-04-01T00:00:00Z",
                      homeowner_name: str = "T. Tester",
                      homeowner_email: str = "t@test.example") -> dict:
    payload = create_system_registration_payload(
        installer_id=installer_id, design_project_id=design_project_id,
        site_address=site_address, site_postal_code=site_postal_code,
        homeowner_name=homeowner_name, homeowner_email=homeowner_email,
        commissioned_at=commissioned_at,
        units=units or [commission_unit_entry("TEST-U1", installed_at=commissioned_at)],
    )
    return get_success_data(
        api_client.create_system_registration(payload, make_installer_headers(installer_id)), 201
    )


def setup_system_with_units(installer_code: str = "INST-FIX",
                            unit_serials: list = None, unit_models: list = None,
                            lot_code: str = "LOT-FIX", embed_model_code: str = "IQ8",
                            replacement_model_code: str = "IQ8",
                            defect_threshold_pct: float = 1e6,
                            commissioned_at: str = "2026-04-01T00:00:00Z",
                            site_address: str = "1 Test Way",
                            homeowner_name: str = "T. Tester",
                            homeowner_email: str = "t@test.example",
                            level: str = "GOLD",
                            clock_at: str = CLOCK_START_ISO) -> dict:
    """Full hierarchy: ACTIVE GOLD installer + approved design + lot + one system.

    `defect_threshold_pct` defaults high so a small fixture lot never reads RECALL
    (which would block claim filing); pass an explicit threshold when testing the
    latent-trend rules.

    Returns a dict with keys: installer, design_project, lot, system, units.
    """
    set_clock(clock_at)
    installer = setup_active_installer(installer_code, level=level)
    project = setup_approved_design(installer["id"], site_address=site_address,
                                    site_postal_code="94000")
    lot = create_lot(lot_code, embed_model_code=embed_model_code,
                     replacement_model_code=replacement_model_code,
                     defect_threshold_pct=defect_threshold_pct)
    serials = unit_serials or ["FIX-U1"]
    models = unit_models or [embed_model_code] * len(serials)
    entries = [
        commission_unit_entry(serial, model_code=models[i], installed_at=commissioned_at,
                              production_lot_code=lot_code)
        for i, serial in enumerate(serials)
    ]
    system = commission_system(installer["id"], project["id"], site_address=site_address,
                               units=entries, commissioned_at=commissioned_at,
                               homeowner_name=homeowner_name, homeowner_email=homeowner_email)
    return {
        "installer": installer,
        "design_project": project,
        "lot": lot,
        "system": system,
        "units": list_system_units(system["id"]),
    }


# ─── Monitoring ───────────────────────────────────────

def observe(unit_id: str, performance_ratio: float, observed_at: str, **overrides) -> dict:
    return get_success_data(
        api_client.observe_unit(unit_id, observation_payload(performance_ratio, observed_at,
                                                             **overrides), MONITORING)
    )


def diagnose(unit_id: str, observed_at: str, performance_ratio=None, **overrides) -> dict:
    return get_success_data(
        api_client.run_unit_diagnostics(
            unit_id, diagnostics_payload(observed_at, performance_ratio, **overrides), MONITORING
        )
    )


def fail_unit(unit_id: str, observed_at: str = "2026-08-01T00:00:00Z") -> dict:
    """Drive a commissioned unit straight to FAILED with a zero-ratio observation."""
    return observe(unit_id, 0.0, observed_at)


def underperform_unit(unit_id: str, observed_at: str = "2026-08-01T00:00:00Z",
                      performance_ratio: float = 0.80) -> dict:
    return observe(unit_id, performance_ratio, observed_at)


# ─── Claims ───────────────────────────────────────────

def file_claim(installer_id: str, unit: dict, claim_kind: str = "DEFECT",
               remote_diagnostic_ref: str = "DIAG-FIX", expected_unit_version=None,
               **overrides) -> dict:
    payload = create_claim_payload(
        unit_id=unit["id"], installer_id=installer_id, claim_kind=claim_kind,
        remote_diagnostic_ref=remote_diagnostic_ref,
        expected_unit_version=unit["version"] if expected_unit_version is None
        else expected_unit_version,
        **overrides,
    )
    return get_success_data(
        api_client.create_claim(payload, make_installer_headers(installer_id)), 201
    )


def advance_claim(claim_id: str, installer_id: str, target: str) -> dict:
    """Walk a claim to `target`, tolerating a claim that is already further along.

    The reimbursement path submits and diagnoses before delegating here, so only
    the steps that have not yet happened are advanced; the helper is idempotent
    and always returns the claim row rather than whatever a transition returns.
    """
    ich = make_installer_headers(installer_id)

    def _current() -> dict:
        return get_success_data(api_client.get_claim(claim_id, ADMIN))

    claim = _current()
    if target == "SUBMITTED":
        if claim["status"] == "DRAFT":
            return get_success_data(api_client.submit_claim(claim_id, ich))
        return claim

    if claim["status"] == "DRAFT":
        claim = get_success_data(api_client.submit_claim(claim_id, ich))
    if target == "DIAGNOSED":
        if claim["status"] in ("SUBMITTED", "REOPENED"):
            return get_success_data(api_client.diagnose_claim(claim_id, MONITORING))
        return claim

    if claim["status"] in ("SUBMITTED", "REOPENED"):
        claim = get_success_data(api_client.diagnose_claim(claim_id, MONITORING))
    if target == "APPROVED":
        if claim["status"] in ("DIAGNOSED", "REOPENED"):
            return get_success_data(api_client.approve_claim(claim_id, ADMIN))
        return claim

    if claim["status"] in ("DIAGNOSED", "REOPENED"):
        claim = get_success_data(api_client.approve_claim(claim_id, ADMIN))
    if target == "DISPATCHED":
        if claim["status"] == "APPROVED":
            get_success_data(api_client.dispatch_claim(claim_id, ADMIN))
        return _current()
    if target == "CLOSED":
        if claim["status"] == "APPROVED":
            return get_success_data(api_client.close_claim_unreplaced(claim_id, ADMIN))
        return claim
    raise ValueError(f"unsupported claim target {target!r}")


def setup_failed_unit_claim(installer_code: str = "INST-CLM",
                            claim_target: str = "APPROVED",
                            claimed_hours: float = None,
                            unit_serials: list = None,
                            unit_models: list = None,
                            lot_code: str = "LOT-CLM",
                            embed_model_code: str = "IQ7",
                            replacement_model_code: str = "IQ8",
                            defect_threshold_pct: float = 1e6,
                            commissioned_at: str = "2026-04-01T00:00:00Z",
                            site_address: str = "9 Claim Way",
                            level: str = "GOLD",
                            time_to_fail: str = "2026-08-01T00:00:00Z"):
    """Setup a system, fail its first unit, file a claim, and walk it to `claim_target`.

    When `claimed_hours` is supplied the labor reimbursement is filed right after
    the DIAGNOSED step, matching the order the PRD describes (a bill is PENDING
    until the claim is dispatched).

    Returns dict: installer, lot, system, units, unit, claim, reimbursement.
    """
    ctx = setup_system_with_units(
        installer_code=installer_code, unit_serials=unit_serials or ["CLM-U1"],
        unit_models=unit_models or [embed_model_code], lot_code=lot_code,
        embed_model_code=embed_model_code, replacement_model_code=replacement_model_code,
        defect_threshold_pct=defect_threshold_pct, commissioned_at=commissioned_at,
        site_address=site_address, level=level,
    )
    installer = ctx["installer"]
    unit = ctx["units"][0]
    unit = observe(unit["id"], 0.0, time_to_fail)
    claim = file_claim(installer["id"], unit)
    reimbursement = None
    if claimed_hours is not None:
        get_success_data(api_client.submit_claim(claim["id"], make_installer_headers(installer["id"])))
        get_success_data(api_client.diagnose_claim(claim["id"], MONITORING))
        reimbursement = get_success_data(
            api_client.create_labor_reimbursement(
                create_labor_reimbursement_payload(claim_id=claim["id"], claimed_hours=claimed_hours),
                make_installer_headers(installer["id"]),
            ),
            201,
        )
        ctx["reimbursement"] = reimbursement
        if claim_target == "APPROVED":
            claim = get_success_data(api_client.approve_claim(claim["id"], ADMIN))
        elif claim_target != "DIAGNOSED":
            claim = advance_claim(claim["id"], installer["id"], claim_target)
    else:
        claim = advance_claim(claim["id"], installer["id"], claim_target)
    ctx["unit"] = get_unit(unit["id"])
    ctx["claim"] = claim
    ctx.setdefault("reimbursement", reimbursement)
    return ctx


# ─── Replacements ─────────────────────────────────────

def create_manual_order(unit_id: str, installer_version: int, model_code: str = "IQ8",
                        claim_id: str = None) -> dict:
    payload = create_replacement_order_payload(unit_id=unit_id, replacement_model_code=model_code,
                                               expected_unit_version=installer_version)
    if claim_id is not None:
        payload["claim_id"] = claim_id
    return get_success_data(api_client.create_replacement_order(payload, ADMIN), 201)


def dispatch_order(order_id: str) -> dict:
    return get_success_data(api_client.dispatch_replacement_order(order_id, ADMIN))


def install_order(order_id: str, replacement_serial_number: str, installed_at: str,
                  installer_id: str) -> dict:
    return get_success_data(
        api_client.install_replacement_order(
            order_id,
            {"replacement_serial_number": replacement_serial_number, "installed_at": installed_at},
            make_installer_headers(installer_id),
        )
    )


def consume_replacement_position(unit: dict, installer_id: str, serial: str,
                                 installed_at: str, model_code: str = "IQ8") -> dict:
    """Create, dispatch, and install one goodwill replacement on `unit`, consuming
    one of the system's five unscheduled positions (PRD §3.3 / §3.7)."""
    unit = get_unit(unit["id"])
    order = create_manual_order(unit["id"], unit["version"], model_code=model_code)
    dispatch_order(order["id"])
    return install_order(order["id"], serial, installed_at, installer_id)


def setup_suspended_installer_with_claim_history(installer_code: str = "INST-SUS") -> dict:
    """A GOLD installer with a fully paid claim, a second denied claim, and a
    suspension on record — the richest business-safety state the PRD admits before a
    further filing is attempted.

    Returns the usual hierarchy plus: labor, claim_one, claim_two, unit_three.
    """
    ctx = setup_system_with_units(
        installer_code=installer_code,
        unit_serials=[f"{installer_code}-U{i}" for i in (1, 2, 3)],
        unit_models=["IQ8"] * 3, lot_code=f"LOT-{installer_code}", embed_model_code="IQ8",
        replacement_model_code="IQ8", defect_threshold_pct=1e6,
        commissioned_at="2026-01-20T00:00:00Z", site_address=f"9 {installer_code} Way",
    )
    installer = ctx["installer"]
    ich = make_installer_headers(installer["id"])

    unit_one = observe(ctx["units"][0]["id"], 0.0, "2026-08-01T00:00:00Z")
    claim_one = get_success_data(api_client.create_claim(
        {"unit_id": unit_one["id"], "installer_id": installer["id"], "claim_kind": "DEFECT",
         "remote_diagnostic_ref": "DIAG-ONE", "expected_unit_version": unit_one["version"]},
        ich), 201)
    get_success_data(api_client.submit_claim(claim_one["id"], ich))
    get_success_data(api_client.diagnose_claim(claim_one["id"], MONITORING))
    labor = get_success_data(api_client.create_labor_reimbursement(
        {"claim_id": claim_one["id"], "claimed_hours": 2.0}, ich), 201)
    get_success_data(api_client.approve_claim(claim_one["id"], ADMIN))
    order = get_success_data(api_client.dispatch_claim(claim_one["id"], ADMIN))
    install_order(order["id"], f"{installer_code}-R1", "2026-08-20T00:00:00Z", installer["id"])

    unit_two = observe(ctx["units"][1]["id"], 0.0, "2026-08-01T00:00:00Z")
    claim_two = get_success_data(api_client.create_claim(
        {"unit_id": unit_two["id"], "installer_id": installer["id"], "claim_kind": "DEFECT",
         "remote_diagnostic_ref": "DIAG-TWO", "expected_unit_version": unit_two["version"]},
        ich), 201)
    get_success_data(api_client.submit_claim(claim_two["id"], ich))
    get_success_data(api_client.diagnose_claim(claim_two["id"], MONITORING))
    get_success_data(api_client.deny_claim(claim_two["id"], {"denial_reason": "no fault"}, ADMIN))

    suspended = suspend_installer(installer["id"])
    assert suspended["certification_status"] == "SUSPENDED"
    ctx["claim_one"] = claim_one
    ctx["claim_two"] = claim_two
    ctx["labor"] = labor
    ctx["installer"] = suspended
    ctx["unit_three"] = get_unit(ctx["units"][2]["id"])
    return ctx


# ─── Campaigns ────────────────────────────────────────

def create_campaign(lot_id: str, replacement_model_code: str = "IQ8", max_units: int = 3,
                    guaranteed_units: int = None) -> dict:
    payload = create_campaign_payload(lot_id=lot_id, replacement_model_code=replacement_model_code,
                                      max_units=max_units)
    if guaranteed_units is not None:
        payload["guaranteed_units"] = guaranteed_units
    return get_success_data(api_client.create_campaign(payload, ADMIN), 201)


def list_campaigns(lot_id: str = None, status: str = None) -> list:
    params = {}
    if lot_id is not None:
        params["lot_id"] = lot_id
    if status is not None:
        params["status"] = status
    params["limit"] = 100
    return get_success_data(api_client.list_campaigns(ADMIN, params))


def activate_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.activate_campaign(campaign_id, ADMIN))


def list_orders(campaign_id: str = None, unit_id: str = None, status: str = None,
                claim_id: str = None) -> list:
    params = {}
    for key, value in (("campaign_id", campaign_id), ("unit_id", unit_id),
                       ("status", status), ("claim_id", claim_id)):
        if value is not None:
            params[key] = value
    # The collection read is paginated (default 10); these helpers act as a
    # test client reading a whole known-small set, so ask for one full page.
    params["limit"] = 100
    return get_success_data(api_client.list_replacement_orders(ADMIN, params))


def list_claims(unit_id: str = None, installer_id: str = None, status: str = None) -> list:
    params = {}
    for key, value in (("unit_id", unit_id), ("installer_id", installer_id),
                       ("status", status)):
        if value is not None:
            params[key] = value
    params["limit"] = 100
    from test_helpers import TEST_USERS
    return get_success_data(api_client.list_claims(TEST_USERS["platform_admin_headers"], params))


def setup_recalled_lot_with_campaign(installer_code: str = "INST-CMP",
                                     unit_serials: list = None,
                                     lot_code: str = "LOT-CMP",
                                     embed_model_code: str = "IQ7",
                                     replacement_model_code: str = "IQ8",
                                     max_units: int = 3,
                                     guaranteed_units: int = None,
                                     commissioned_at: str = "2026-01-20T00:00:00Z",
                                     site_address: str = "10 Campaign Way"):
    """Install, ACTIVE installer + approved design + lot + units, then force the lot
    into RECALL by hand and draft a campaign of `max_units` targets."""
    serials = unit_serials or ["CMP-U1", "CMP-U2", "CMP-U3"]
    ctx = setup_system_with_units(
        installer_code=installer_code, unit_serials=serials,
        unit_models=[embed_model_code] * len(serials), lot_code=lot_code,
        embed_model_code=embed_model_code, replacement_model_code=replacement_model_code,
        defect_threshold_pct=1e6, commissioned_at=commissioned_at,
        site_address=site_address,
    )
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], replacement_model_code=replacement_model_code,
                               max_units=max_units, guaranteed_units=guaranteed_units)
    ctx["campaign"] = campaign
    return ctx


# ─── Transfers ────────────────────────────────────────

def create_transfer(system_id: str, effective_date: str = "2026-08-15T00:00:00Z",
                    new_owner_name: str = "N. Owner",
                    new_owner_email: str = "n@owner.example",
                    transfer_kind: str = "SALE") -> dict:
    payload = create_warranty_transfer_payload(
        system_id=system_id, effective_date=effective_date, new_owner_name=new_owner_name,
        new_owner_email=new_owner_email, transfer_kind=transfer_kind,
    )
    return get_success_data(api_client.create_warranty_transfer(payload, HOMEOWNER), 201)


def approve_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.approve_warranty_transfer(transfer_id, ADMIN))


# ─── Billing ──────────────────────────────────────────

def create_entitlement(unit_id: str, effective_from: str,
                       entitlement_kind: str = "SERVICE_PLAN") -> dict:
    return get_success_data(
        api_client.create_billing_entitlement(
            {"unit_id": unit_id, "entitlement_kind": entitlement_kind,
             "effective_from": effective_from}, ADMIN),
        201,
    )


def create_billing_correction(system_id: str, period_month: str,
                             corrected_metering_fee_cents: int) -> dict:
    return get_success_data(
        api_client.create_billing_correction(
            {"system_id": system_id, "period_month": period_month,
             "corrected_metering_fee_cents": corrected_metering_fee_cents}, ADMIN)
    )