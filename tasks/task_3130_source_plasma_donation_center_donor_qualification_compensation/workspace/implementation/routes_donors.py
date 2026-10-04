"""Routes: Donor registration, reads, deferral registry."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import db
import errors
import middleware
import response
import services as svc

bp = Blueprint("donors", __name__)


def _require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.err_invalid_request(f"{field} must be a non-empty string")
    return val


# ---------------------------------------------------------------------------
# Donor
# ---------------------------------------------------------------------------
@bp.post("/donors")
def register_donor():
    middleware.require_roles("Recorder")
    body = middleware.get_body()
    external_donor_ref = _require_str(body, "external_donor_ref")
    legal_first_name = _require_str(body, "legal_first_name")
    legal_last_name = _require_str(body, "legal_last_name")
    date_of_birth_raw = body.get("date_of_birth")
    dob = db.parse_date(date_of_birth_raw)
    if dob is None:
        raise errors.err_invalid_request("date_of_birth must be an ISO 8601 date (YYYY-MM-DD)")
    weight_kg = body.get("weight_kg")
    if not isinstance(weight_kg, (int, float)) or isinstance(weight_kg, bool):
        raise errors.err_invalid_request("weight_kg must be a number")
    home_center_id = body.get("home_center_id")
    if not isinstance(home_center_id, str) or home_center_id == "":
        raise errors.err_invalid_request("home_center_id must be a non-empty string")
    with db.lock():
        center = svc.get_center(home_center_id)
        if center is None:
            raise errors.err_not_found("home_center_id does not resolve")
        # Age >= 18 evaluated against the logical clock (never wall time).
        now = db.now()
        try:
            eighteenth = dob.replace(year=dob.year + 18)
        except ValueError:
            eighteenth = dob.replace(year=dob.year + 18, day=28)
        eighteenth_dt = datetime(
            eighteenth.year, eighteenth.month, eighteenth.day, tzinfo=timezone.utc
        )
        if now < eighteenth_dt:
            raise errors.err_invalid_request("donor must be at least 18 years old at registration")
        for d in db.DB["donors"].values():
            if d["external_donor_ref"] == external_donor_ref:
                raise errors.err_duplicate_donor()
        donor = {
            "id": db.next_id(),
            "external_donor_ref": external_donor_ref,
            "legal_first_name": legal_first_name,
            "legal_last_name": legal_last_name,
            "date_of_birth": date_of_birth_raw,
            "weight_kg": weight_kg,
            "home_center_id": home_center_id,
            "donor_status": "APPLICANT",
            "applicant_window_started_on": None,
            "deferral_ends_on": None,
            "deferred_reason_code": None,
            "lifetime_donation_count": 0,
            "ytd_compensation_cents": 0,
            "requires_1099": False,
            "active_deferral_id": None,
        }
        db.stamp_new(donor)
        db.DB["donors"][donor["id"]] = donor
    return response.success_object(svc.donor_view(donor), status=201)


@bp.get("/donors")
def list_donors():
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Phlebotomist", "Recorder"
    )
    limit, offset = response.parse_pagination(request.args)
    donor_status = request.args.get("donor_status")
    home_center_id = request.args.get("home_center_id")
    external_donor_ref = request.args.get("external_donor_ref")
    items = list(db.DB["donors"].values())
    if donor_status is not None:
        items = [d for d in items if d["donor_status"] == donor_status]
    if home_center_id is not None:
        items = [d for d in items if d["home_center_id"] == home_center_id]
    if external_donor_ref is not None:
        items = [d for d in items if d["external_donor_ref"] == external_donor_ref]
    items.sort(key=lambda d: d["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list([svc.donor_view(d) for d in page], limit, offset, total)


@bp.get("/donors/<donor_id>")
def get_donor(donor_id):
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Phlebotomist", "Recorder"
    )
    donor = svc.get_donor_or_404(donor_id)
    return response.success_object(svc.donor_view(donor))


# ---------------------------------------------------------------------------
# Deferrals
# ---------------------------------------------------------------------------
@bp.post("/donors/<donor_id>/deferrals")
def file_deferral(donor_id):
    ctx = middleware.require_roles("ComplianceOfficer")
    donor = svc.get_donor_or_404(donor_id)
    body = middleware.get_body()
    reason_code = _require_str(body, "reason_code")
    deferral_type = body.get("deferral_type")
    if deferral_type not in ("TEMPORARY", "PERMANENT"):
        raise errors.err_invalid_request("deferral_type must be TEMPORARY or PERMANENT")
    deferral_ends_raw = body.get("deferral_ends_on")
    if deferral_type == "TEMPORARY":
        ends = db.parse_dt(deferral_ends_raw)
        if ends is None:
            raise errors.err_invalid_request(
                "deferral_ends_on is required for TEMPORARY deferrals and must be an ISO 8601 datetime"
            )
        if ends <= db.now():
            raise errors.err_invalid_request(
                "deferral_ends_on must be later than the entry's created_at"
            )
        ends_str = db.ts(ends)
    else:
        ends_str = None
    with db.lock():
        if donor["donor_status"] not in ("APPLICANT", "QUALIFIED"):
            raise errors.err_donor_not_deferrable()
        if svc.active_deferral_for(donor["id"]) is not None:
            raise errors.err_active_deferral_exists()
        entry = {
            "id": db.next_id(),
            "donor_id": donor["id"],
            "reason_code": reason_code,
            "deferral_type": deferral_type,
            "deferral_ends_on": ends_str,
            "source_center_id": donor["home_center_id"],
            "filed_by_user_id": ctx.user_id,
            "registry_status": "ACTIVE",
            "override_rationale": None,
        }
        db.stamp_new(entry)
        db.DB["deferral_registry_entries"][entry["id"]] = entry

        if deferral_type == "TEMPORARY":
            donor["donor_status"] = "DEFERRED_TEMP"
            donor["deferral_ends_on"] = ends_str
        else:
            donor["donor_status"] = "DEFERRED_PERM"
            donor["deferral_ends_on"] = None
        donor["active_deferral_id"] = entry["id"]
        donor["deferred_reason_code"] = reason_code
        db.touch(donor)

        if deferral_type == "TEMPORARY":
            svc.move_scheduled_visits_to_no_show(donor_id=donor["id"])
        else:
            quarantined = [
                u for u in db.DB["donation_units"].values()
                if u["donor_id"] == donor["id"] and u["unit_status"] == "QUARANTINED"
            ]
            held = [
                u for u in db.DB["donation_units"].values()
                if u["donor_id"] == donor["id"] and u["unit_status"] == "LOOKBACK_HOLD"
            ]
            svc.destroy_units(quarantined, "DONOR_PERMANENT_DEFERRAL")
            svc.destroy_units(held, "DONOR_PERMANENT_DEFERRAL")
            svc.resolve_cases_after_mass_destroy(donor["id"])
    return response.success_object(svc.deferral_view(entry), status=201)


@bp.get("/donors/<donor_id>/deferrals")
def list_deferrals(donor_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer", "MedicalScreener")
    svc.get_donor_or_404(donor_id)
    limit, offset = response.parse_pagination(request.args)
    registry_status = request.args.get("registry_status")
    items = [
        e for e in db.DB["deferral_registry_entries"].values() if e["donor_id"] == donor_id
    ]
    if registry_status is not None:
        items = [e for e in items if e["registry_status"] == registry_status]
    items.sort(key=lambda e: e["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list([svc.deferral_view(e) for e in page], limit, offset, total)


@bp.post("/deferral-registry-entries/<entry_id>/override")
def override_deferral(entry_id):
    middleware.require_roles("ComplianceOfficer")
    entry = svc.get_deferral_entry_or_404(entry_id)
    body = middleware.get_body()
    rationale = body.get("override_rationale")
    if not isinstance(rationale, str) or len(rationale) < 20:
        raise errors.err_invalid_request("override_rationale must be at least 20 characters")
    with db.lock():
        if entry["registry_status"] != "ACTIVE":
            raise errors.err_invalid_state("deferral entry is not ACTIVE")
        entry["registry_status"] = "OVERRIDDEN"
        entry["override_rationale"] = rationale
        db.touch(entry)
        donor = db.DB["donors"].get(entry["donor_id"])
        if donor is not None and donor.get("active_deferral_id") == entry["id"]:
            donor["active_deferral_id"] = None
            donor["deferral_ends_on"] = None
            donor["deferred_reason_code"] = None
            donor["donor_status"] = (
                "APPLICANT" if donor["lifetime_donation_count"] == 0 else "QUALIFIED"
            )
            db.touch(donor)
    return response.success_object(svc.deferral_view(entry))


# ---------------------------------------------------------------------------
# Compensation payments under a donor
# ---------------------------------------------------------------------------
@bp.get("/donors/<donor_id>/compensation-payments")
def list_donor_payments(donor_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer")
    svc.get_donor_or_404(donor_id)
    limit, offset = response.parse_pagination(request.args)
    payment_status = request.args.get("payment_status")
    schedule_id = request.args.get("schedule_id")
    items = [
        p for p in db.DB["compensation_payments"].values() if p["donor_id"] == donor_id
    ]
    if payment_status is not None:
        items = [p for p in items if p["payment_status"] == payment_status]
    if schedule_id is not None:
        items = [p for p in items if p["schedule_id"] == schedule_id]
    items.sort(key=lambda p: p["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list([svc.payment_view(p) for p in page], limit, offset, total)
