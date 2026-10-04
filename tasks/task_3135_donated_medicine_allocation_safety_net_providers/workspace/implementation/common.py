"""Shared store, logical clock, envelope, auth, pagination, and business helpers."""
import re
import uuid
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; no seeding)
# ---------------------------------------------------------------------------
LOCK = threading.RLock()

DONORS = {}
LOTS = {}
SITES = {}
LICENSES = {}
REQUESTS = {}
DECISIONS = {}
LINES = {}
SHIPMENTS = {}
CUSTOMS = {}
EVENTS = {}
MODULES = {}
SNAPSHOTS = {}
REPORTS = {}

_SEQ = [0]

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK = [datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)]


def clock():
    return _CLOCK[0]


def set_clock(dt):
    _CLOCK[0] = dt


def now_wall():
    return datetime.now(timezone.utc)


def fmt_wall(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_business(dt):
    """Logical-clock timestamps: no fraction when zero, else 3 fractional digits."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_wall(dt)


def parse_dt(value):
    """Parse an ISO date or datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Expected an ISO8601 date/datetime string")
    s = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Malformed datetime: {value!r}")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def ok(data, status=200):
    body = {
        "meta": {
            "api_request_id": err_request_id(),
            "api_request_timestamp": fmt_wall(now_wall()),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items):
    """items: full (already serialized) list; pagination applied here."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": err_request_id(),
            "api_request_timestamp": fmt_wall(now_wall()),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        },
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": {
            "api_request_id": err_request_id(),
            "api_request_timestamp": fmt_wall(now_wall()),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
ROLES = {
    "PlatformAdmin", "QAPharmacist", "ComplianceOfficer", "AllocationOfficer",
    "LogisticsCoordinator", "SiteCoordinator", "EmergencyManager",
    "DonorReportingOfficer",
}


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-ID header missing or malformed")
    if not role or not isinstance(role, str) or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role header missing or malformed")
    return uid.strip(), role.strip()


def require_roles(*roles):
    uid, role = auth_context()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, f"Role {role} is not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Body field helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def req_field(b, name):
    if name not in b or b[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
    return b[name]


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a non-empty string")
    return v


def opt_str(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a string")
    return v


def req_int(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an integer")
    return v


def req_bool(b, name):
    v = req_field(b, name)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a boolean")
    return v


def req_num(b, name):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a number")
    return v


def req_list(b, name):
    v = req_field(b, name)
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an array")
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    entity["id"] = new_id()
    entity["created_at"] = now_wall()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = _SEQ[0]
    _SEQ[0] += 1
    return entity


def bump(entity):
    entity["version"] += 1
    entity["updated_at"] = now_wall()


def base_json(e):
    return {
        "id": e["id"],
        "created_at": fmt_wall(e["created_at"]),
        "updated_at": fmt_wall(e["updated_at"]),
        "version": e["version"],
    }


def sorted_items(store):
    return sorted(store.values(), key=lambda e: e["_seq"])


def get_or_404(store, entity_id, label="Resource"):
    e = store.get(entity_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found: {entity_id}")
    return e


def money2(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
def lot_available(lot):
    return (lot["quantity_received"] - lot["quantity_quarantined"]
            - lot["quantity_committed"] - lot["quantity_shipped"]
            - lot["quantity_expired"])


def site_active_license_count(site_id):
    now = clock()
    return sum(
        1 for lic in LICENSES.values()
        if lic["site_id"] == site_id
        and lic["verification_status"] == "VERIFIED"
        and parse_dt(lic["expires_on_raw"]) > now
    )


def site_json(site):
    d = base_json(site)
    d.update({
        "organization_name": site["organization_name"],
        "site_type": site["site_type"],
        "country_code": site["country_code"],
        "is_international": site["country_code"] != "US",
        "cold_storage_capacity_l": site["cold_storage_capacity_l"],
        "has_dea_registration": site["has_dea_registration"],
        "monthly_patient_volume": site["monthly_patient_volume"],
        "underserved_index": site["underserved_index"],
        "qualification_status": site["qualification_status"],
        "qualified_at": fmt_business(site["qualified_at"]) if site["qualified_at"] else None,
        "active_license_count": site_active_license_count(site["id"]),
    })
    return d


def donor_json(donor):
    d = base_json(donor)
    d.update({
        "legal_name": donor["legal_name"],
        "country_code": donor["country_code"],
        "dea_registration_no": donor["dea_registration_no"],
        "tax_id": donor["tax_id"],
        "status": donor["status"],
    })
    return d


def lot_json(lot):
    d = base_json(lot)
    d.update({
        "donor_id": lot["donor_id"],
        "ndc_code": lot["ndc_code"],
        "product_name": lot["product_name"],
        "product_class": lot["product_class"],
        "dosage_form": lot["dosage_form"],
        "unit_of_measure": lot["unit_of_measure"],
        "quantity_received": lot["quantity_received"],
        "quantity_available": lot_available(lot),
        "quantity_quarantined": lot["quantity_quarantined"],
        "quantity_committed": lot["quantity_committed"],
        "quantity_shipped": lot["quantity_shipped"],
        "quantity_expired": lot["quantity_expired"],
        "expiration_date": lot["expiration_date"],
        "storage_temp_min_c": lot["storage_temp_min_c"],
        "storage_temp_max_c": lot["storage_temp_max_c"],
        "restricted_use_conditions": lot["restricted_use_conditions"],
        "requires_cold_chain": lot["product_class"] == "COLD_CHAIN",
        "is_controlled": lot["product_class"] == "CONTROLLED",
        "unit_acquisition_value_usd": lot["unit_acquisition_value_usd"],
        "unit_wholesale_value_usd": lot["unit_wholesale_value_usd"],
        "lot_posture": lot["lot_posture"],
        "intake_recorded_at": fmt_business(lot["intake_recorded_at"]),
    })
    return d


def license_json(lic):
    d = base_json(lic)
    d.update({
        "site_id": lic["site_id"],
        "license_type": lic["license_type"],
        "issuing_authority": lic["issuing_authority"],
        "license_number": lic["license_number"],
        "expires_on": lic["expires_on"],
        "verification_status": lic["verification_status"],
    })
    return d


def request_json(req):
    d = base_json(req)
    d.update({
        "site_id": req["site_id"],
        "requested_by_user_id": req["requested_by_user_id"],
        "ndc_code": req["ndc_code"],
        "quantity_requested": req["quantity_requested"],
        "justification_text": req["justification_text"],
        "emergency_event_id": req["emergency_event_id"],
        "status": req["status"],
        "need_score": req["need_score"],
        "quantity_approved": req["quantity_approved"],
    })
    return d


def line_json(line):
    d = base_json(line)
    d.update({
        "decision_id": line["decision_id"],
        "lot_id": line["lot_id"],
        "quantity": line["quantity"],
        "status": line["status"],
        "reservation_expires_at": fmt_business(line["reservation_expires_at"]) if line["reservation_expires_at"] else None,
    })
    return d


def decision_json(dec, include_lines=True):
    d = base_json(dec)
    d.update({
        "request_id": dec["request_id"],
        "reviewer_user_id": dec["reviewer_user_id"],
        "decided_at": fmt_business(dec["decided_at"]) if dec["decided_at"] else None,
        "rationale": dec["rationale"],
        "status": dec["status"],
    })
    if include_lines:
        lines = [line_json(l) for l in sorted_items(LINES) if l["decision_id"] == dec["id"]]
        d["lines"] = lines
    return d


def decision_lines(dec_id):
    return [l for l in LINES.values() if l["decision_id"] == dec_id]


def shipment_json(sh):
    d = base_json(sh)
    d.update({
        "site_id": sh["site_id"],
        "allocation_decision_id": sh["allocation_decision_id"],
        "carrier_name": sh["carrier_name"],
        "is_international": sh["is_international"],
        "requires_cold_chain": sh["requires_cold_chain"],
        "temperature_band_min_c": sh["temperature_band_min_c"],
        "temperature_band_max_c": sh["temperature_band_max_c"],
        "packed_with_cold_shipper": sh["packed_with_cold_shipper"],
        "customs_declaration_id": sh["customs_declaration_id"],
        "status": sh["status"],
        "dispatched_at": fmt_business(sh["dispatched_at"]) if sh["dispatched_at"] else None,
        "delivered_at": fmt_business(sh["delivered_at"]) if sh["delivered_at"] else None,
    })
    return d


def customs_json(cd):
    d = base_json(cd)
    d.update({
        "shipment_id": cd["shipment_id"],
        "hs_code": cd["hs_code"],
        "declared_value_usd": cd["declared_value_usd"],
        "import_license_id": cd["import_license_id"],
        "destination_country_code": cd["destination_country_code"],
        "status": cd["status"],
    })
    return d


def event_json(ev):
    d = base_json(ev)
    d.update({
        "event_name": ev["event_name"],
        "severity": ev["severity"],
        "affected_country_codes": ev["affected_country_codes"],
        "declared_at": fmt_business(ev["declared_at"]),
        "surge_window_ends_at": fmt_business(ev["surge_window_ends_at"]) if ev["surge_window_ends_at"] else None,
        "status": ev["status"],
    })
    return d


def module_json(mod):
    d = base_json(mod)
    d.update({
        "module_code": mod["module_code"],
        "intended_use": mod["intended_use"],
        "holding_country_code": mod["holding_country_code"],
        "quantity_on_hand": mod["quantity_on_hand"],
        "reserved_for_event_id": mod["reserved_for_event_id"],
        "status": mod["status"],
    })
    return d


def snapshot_json(snap):
    d = base_json(snap)
    d.update({
        "snapshot_period": snap["snapshot_period"],
        "donor_id": snap["donor_id"],
        "method": snap["method"],
        "total_value_usd": snap["total_value_usd"],
        "lot_count": snap["lot_count"],
        "generated_at": fmt_business(snap["generated_at"]),
    })
    return d


def report_json(rep):
    d = base_json(rep)
    d.update({
        "site_id": rep["site_id"],
        "shipment_id": rep["shipment_id"],
        "reporting_period": rep["reporting_period"],
        "units_distributed": rep["units_distributed"],
        "patients_reached": rep["patients_reached"],
        "wastage_units": rep["wastage_units"],
        "submitted_by_user_id": rep["submitted_by_user_id"],
        "status": rep["status"],
        "reviewed_by_user_id": rep["reviewed_by_user_id"],
    })
    return d


# ---------------------------------------------------------------------------
# Cascades / shared business operations
# ---------------------------------------------------------------------------
def finalized_decision_for(request_id):
    for dec in DECISIONS.values():
        if dec["request_id"] == request_id and dec["status"] == "FINALIZED":
            return dec
    return None


def recompute_request_approved(req):
    """Recompute quantity_approved from the FINALIZED decision's active lines;
    if it drops to 0 on an approved request, the request is REJECTED."""
    dec = finalized_decision_for(req["id"])
    total = 0
    if dec is not None:
        for line in decision_lines(dec["id"]):
            if line["status"] in ("RESERVED", "PICKED", "SHIPPED", "DELIVERED"):
                total += line["quantity"]
    req["quantity_approved"] = total
    if total == 0 and req["status"] in ("APPROVED", "PARTIALLY_APPROVED"):
        req["status"] = "REJECTED"
        bump(req)


def release_line(line):
    """RESERVED -> RELEASED, freeing the lot's committed quantity."""
    lot = LOTS.get(line["lot_id"])
    line["status"] = "RELEASED"
    bump(line)
    if lot is not None:
        lot["quantity_committed"] -= line["quantity"]
        bump(lot)


def forfeit_line(line):
    """RESERVED -> FORFEITED; quantity returns to available; request reconciles."""
    lot = LOTS.get(line["lot_id"])
    line["status"] = "FORFEITED"
    bump(line)
    if lot is not None:
        lot["quantity_committed"] -= line["quantity"]
        bump(lot)
    dec = DECISIONS.get(line["decision_id"])
    if dec is not None:
        req = REQUESTS.get(dec["request_id"])
        if req is not None:
            recompute_request_approved(req)


def site_lines(site_id, statuses):
    """Allocation lines belonging (via decision -> request) to a site."""
    out = []
    for line in LINES.values():
        if line["status"] not in statuses:
            continue
        dec = DECISIONS.get(line["decision_id"])
        if dec is None:
            continue
        req = REQUESTS.get(dec["request_id"])
        if req is not None and req["site_id"] == site_id:
            out.append(line)
    return out


def cancel_shipment(sh, recalled_lot_ids=None):
    """Cancel a pre-dispatch shipment; PICKED lines return to RESERVED unless
    their lot was recalled (those lines are RELEASED instead)."""
    recalled_lot_ids = recalled_lot_ids or set()
    dec = DECISIONS.get(sh["allocation_decision_id"])
    if dec is not None:
        for line in decision_lines(dec["id"]):
            if line["status"] != "PICKED":
                continue
            lot = LOTS.get(line["lot_id"])
            if line["lot_id"] in recalled_lot_ids:
                line["status"] = "RELEASED"
                bump(line)
            else:
                line["status"] = "RESERVED"
                bump(line)
                if lot is not None:
                    lot["quantity_committed"] += line["quantity"]
                    bump(lot)
    sh["status"] = "CANCELLED"
    bump(sh)


def suspend_site_cascade(site):
    """Shared cascade for suspension / revocation / auto-suspension."""
    for req in REQUESTS.values():
        if req["site_id"] == site["id"] and req["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            req["status"] = "CANCELLED"
            bump(req)
    for line in site_lines(site["id"], ("RESERVED",)):
        release_line(line)


def auto_suspend_if_license_lapse(site):
    if site["qualification_status"] == "QUALIFIED" and site_active_license_count(site["id"]) == 0:
        site["qualification_status"] = "SUSPENDED"
        bump(site)
        suspend_site_cascade(site)


# ---------------------------------------------------------------------------
# Expiry sweep (triggered by logical-clock advancement)
# ---------------------------------------------------------------------------
def run_sweep():
    now = clock()

    # 1. Lot expiry
    for lot in list(LOTS.values()):
        if lot["lot_posture"] not in ("RELEASABLE", "QUARANTINED"):
            continue
        if now < parse_dt(lot["expiration_date_raw"]):
            continue
        if lot["lot_posture"] == "QUARANTINED":
            lot["quantity_expired"] += lot["quantity_quarantined"]
            lot["quantity_quarantined"] = 0
            lot["lot_posture"] = "EXPIRED"
            bump(lot)
        else:  # RELEASABLE
            unshipped = lot["quantity_received"] - lot["quantity_shipped"] - lot["quantity_expired"]
            if unshipped <= 0:
                continue
            for line in [l for l in LINES.values()
                         if l["lot_id"] == lot["id"] and l["status"] == "RESERVED"]:
                forfeit_line(line)
            lot["quantity_expired"] += lot_available(lot)
            lot["lot_posture"] = "EXPIRED"
            bump(lot)

    # 2. License expiry
    affected_sites = set()
    for lic in list(LICENSES.values()):
        if lic["verification_status"] == "VERIFIED" and now >= parse_dt(lic["expires_on_raw"]):
            lic["verification_status"] = "EXPIRED"
            bump(lic)
            affected_sites.add(lic["site_id"])
    for site_id in affected_sites:
        site = SITES.get(site_id)
        if site is not None:
            auto_suspend_if_license_lapse(site)

    # 3. Reservation forfeits
    for line in list(LINES.values()):
        if line["status"] == "RESERVED" and line["reservation_expires_at"] is not None \
                and now >= line["reservation_expires_at"]:
            forfeit_line(line)

    # 4. Emergency stand-down
    for ev in list(EVENTS.values()):
        if ev["status"] == "ACTIVE" and ev["surge_window_ends_at"] is not None \
                and now >= ev["surge_window_ends_at"]:
            ev["status"] = "STAND_DOWN"
            bump(ev)
            for mod in MODULES.values():
                if mod["status"] == "RESERVED" and mod["reserved_for_event_id"] == ev["id"]:
                    mod["status"] = "AVAILABLE"
                    mod["reserved_for_event_id"] = None
                    bump(mod)
