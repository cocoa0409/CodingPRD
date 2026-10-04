"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the public API,
because the harness restarts the server before each individual test. Fixtures
use ``get_success_data`` internally so a broken precondition surfaces as a clear
"Setup failed" message rather than a confusing assertion failure.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP, POSTMASTER_USER_ID, SUPERVISOR_USER_ID
from .factories import (
    create_adjustment_payload,
    create_auxiliary_payload,
    create_carrier_payload,
    create_coa_payload,
    create_facility_payload,
    create_hold_payload,
    create_inquiry_payload,
    create_point_payload,
    create_route_payload,
    create_rule_payload,
    create_scan_payload,
    create_unit_payload,
    submit_counts_payload,
)
from .test_users import TEST_USERS, make_carrier_headers, make_postmaster_headers, make_supervisor_headers

H = TEST_USERS
_API = api_client

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


# ─── Clock ─────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock. Returns the response data."""
    return get_success_data(
        _API.set_clock({"to_iso8601": to_iso8601}, H["platform_admin_headers"]))


def reset_clock():
    """Pin the clock at the PRD's startup default instant."""
    return set_clock(CLOCK_STARTUP)


# ─── Single-entity creators ────────────────────────────────────────────────

def create_facility(code: str = None, region_class: str = "CONTIGUOUS",
                    cutoff: str = "17:00", operating_days=None) -> dict:
    """Create a facility. Without ``code`` a unique 3-letter code is derived
    from the fixture counter (avoids facility_code uniqueness collisions)."""
    if code is None:
        n = _n()
        code = chr(65 + (n // 26) % 26) + chr(65 + n % 26) + chr(65 + (n // 676) % 26)
    payload = create_facility_payload(
        facility_code=code, region_class=region_class,
        dispatch_cutoff_local=cutoff,
        operating_days=operating_days or ["MON", "TUE", "WED", "THU", "FRI", "SAT"])
    return get_success_data(
        _API.create_facility(payload, H["standards_admin_headers"]))


def create_facility_named(code: str, **overrides) -> dict:
    """Create a facility with an exact 3-letter code (no counter mangling)."""
    payload = create_facility_payload(facility_code=code, **overrides)
    return get_success_data(
        _API.create_facility(payload, H["standards_admin_headers"]))


def create_unit(facility_id: str, code: str = None, **overrides) -> dict:
    code = code or f"DU{_n():04d}"
    return get_success_data(
        _API.create_unit(create_unit_payload(facility_id, unit_code=code, **overrides),
                         H["platform_admin_headers"]))


def create_carrier(unit_id: str, employee_id: str = None,
                   carrier_class: str = "REGULAR", **overrides) -> dict:
    employee_id = employee_id or f"E{_n():07d}"
    return get_success_data(
        _API.create_carrier(unit_id,
                            create_carrier_payload(employee_id,
                                                   carrier_class=carrier_class,
                                                   **overrides),
                            H["postmaster_headers"]))


def create_route(unit_id: str, carrier_id: str, route_code: str = None,
                 **overrides) -> dict:
    route_code = route_code or f"C{_n():03d}"
    return get_success_data(
        _API.create_route(unit_id,
                          create_route_payload(carrier_id, route_code=route_code,
                                               **overrides),
                          H["supervisor_headers"]))


def create_point(unit_id: str, zip11: str = None, **overrides) -> dict:
    zip11 = zip11 or f"9023{_n():07d}"
    return get_success_data(
        _API.create_point(unit_id, create_point_payload(zip11, **overrides),
                          H["ams_headers"]))


def activate_point(unit_id: str, point_id: str, route_id: str) -> dict:
    return get_success_data(
        _API.activate_point(unit_id, point_id, {"route_id": route_id},
                            H["ams_headers"]))


def get_route(unit_id: str, route_id: str) -> dict:
    return get_success_data(_API.get_route(unit_id, route_id, H["supervisor_headers"]))


def get_point(unit_id: str, point_id: str) -> dict:
    return get_success_data(_API.get_point(unit_id, point_id, H["ams_headers"]))


def get_evaluation(unit_id: str, route_id: str, eval_id: str) -> dict:
    return get_success_data(
        _API.get_evaluation(unit_id, route_id, eval_id, H["supervisor_headers"]))


def get_adjustment(unit_id: str, route_id: str, eval_id: str, adj_id: str) -> dict:
    return get_success_data(
        _API.get_adjustment(unit_id, route_id, eval_id, adj_id,
                            H["supervisor_headers"]))


def get_coa(unit_id: str, coa_id: str) -> dict:
    return get_success_data(_API.get_coa(unit_id, coa_id, H["csr_headers"]))


def get_hold(unit_id: str, hold_id: str) -> dict:
    return get_success_data(_API.get_hold(unit_id, hold_id, H["csr_headers"]))


def get_inquiry(unit_id: str, inquiry_id: str) -> dict:
    return get_success_data(_API.get_inquiry(unit_id, inquiry_id, H["csr_headers"]))


def get_auxiliary(unit_id: str, route_id: str, aux_id: str) -> dict:
    rows = get_success_data(
        _API.list_auxiliary(unit_id, route_id, H["supervisor_headers"],
                            params={"limit": 100}))
    for row in rows:
        if row["id"] == aux_id:
            return row
    raise AssertionError(f"Setup failed: auxiliary {aux_id} not found in list")


def list_sequence_entries(unit_id: str, route_id: str) -> list:
    return get_success_data(
        _API.list_sequence_entries(unit_id, route_id, H["supervisor_headers"],
                                   params={"limit": 100}))


# ─── Tier 2: Entity hierarchy ──────────────────────────────────────────────

def _fresh_unit_code() -> str:
    return f"DU{_n():04d}"


def _fresh_employee_id() -> str:
    return f"E{_n():07d}"


def _fresh_route_code() -> str:
    return f"C{_n():03d}"


def _fresh_zip11() -> str:
    return f"9023{_n():07d}"


def setup_unit_with_route(case_slots: int = 500, route_code: str = None,
                          unit_code: str = None, facility_code: str = None,
                          carrier_class: str = "REGULAR") -> dict:
    """Facility + unit + one REGULAR carrier + one STANDARD route.

    Returns a dict with keys: facility, unit, carrier, route.
    """
    fac = create_facility(code=facility_code)
    unit = create_unit(fac["id"], code=unit_code)
    car = create_carrier(unit["id"], carrier_class=carrier_class)
    route = create_route(unit["id"], car["id"], route_code=route_code)
    return {"facility": fac, "unit": unit, "carrier": car, "route": route}


def setup_route_with_active_points(num_points: int, case_slots: int = 500) -> dict:
    """Unit + route + ``num_points`` points activated onto the route.

    Returns dict with facility, unit, carrier, route, points (list of created
    point payloads, in activation order = line-of-travel order 1..N).
    """
    ctx = setup_unit_with_route(case_slots=case_slots)
    points = []
    for _ in range(num_points):
        p = create_point(ctx["unit"]["id"])
        activate_point(ctx["unit"]["id"], p["id"], ctx["route"]["id"])
        points.append(p)
    ctx["points"] = points
    # Refresh route snapshot (activations bump the route version and counts).
    ctx["route"] = get_route(ctx["unit"]["id"], ctx["route"]["id"])
    return ctx


# ─── Tier 3: Evaluation lifecycle shortcuts ────────────────────────────────

def open_evaluation(unit_id: str, route_id: str, kind: str = "MINI_SURVEY",
                    count_week_start: str = "2026-09-19") -> dict:
    """Create an evaluation on a route (reads the live route version first).

    Returns the created evaluation. Route must be STANDARD with no open
    evaluation.
    """
    route = get_route(unit_id, route_id)
    return get_success_data(
        _API.create_evaluation(
            unit_id, route_id,
            {"evaluation_kind": kind, "count_week_start": count_week_start,
             "expected_route_version": route["version"]},
            H["supervisor_headers"]))


def evaluation_in_data_collection(ctx: dict = None, kind: str = "MINI_SURVEY",
                                  count_week_start: str = "2026-09-19") -> dict:
    """Unit + route + evaluation walked to DATA_COLLECTION.

    Accepts an optional ctx from setup_route_with_active_points / setup_unit_with_route.
    Returns ctx with an added ``evaluation`` key.
    """
    ctx = ctx or setup_unit_with_route()
    ev = open_evaluation(ctx["unit"]["id"], ctx["route"]["id"], kind=kind,
                         count_week_start=count_week_start)
    get_success_data(
        _API.begin_count(ctx["unit"]["id"], ctx["route"]["id"], ev["id"],
                         H["supervisor_headers"]))
    ctx["evaluation"] = ev
    return ctx


def evaluation_consulted(ctx: dict = None, outcome: str = "CONCURRED",
                         counts: dict = None, kind: str = "MINI_SURVEY") -> dict:
    """Evaluation walked to CONSULTED with the given consultation outcome.

    Returns ctx with ``evaluation`` key (post-submit-counts snapshot; callers
    should re-GET for post-consultation state).
    """
    ctx = evaluation_in_data_collection(ctx, kind=kind)
    ev = ctx["evaluation"]
    payload = submit_counts_payload(**(counts or {}))
    get_success_data(
        _API.submit_counts(ctx["unit"]["id"], ctx["route"]["id"], ev["id"],
                           payload, H["supervisor_headers"]))
    get_success_data(
        _API.record_consultation(ctx["unit"]["id"], ctx["route"]["id"], ev["id"],
                                 {"consultation_outcome": outcome},
                                 H["supervisor_headers"]))
    return ctx


def adjustment_in_state(ctx: dict, state: str = "SUBMITTED",
                        proposed_minutes: int = 545,
                        transfers: list = None,
                        effective_date: str = "2026-09-08",
                        submitter: str = SUPERVISOR_USER_ID,
                        approver: str = POSTMASTER_USER_ID) -> dict:
    """Create an adjustment on ctx's CONSULTED evaluation and walk it to the
    requested state (DRAFT | SUBMITTED | APPROVED).

    Returns ctx with ``adjustment`` key.
    """
    ev = ctx["evaluation"]
    payload = create_adjustment_payload(
        proposed_evaluated_minutes=proposed_minutes,
        points_transferred_out=transfers or [],
        effective_date=effective_date)
    adj = get_success_data(
        _API.create_adjustment(ctx["unit"]["id"], ctx["route"]["id"], ev["id"],
                               payload, H["supervisor_headers"]))
    ctx["adjustment"] = adj
    if state in ("SUBMITTED", "APPROVED"):
        get_success_data(
            _API.submit_adjustment(ctx["unit"]["id"], ctx["route"]["id"], ev["id"],
                                   adj["id"], make_supervisor_headers(submitter)))
    if state == "APPROVED":
        get_success_data(
            _API.approve_adjustment(ctx["unit"]["id"], ctx["route"]["id"], ev["id"],
                                    adj["id"], make_postmaster_headers(approver)))
    return ctx


# ─── Tier 3: Auxiliary lifecycle shortcuts ─────────────────────────────────

def create_auxiliary(unit_id: str, route_id: str, helper_carrier_id: str,
                     service_date: str, projected_overrun_minutes: int,
                     seasonal_surge_flag: bool = False) -> dict:
    return get_success_data(
        _API.create_auxiliary(
            unit_id, route_id,
            create_auxiliary_payload(helper_carrier_id, service_date,
                                     projected_overrun_minutes=projected_overrun_minutes,
                                     seasonal_surge_flag=seasonal_surge_flag),
            H["supervisor_headers"]))


def approve_auxiliary(unit_id: str, route_id: str, aux_id: str) -> dict:
    return get_success_data(
        _API.approve_auxiliary(unit_id, route_id, aux_id, H["postmaster_headers"]))


# ─── Tier 3: COA / hold / inquiry shortcuts ────────────────────────────────

def create_coa(unit_id: str, point_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_coa(unit_id, create_coa_payload(point_id, **overrides),
                        H["csr_headers"]))


def create_hold(unit_id: str, point_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_hold(unit_id, create_hold_payload(point_id, **overrides),
                         H["csr_headers"]))


def create_inquiry(unit_id: str, point_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_inquiry(unit_id, create_inquiry_payload(point_id, **overrides),
                            H["csr_headers"]))


# ─── Scan events ───────────────────────────────────────────────────────────

def record_scan(unit_id: str, route_id: str, point_id: str, carrier_id: str,
                **overrides) -> dict:
    """Record a scan as the given carrier (entity-backed headers)."""
    return get_success_data(
        _API.create_scan_event(unit_id, route_id,
                               create_scan_payload(point_id, carrier_id, **overrides),
                               make_carrier_headers(carrier_id)))
