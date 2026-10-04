"""Entity serializers — derived fields are computed fresh on every read."""

from decimal import Decimal

import db
import calculations as calc
import core

COMMON = ("id", "created_at", "updated_at", "version")

_TIMESTAMP_FIELDS = {
    "created_at", "updated_at", "aep_start_date", "aep_end_date", "posture_since",
    "hire_date", "issued_on", "expires_on", "requested_on", "appointed_on",
    "terminated_on", "certified_on", "date_of_birth", "captured_on",
    "retained_until", "started_at", "scheduled_end_at", "actual_end_at",
    "recording_retained_until", "submitted_on", "acknowledged_on",
    "effectuated_on", "effective_date", "disenrollment_date", "posted_on",
    "filed_on", "substantiated_on", "assigned_on", "due_on", "completed_on",
    "last_attested_on",
}

_DECIMAL_FIELDS = {
    "substantiated_complaint_rate", "loss_ratio", "compliance_risk_score",
    "provisional_commission_cents", "final_commission_cents", "amount_cents",
    "internal_total_cents", "variance_cents", "commission_balance_cents",
}

_NAMES = {
    "Agency": "agencies", "Carrier": "carriers", "Agent": "agents",
    "AgentStateLicense": "state_licenses", "CarrierAppointment": "appointments",
    "CarrierCertification": "certifications", "Member": "members",
    "ScopeOfAppointment": "scopes", "CallSession": "call_sessions",
    "Plan": "plans", "FormularyDrug": "formulary_drugs",
    "PharmacyNetworkEntry": "pharmacy_entries", "ProviderDirectoryEntry": "provider_entries",
    "Enrollment": "enrollments", "CommissionLedgerEntry": "ledger_entries",
    "CarrierReconciliation": "reconciliations", "Complaint": "complaints",
    "CoachingAssignment": "coaching",
}


def _base(row, common=True):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if key in _TIMESTAMP_FIELDS:
            out[key] = db.iso(value)
        elif key in _DECIMAL_FIELDS:
            out[key] = calc.num(value)
        elif isinstance(value, Decimal):
            # PRD §2.11: the two rate inputs are "decimal fractions" and preserve
            # the precision with which they were supplied, so they are emitted as
            # JSON numbers rather than strings.
            out[key] = float(value)
        else:
            out[key] = value
    if not common:
        out.pop("updated_at", None)
        out.pop("version", None)
    return out


def serialize(entity_name, row):
    if row is None:
        return None
    common = entity_name != "PharmacyNetworkEntry"
    out = _base(row, common)

    if entity_name == "Agency":
        out["compliance_posture"] = row["compliance_posture"]
    elif entity_name == "AgentStateLicense":
        out["license_status"] = core.license_status(row)
    elif entity_name == "ScopeOfAppointment":
        out["expires_on"] = db.iso(core.scope_expires_on(row))
        out["retained_until"] = db.iso(core.scope_retained_until(row))
    elif entity_name == "CallSession":
        out["recording_retained_until"] = db.iso(core.recording_retained_until(row))
        out["recording_status"] = core.recording_status(row)
    elif entity_name == "Enrollment":
        out["disenrolled_day_number"] = core.disenrolled_day_number(row)
        agency = db.agencies.get(row["agency_id"])
        rapid = core.is_rapid(row, agency) if agency else None
        # PRD §3.6: before any disenrollment the flag "stays unset" — reported as
        # the boolean false, so the field is always a boolean on the wire.
        out["is_rapid_disenrollment"] = bool(rapid)
    elif entity_name == "CoachingAssignment":
        out["overdue_days"] = core.coaching_overdue_days(row)
    elif entity_name == "CarrierReconciliation":
        out["variance_variant"] = row.get("internal_total_variant", "PROVISIONAL")
    return out


def get(entity_name, entity_id):
    return db.__dict__[_NAMES[entity_name]].get(entity_id)


def listing(entity_name, rows):
    return [serialize(entity_name, row) for row in rows]