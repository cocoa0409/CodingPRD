"""In-memory data store for DispatchHealth. Store starts empty on every boot."""
import threading

_lock = threading.RLock()

# Logical clock: starts at 2026-09-01T00:00:00Z before any interaction.
from datetime import datetime, timezone

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

_markets = {}
_payer_contracts = {}
_formulary_entries = {}
_patients = {}
_care_teams = {}
_vehicle_shifts = {}
_visit_requests = {}
_triage_assessments = {}
_ems_handoffs = {}
_dispatch_assignments = {}
_encounters = {}
_diagnostic_orders = {}
_disposition_decisions = {}
_facility_transports = {}
_claims = {}
_claim_lines = {}
_follow_up_notices = {}
_monitoring_checkins = {}

_clock = {"current_utc": CLOCK_DEFAULT}

STORES = {
    "markets": _markets,
    "payer_contracts": _payer_contracts,
    "formulary_entries": _formulary_entries,
    "patients": _patients,
    "care_teams": _care_teams,
    "vehicle_shifts": _vehicle_shifts,
    "visit_requests": _visit_requests,
    "triage_assessments": _triage_assessments,
    "ems_handoffs": _ems_handoffs,
    "dispatch_assignments": _dispatch_assignments,
    "encounters": _encounters,
    "diagnostic_orders": _diagnostic_orders,
    "disposition_decisions": _disposition_decisions,
    "facility_transports": _facility_transports,
    "claims": _claims,
    "claim_lines": _claim_lines,
    "follow_up_notices": _follow_up_notices,
    "monitoring_checkins": _monitoring_checkins,
}


def lock():
    return _lock


def get_clock():
    with _lock:
        return _clock["current_utc"]


def set_clock(value):
    with _lock:
        _clock["current_utc"] = value
    return value
