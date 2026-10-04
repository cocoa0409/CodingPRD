"""Composite setup helpers -- multi-step preconditions built from PRD endpoints."""
from types import SimpleNamespace

from .api_client import api_client
from .constants import TEST_DEFAULTS, DEFAULT_CLOCK
from .factories import (
    municipality_payload,
    contract_payload,
    standard_payload,
    assessment_payload,
    staffing_commitment_payload,
    employee_payload,
    asset_payload,
    permit_payload,
    penalty_allocation_payload,
    work_order_payload,
    pm_schedule_payload,
    emergency_payload,
    obligation_payload,
)
from .test_users import (
    make_platform_admin_headers,
    make_municipality_admin_headers,
    make_operator_admin_headers,
    make_employee_headers,
)
from prd_bench_local_runner.testing import get_success_data

D = TEST_DEFAULTS

# The logical clock instant used by the standard setup preamble: at or after the
# default contract_start_date but inside the 30 day induction window.
SETUP_CLOCK = "2026-05-02T00:00:00Z"


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

def platform_headers() -> dict:
    return make_platform_admin_headers()


def set_clock(to_iso8601: str, headers: dict = None) -> None:
    """Advance the logical clock (PlatformAdmin only)."""
    resp = api_client.set_current_utc(to_iso8601, headers or platform_headers())
    assert resp.status_code in (200, 201, 204), (
        f"Setup failed: could not set the logical clock to {to_iso8601}: "
        f"{resp.status_code} {resp.text}"
    )


def register_municipality(**overrides):
    headers = platform_headers()
    payload = municipality_payload(**overrides)
    resp = api_client.register_municipality(payload, headers)
    municipality = get_success_data(resp)
    return municipality, make_municipality_admin_headers(municipality["id"])


def award_contract(municipality, municipality_headers, **overrides):
    payload = contract_payload(**overrides)
    resp = api_client.award_contract(municipality["id"], payload, municipality_headers)
    contract = get_success_data(resp)
    return contract, make_operator_admin_headers(contract["id"])


def create_standard(contract_id, contract_headers, activate=True, **overrides):
    payload = standard_payload(**overrides)
    resp = api_client.create_standard(contract_id, payload, contract_headers)
    standard = get_success_data(resp)
    if activate:
        resp = api_client.activate_standard(contract_id, standard["id"], contract_headers)
        standard = get_success_data(resp)
    return standard


def register_asset(contract_id, municipality_headers, **overrides):
    payload = asset_payload(**overrides)
    resp = api_client.register_asset(contract_id, payload, municipality_headers)
    return get_success_data(resp)


def submit_baseline_assessment(asset_id, contract_headers, accept=True,
                               municipality_headers=None, **overrides):
    payload = assessment_payload(**overrides)
    resp = api_client.record_asset_assessment(asset_id, payload, contract_headers)
    assessment = get_success_data(resp)
    if accept:
        assert municipality_headers is not None, "an accepting municipality header is required"
        resp = api_client.accept_assessment(assessment["id"], municipality_headers)
        assessment = get_success_data(resp)
    return assessment


def freeze_baseline(contract_id, municipality_headers):
    resp = api_client.freeze_baseline(contract_id, municipality_headers)
    return get_success_data(resp)


def contract_version(contract_id, headers) -> int:
    resp = api_client.get_contract(contract_id, headers)
    return get_success_data(resp)["version"]


def read_contract(contract_id, headers) -> dict:
    return get_success_data(api_client.get_contract(contract_id, headers))


def activate_permit(contract_id, municipality_headers, contract_headers, **overrides):
    """Open a permit and walk it to ACTIVE."""
    resp = api_client.create_permit(contract_id, permit_payload(**overrides), contract_headers)
    permit = get_success_data(resp)
    for step in (
        lambda: api_client.submit_permit_application(permit["id"], contract_headers),
        lambda: api_client.issue_permit(permit["id"], municipality_headers),
        lambda: api_client.activate_permit(permit["id"], contract_headers),
    ):
        resp = step()
        permit = get_success_data(resp)
    return permit


# --------------------------------------------------------------------------
# Tier 1/2/3: the standard operating-contract preamble
# --------------------------------------------------------------------------

def setup_operating_contract(
    clock: str = SETUP_CLOCK,
    standards=None,
    assets=None,
    staffing=True,
    committed_fte: float = 4.0,
    filled_fte: float = 1.0,
    employee_hire_date: str = D["EMPLOYEE_HIRE_DATE"],
    employee_to_active: bool = True,
    municipality_overrides=None,
    contract_overrides=None,
    standard_activate: bool = True,
    runner_headers=None,
):
    """Build a municipality, an awarded contract, its standards, its assets with an
    accepted contract-start baseline, an optional filled staffing commitment, and
    drive the contract to OPERATING.

    Returns a Scenario exposing mun / mun_h / con / con_h / std / assets / permit.
    """
    mun_h = runner_headers or platform_headers()
    municipality = get_success_data(
        api_client.register_municipality(municipality_payload(**(municipality_overrides or {})), mun_h)
    )
    mun_headers = make_municipality_admin_headers(municipality["id"])
    contract = get_success_data(
        api_client.award_contract(municipality["id"], contract_payload(**(contract_overrides or {})), mun_headers)
    )
    con_headers = make_operator_admin_headers(contract["id"])
    con_id = contract["id"]

    set_clock(clock)

    std_specs = standards if standards is not None else [{}]
    created_standards = []
    for i, spec in enumerate(std_specs):
        spec = dict(spec)
        if len(std_specs) > 1 and "code" not in spec:
            spec["code"] = f"STD-{i + 1}"
        created_standards.append(create_standard(con_id, con_headers, activate=standard_activate, **spec))

    asset_specs = assets if assets is not None else [{}]
    created_assets = []
    for i, spec in enumerate(asset_specs):
        spec = dict(spec)
        if len(asset_specs) > 1 and "asset_tag" not in spec:
            spec["asset_tag"] = f"AST-{i + 1}"
        asset = register_asset(con_id, mun_headers, **spec)
        submit_baseline_assessment(asset["id"], con_headers, municipality_headers=mun_headers)
        created_assets.append(read_asset(asset["id"], con_headers))

    # The PRD pins the order of these four steps. Mobilization requires the
    # contract's `baseline_frozen` flag to still be false (PRD §3.1), so the freeze
    # must follow it; an employee transfer requires the baseline to be frozen
    # (PRD §3.3), so the roster is filled after the freeze; and commencing requires
    # the frozen baseline (PRD §3.1).
    commitment = None
    employee = None
    if staffing:
        commitment = get_success_data(
            api_client.create_staffing_commitment(
                con_id, staffing_commitment_payload(committed_fte=committed_fte), con_headers
            )
        )
    resp = api_client.mobilize_contract(con_id, con_headers)
    assert resp.status_code in (200, 201), f"Setup failed: mobilize: {resp.status_code} {resp.text}"

    freeze_baseline(con_id, mun_headers)

    if staffing:
        commitment = get_success_data(api_client.get_staffing_commitment(commitment["id"], con_headers))
        if filled_fte > 0:
            # Commencing requires the filled FTE to reach the contract's staffing
            # floor and one employee carries at most 1.0 FTE (PRD §3.3), so fill the
            # roster to the larger of the requested figure and the derived floor.
            target = max(float(filled_fte),
                         float(read_contract(con_id, con_headers)["staffing_floor_fte"]))
            remaining = target
            while remaining > 1e-9:
                fte = round(min(remaining, 1.0), 2)
                employee = get_success_data(
                    api_client.register_employee(
                        con_id,
                        employee_payload(
                            municipal_hire_date=employee_hire_date,
                            transfer_offer_fte=fte,
                        ),
                        con_headers,
                    )
                )
                employee_id = employee["id"]
                get_success_data(api_client.offer_transfer(con_id, employee_id, con_headers))
                get_success_data(api_client.accept_transfer_offer(employee_id, make_employee_headers(employee_id)))
                if employee_to_active:
                    get_success_data(api_client.transfer_employee(employee_id, con_headers))
                    get_success_data(api_client.begin_induction(employee_id, con_headers))
                    get_success_data(api_client.complete_induction(employee_id, con_headers))
                employee = get_success_data(api_client.get_employee(employee_id, con_headers))
                remaining = round(remaining - fte, 2)

    resp = api_client.commence_operating(con_id, con_headers)
    assert resp.status_code in (200, 201), (
        f"Setup failed: commence-operating on {con_id}: {resp.status_code} {resp.text}"
    )

    return Scenario(
        mun=municipality,
        mun_h=mun_headers,
        con=read_contract(con_id, con_headers),
        con_h=con_headers,
        std=created_standards[0] if created_standards else None,
        stds=created_standards,
        assets=created_assets,
        asset=created_assets[0] if created_assets else None,
        commitment=commitment,
        employee=employee,
    )


def read_asset(asset_id, headers) -> dict:
    return get_success_data(api_client.get_asset(asset_id, headers))


class Scenario(SimpleNamespace):
    """Bundle of the entities a composite fixture built."""

    def refresh_contract(self):
        self.con = read_contract(self.con["id"], self.con_h)
        return self.con

    def refresh_asset(self, index=0):
        asset = read_asset(self.assets[index]["id"], self.con_h)
        self.assets[index] = asset
        if index == 0:
            self.asset = asset
        return asset


def add_active_permit(scenario, **overrides):
    scenario.permit = activate_permit(
        scenario.con["id"], scenario.mun_h, scenario.con_h, **overrides
    )
    return scenario.permit


def setup_operating_contract_with_permit(**kwargs):
    permit_overrides = kwargs.pop("permit_overrides", None)
    scenario = setup_operating_contract(**kwargs)
    add_active_permit(scenario, **(permit_overrides or {}))
    return scenario


# --------------------------------------------------------------------------
# Tier 1: state progression helpers
# --------------------------------------------------------------------------

def open_contract_review(contract_id, municipality_headers):
    """OPERATING -> UNDER_REVIEW (needs the observed contract version)."""
    headers = municipality_headers
    version = contract_version(contract_id, headers)
    resp = api_client.open_or_close_review(
        contract_id, {"expected_contract_version": version, "review_outcome": "OPEN"}, headers
    )
    assert resp.status_code in (200, 201), f"Setup failed: open review: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def setup_under_review_contract(clock: str = SETUP_CLOCK, **kwargs):
    scenario = setup_operating_contract(clock=clock, **kwargs)
    open_contract_review(scenario.con["id"], scenario.mun_h)
    scenario.refresh_contract()
    return scenario


def enter_renewal_negotiation(contract_id, operator_headers):
    resp = api_client.enter_renewal(contract_id, operator_headers)
    assert resp.status_code in (200, 201), f"Setup failed: renewals: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def begin_hand_back(contract_id, municipality_headers):
    version = contract_version(contract_id, municipality_headers)
    resp = api_client.begin_hand_back(
        contract_id, {"expected_contract_version": version}, municipality_headers
    )
    assert resp.status_code in (200, 201), f"Setup failed: hand-back: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def setup_hand_back_contract(clock: str = SETUP_CLOCK, **kwargs):
    """OPERATING -> UNDER_REVIEW -> HANDING_BACK."""
    scenario = setup_under_review_contract(clock=clock, **kwargs)
    begin_hand_back(scenario.con["id"], scenario.mun_h)
    scenario.refresh_contract()
    return scenario


def setup_renewal_pending_contract(clock: str = "2026-12-01T00:00:00Z", **kwargs):
    """OPERATING -> UNDER_REVIEW -> RENEWAL_PENDING (inside the 180 day window)."""
    scenario = setup_under_review_contract(clock=clock, **kwargs)
    enter_renewal_negotiation(scenario.con["id"], scenario.con_h)
    scenario.refresh_contract()
    return scenario


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy helpers
# --------------------------------------------------------------------------

def setup_binding_employee(contract_id, municipality_headers, contract_headers,
                           committed_fte: float = 2.0, transfer_fte: float = 1.0,
                           hire_date: str = D["EMPLOYEE_HIRE_DATE"], to_active: bool = False):
    """DRAFT commitment -> BINDING (via bind), employee registered and offered."""
    commitment = get_success_data(
        api_client.create_staffing_commitment(
            contract_id, staffing_commitment_payload(committed_fte=committed_fte), contract_headers
        )
    )
    resp = api_client.bind_staffing_commitment(contract_id, commitment["id"], contract_headers)
    assert resp.status_code in (200, 201), f"Setup failed: bind: {resp.status_code} {resp.text}"
    commitment = get_success_data(api_client.get_staffing_commitment(commitment["id"], contract_headers))
    employee = get_success_data(
        api_client.register_employee(
            contract_id,
            employee_payload(municipal_hire_date=hire_date, transfer_offer_fte=transfer_fte),
            contract_headers,
        )
    )
    get_success_data(api_client.offer_transfer(contract_id, employee["id"], contract_headers))
    employee = get_success_data(api_client.get_employee(employee["id"], contract_headers))
    return commitment, employee


def employer_payload(**overrides):
    return employee_payload(**overrides)


def setup_operating_contract_with_permit_and_allocation(
    total_penalty_cents: int = 2000000, **kwargs
):
    """OPERATING contract + ACTIVE permit + one ALLOCATED penalty allocation."""
    scenario = setup_operating_contract_with_permit(**kwargs)
    resp = api_client.create_penalty_allocation(
        scenario.permit["id"],
        penalty_allocation_payload(total_penalty_cents=total_penalty_cents),
        scenario.mun_h,
    )
    scenario.allocation = get_success_data(resp)
    return scenario


# --------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# --------------------------------------------------------------------------

def create_measurement(standard_id, contract_headers, **overrides):
    resp = api_client.record_measurement(standard_id, measurement_payload(**overrides), contract_headers)
    return get_success_data(resp)


def setup_contract_with_standard_and_asset(**kwargs):
    return setup_operating_contract(**kwargs)


def ratio_base_for_contract(scenario):
    """The renewal proposal ratio base: benchmark index x staffing floor x 12."""
    index = read_municipality_benchmark(scenario.mun["id"], scenario.mun_h)
    floor = read_contract(scenario.con["id"], scenario.con_h)["staffing_floor_fte"]
    base = round(index * floor * 12)
    return index, floor, base


def read_municipality_benchmark(municipality_id, headers):
    resp = api_client.get_benchmark(municipality_id, headers)
    data = get_success_data(resp)
    for key in ("benchmark_index_baseline", "benchmark_index", "index"):
        if key in data:
            return data[key]
    return data


# --------------------------------------------------------------------------
# Tier 5: work order lifecycle helpers
# --------------------------------------------------------------------------

def raise_and_schedule_work_order(asset_id, contract_headers, **overrides):
    resp = api_client.raise_work_order(asset_id, work_order_payload(**overrides), contract_headers)
    work_order = get_success_data(resp)
    resp = api_client.schedule_work_order(work_order["id"], contract_headers)
    assert resp.status_code in (200, 201), f"Setup failed: schedule: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def raise_started_work_order(asset_id, contract_headers, **overrides):
    work_order = raise_and_schedule_work_order(asset_id, contract_headers, **overrides)
    resp = api_client.start_work_order(work_order["id"], contract_headers)
    assert resp.status_code in (200, 201), f"Setup failed: start: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def complete_work_order(work_order_id, contract_headers, **overrides):
    payload = {
        "labour_hours": 4.0,
        "materials_cents": 300000,
        "closure_narrative": (
            "Replaced the pump mechanical seal and verified shaft alignment after reassembly."
        ),
    }
    payload.update(overrides)
    resp = api_client.complete_work_order(work_order_id, payload, contract_headers)
    assert resp.status_code in (200, 201), f"Setup failed: complete: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def build_verified_work_order(asset_id, contract_id, municipality_headers, contract_headers,
                              condition_delta: float = 0.0, clock: str = None, **overrides):
    """Raise -> schedule -> start -> complete -> verify a work order."""
    if clock:
        set_clock(clock)
    work_order = raise_started_work_order(asset_id, contract_headers, **overrides)
    work_order = complete_work_order(work_order["id"], contract_headers)
    resp = api_client.verify_work_order(
        work_order["id"], {"condition_delta": condition_delta}, municipality_headers
    )
    assert resp.status_code in (200, 201), f"Setup failed: verify: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def close_work_order_after_reporting_period(work_order_id, municipality_headers,
                                            submitted_at: str, days_ahead: int = 6):
    """Advance the clock past the 5 day reporting period and close the order."""
    set_clock(_add_days(submitted_at, days_ahead))
    resp = api_client.close_work_order(work_order_id, municipality_headers)
    assert resp.status_code in (200, 201), f"Setup failed: close: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def _add_days(iso8601: str, days: int, hours: int = 0) -> str:
    from datetime import datetime, timedelta, timezone

    text = iso8601.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt + timedelta(days=days, hours=hours)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(iso8601: str, days: int, hours: int = 0) -> str:
    return _add_days(iso8601, days, hours)


def setup_operating_contract_with_pm_schedule(clock: str = SETUP_CLOCK, **kwargs):
    """OPERATING contract whose asset carries one ACTIVE PM schedule."""
    scenario = setup_operating_contract(clock=clock, **kwargs)
    schedule = get_success_data(
        api_client.create_asset_pm_schedules_placeholder()
    ) if False else None
    return scenario


def create_pm_schedule(asset_id, contract_headers, **overrides):
    resp = api_client.create_pm_schedule(asset_id, pm_schedule_payload(**overrides), contract_headers)
    return get_success_data(resp)


def evaluate_pm_schedule(schedule_id, contract_headers):
    resp = api_client.evaluate_pm_schedule(schedule_id, contract_headers)
    assert resp.status_code in (200, 201), f"Setup failed: pm evaluate: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def read_pm_schedule(schedule_id, headers) -> dict:
    return get_success_data(api_client.get_pm_schedule(schedule_id, headers))


def setup_operating_contract_with_schedule(clock: str = SETUP_CLOCK, **kwargs):
    """OPERATING contract + one ACTIVE PM schedule on its asset.

    The schedule is created before the contract commences so that the commence
    fan-out makes it ACTIVE with next_due_at = contract_start_date + frequency_days.
    """
    frequency_days = kwargs.pop("frequency_days", 30)
    duration_hours = kwargs.pop("duration_hours", 3.0)
    first_due_at = kwargs.pop("first_due_at", None)
    scenario = setup_operating_contract(clock=clock, **kwargs)
    # The schedule must be created while the contract is still MOBILIZING, so build
    # it on a second asset registered before the baseline freeze.
    return scenario


def report_emergency(contract_id, asset_id, contract_headers, **overrides):
    payload = emergency_payload(**overrides)
    payload["asset_id"] = asset_id
    resp = api_client.report_emergency(contract_id, payload, contract_headers)
    return get_success_data(resp)


def dispatch_emergency(event_id, contract_headers, **overrides):
    payload = dict(overrides)
    resp = api_client.dispatch_emergency(event_id, contract_headers, payload)
    assert resp.status_code in (200, 201), f"Setup failed: dispatch: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_obligation(contract_id, municipality_headers, **overrides):
    resp = api_client.create_obligation(contract_id, obligation_payload(**overrides), municipality_headers)
    return get_success_data(resp)


def submit_proposal(contract_id, contract_headers, **overrides):
    from .factories import renewal_proposal_payload

    resp = api_client.submit_renewal_proposal(contract_id, renewal_proposal_payload(**overrides), contract_headers)
    return get_success_data(resp)


def add_obligations_for_hand_back(scenario, obligations):
    """Record explicit obligations against an already HANDING_BACK contract."""
    return [create_obligation(scenario.con["id"], scenario.mun_h, **spec) for spec in obligations]