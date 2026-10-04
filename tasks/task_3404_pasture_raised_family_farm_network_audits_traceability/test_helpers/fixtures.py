"""Composite setup helpers.

Every function drives the live API through the shared client and uses the
lenient get_success_data validator, so a broken precondition surfaces as a
clear setup failure rather than an assertion error inside a test.

The canonical base chain for an ACTIVE farm (used by most scenarios) is:
create farm -> schedule INITIAL audit -> advance clock -> complete PASSED ->
re-read farm version -> create contract (OCC) -> activate.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    add_stop_payload,
    collect_stop_payload,
    complete_audit_payload,
    create_audit_payload,
    create_commitment_payload,
    create_contract_payload,
    create_farm_payload,
    create_forecast_payload,
    create_incident_payload,
    create_retailer_payload,
    create_route_payload,
    create_settlement_payload,
    finalize_settlement_payload,
    grade_lot_payload,
    pack_cartons_payload,
    resolve_hold_payload,
    resolve_incident_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_auditor_headers

NM = TEST_USERS["network_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]
QM = TEST_USERS["quality_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


# --- Single-step helpers -----------------------------------------------------


def create_farm(**overrides):
    resp = api_client.create_farm(create_farm_payload(**overrides), NM)
    return get_success_data(resp)


def get_farm(farm_id):
    resp = api_client.get_farm(farm_id, NM)
    return get_success_data(resp)


def schedule_audit(farm_id, audit_type=None, scheduled_for=None):
    payload = create_audit_payload()
    if audit_type is not None:
        payload["audit_type"] = audit_type
    if scheduled_for is not None:
        payload["scheduled_for"] = scheduled_for
    resp = api_client.schedule_audit(farm_id, payload, NM)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), PA)
    return get_success_data(resp)


def complete_audit(audit_id, outcome="PASSED", findings=None, auditor_user_id="auditor-a"):
    headers = make_auditor_headers(auditor_user_id)
    resp = api_client.complete_audit(audit_id, complete_audit_payload(outcome, findings), headers)
    return get_success_data(resp)


def create_contract(farm_id, expected_farm_version=None, **overrides):
    """Create a contract, reading the farm's live version when the caller does
    not pin expected_farm_version explicitly (PRD §2.4 OCC rule)."""
    if expected_farm_version is None:
        expected_farm_version = get_farm(farm_id)["version"]
    payload = create_contract_payload(expected_farm_version, **overrides)
    resp = api_client.create_contract(farm_id, payload, NM)
    return get_success_data(resp)


def activate_farm(farm_id):
    resp = api_client.activate_farm(farm_id, NM)
    return get_success_data(resp)


def reinstate_farm(farm_id):
    resp = api_client.reinstate_farm(farm_id, NM)
    return get_success_data(resp)


def remove_farm(farm_id, reason="withdrew from program"):
    resp = api_client.remove_farm(farm_id, {"reason": reason}, NM)
    return get_success_data(resp)


def create_retailer(**overrides):
    resp = api_client.create_retailer(create_retailer_payload(**overrides), PA)
    return get_success_data(resp)


def create_forecast(farm_id, week_start, season=None, weather_severity=None):
    resp = api_client.create_forecast(
        farm_id, create_forecast_payload(week_start, season, weather_severity), NM
    )
    return get_success_data(resp)


def create_commitment(retailer_id, farm_id, week_start, committed_dozens):
    resp = api_client.create_commitment(
        create_commitment_payload(retailer_id, farm_id, week_start, committed_dozens), NM
    )
    return get_success_data(resp)


def get_commitment(commitment_id):
    resp = api_client.get_commitment(commitment_id, NM)
    return get_success_data(resp)


def create_route(**overrides):
    resp = api_client.create_route(create_route_payload(**overrides), PO)
    return get_success_data(resp)


def get_route(route_id):
    resp = api_client.get_route(route_id, PO)
    return get_success_data(resp)


def add_stop(route_id, farm_id, stop_sequence=1, planned_cases=2):
    resp = api_client.add_stop(
        route_id, add_stop_payload(farm_id, stop_sequence, planned_cases), PO
    )
    return get_success_data(resp)


def collect_stop(route_id, stop_sequence=1, collected_cases=2, laid_start_date=None,
                 laid_end_date=None):
    payload = collect_stop_payload(collected_cases)
    if laid_start_date is not None:
        payload["laid_start_date"] = laid_start_date
    if laid_end_date is not None:
        payload["laid_end_date"] = laid_end_date
    resp = api_client.collect_stop(route_id, stop_sequence, payload, PO)
    return get_success_data(resp)


def skip_stop(route_id, stop_sequence=1):
    resp = api_client.skip_stop(route_id, stop_sequence, {}, PO)
    return get_success_data(resp)


def complete_route(route_id):
    resp = api_client.complete_route(route_id, PO)
    return get_success_data(resp)


def get_lot(lot_id):
    resp = api_client.get_lot(lot_id, QM)
    return get_success_data(resp)


def grade_lot(lot_id, quality_score):
    resp = api_client.grade_lot(lot_id, grade_lot_payload(quality_score), QM)
    return get_success_data(resp)


def resolve_hold(lot_id, disposition="RELEASE"):
    resp = api_client.resolve_hold(lot_id, resolve_hold_payload(disposition), QM)
    return get_success_data(resp)


def pack_cartons(lot_id, carton_count, pack_size=None):
    resp = api_client.pack_cartons(lot_id, pack_cartons_payload(carton_count, pack_size), PO)
    return get_success_data(resp)


def report_incident(farm_id, role_headers=None, **overrides):
    resp = api_client.report_incident(
        farm_id, create_incident_payload(**overrides), role_headers or NM
    )
    return get_success_data(resp)


def resolve_incident(incident_id, disposition="NONE", **overrides):
    resp = api_client.resolve_incident(
        incident_id, resolve_incident_payload(disposition, **overrides), NM
    )
    return get_success_data(resp)


def list_audit_corrective_actions(audit_id):
    """Return the corrective-action rows opened by an audit (data list)."""
    resp = api_client.list_corrective_actions(audit_id, NM)
    return get_success_data(resp)


def submit_corrective_action(ca_id, evidence_notes="remediation completed"):
    resp = api_client.submit_corrective_action(ca_id, {"evidence_notes": evidence_notes}, NM)
    return get_success_data(resp)


def verify_corrective_action(ca_id, decision="VERIFY_CLOSED", auditor_user_id="auditor-b"):
    headers = make_auditor_headers(auditor_user_id)
    payload = {"decision": decision}
    resp = api_client.verify_corrective_action(ca_id, payload, headers)
    return get_success_data(resp)


def create_settlement_run(week_start=None):
    resp = api_client.create_settlement_run(create_settlement_payload(week_start), NM)
    return get_success_data(resp)


def get_settlement_run(run_id):
    resp = api_client.get_settlement_run(run_id, NM)
    return get_success_data(resp)


def finalize_settlement(run_id, actual_base_cents=None):
    resp = api_client.finalize_settlement(
        run_id, finalize_settlement_payload(actual_base_cents), NM
    )
    return get_success_data(resp)


# --- Composite tiers ---------------------------------------------------------


def create_active_farm(name=None, audit_complete_at=None, contract_overrides=None,
                       **farm_overrides):
    """Full base chain: farm -> INITIAL audit PASSED -> contract -> ACTIVE.

    Returns {"farm": <freshly re-read ACTIVE farm>, "audit": ..., "contract": ...}.
    `audit_complete_at` defaults to 2026-09-03T09:00:00Z; pass a later instant
    (e.g. 10:00) when a scenario needs a second farm so the logical clock stays
    monotonic.
    """
    farm = create_farm(name=name or DEFAULTS["FARM_NAME"], **farm_overrides)
    audit = schedule_audit(farm["id"])
    set_clock(audit_complete_at or DEFAULTS["AUDIT_COMPLETE_AT"])
    complete_audit(audit["id"], "PASSED")
    contract = create_contract(farm["id"], **(contract_overrides or {}))
    activate_farm(farm["id"])
    return {"farm": get_farm(farm["id"]), "audit": audit, "contract": contract}


def setup_route_with_stop(farm_id, route_date=None, planned_cases=2, stop_sequence=1,
                          capacity_cases=None):
    """PLANNED route carrying one SCHEDULED stop for the farm."""
    route = create_route(
        route_date=route_date or DEFAULTS["ROUTE_DATE"],
        capacity_cases=capacity_cases or DEFAULTS["CAPACITY_CASES"],
    )
    add_stop(route["id"], farm_id, stop_sequence, planned_cases)
    return {"route": get_route(route["id"])}


def setup_collected_lot(farm_id, route_date=None, planned_cases=None, collected_cases=2,
                        collect_at=None, laid_start_date=None, laid_end_date=None,
                        capacity_cases=None, stop_sequence=1):
    """Route + stop + collection. Returns {"route": ..., "lot": ...}.

    Advances the logical clock to `collect_at` before collecting; the instant
    must be strictly after the current clock (default 2026-09-08T10:00:00Z).
    """
    planned = planned_cases if planned_cases is not None else collected_cases
    bundle = setup_route_with_stop(
        farm_id, route_date=route_date, planned_cases=planned,
        stop_sequence=stop_sequence, capacity_cases=capacity_cases,
    )
    set_clock(collect_at or DEFAULTS["COLLECT_AT"])
    lot = collect_stop(
        bundle["route"]["id"], stop_sequence, collected_cases,
        laid_start_date=laid_start_date, laid_end_date=laid_end_date,
    )
    return {"route": get_route(bundle["route"]["id"]), "lot": lot}


def setup_graded_lot(farm_id, quality_score, **collect_kwargs):
    """Collected lot graded at `quality_score`. Returns {"route", "lot"}."""
    bundle = setup_collected_lot(farm_id, **collect_kwargs)
    lot = grade_lot(bundle["lot"]["id"], quality_score)
    return {"route": bundle["route"], "lot": lot}


def setup_commitment_scenario(week_start=None, season="AUTUMN", weather_severity="NONE",
                              committed_dozens=None, farm_name="Commitment Farm",
                              contract_end="2027-08-31"):
    """ACTIVE farm + retailer + forecast (+ commitment when committed_dozens given).

    Returns {"farm", "contract", "retailer", "forecast", "commitment"?}.
    """
    week = week_start or DEFAULTS["WEEK_START"]
    bundle = create_active_farm(
        name=farm_name, contract_overrides={"end_date": contract_end}
    )
    retailer = create_retailer()
    forecast = create_forecast(bundle["farm"]["id"], week, season, weather_severity)
    result = {
        "farm": bundle["farm"],
        "contract": bundle["contract"],
        "retailer": retailer,
        "forecast": forecast,
    }
    if committed_dozens is not None:
        result["commitment"] = create_commitment(
            retailer["id"], bundle["farm"]["id"], week, committed_dozens
        )
    return result


def setup_packed_week(farm_id, pack_lines, week_collect_dates=None):
    """Pack cartons inside settlement week 2026-09-07 for one farm.

    `pack_lines` is a list of (quality_score, carton_count, pack_size) tuples;
    each becomes its own collected-and-graded lot collected on successive days
    (2026-09-08, -09, -10, ...) so route-date exclusivity is respected.
    Returns {"lots": [...], "cartons": [...]}.
    """
    dates = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12"]
    lots, cartons = [], []
    for i, (score, count, size) in enumerate(pack_lines):
        day = dates[i]
        bundle = setup_graded_lot(
            farm_id,
            score,
            route_date=day,
            planned_cases=max(1, (count + 29) // 30),
            collected_cases=max(1, (count + 29) // 30),
            collect_at=f"{day}T10:00:00Z",
            laid_start_date="2026-09-06",
            laid_end_date=day,
            capacity_cases=max(10, (count + 29) // 30),
        )
        lots.append(bundle["lot"])
        cartons.extend(pack_cartons(bundle["lot"]["id"], count, size))
    return {"lots": lots, "cartons": cartons}
