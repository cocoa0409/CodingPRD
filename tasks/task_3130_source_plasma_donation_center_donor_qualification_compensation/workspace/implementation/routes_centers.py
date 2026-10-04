"""Routes: logical clock, PlasmaCenter lifecycle, CompensationSchedule."""
from flask import Blueprint, request

import db
import errors
import middleware
import response
import services as svc

bp = Blueprint("centers", __name__)


def _require_int(body, field):
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise errors.err_invalid_request(f"{field} must be an integer")
    return val


def _require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.err_invalid_request(f"{field} must be a non-empty string")
    return val


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    middleware.require_roles("PlatformAdmin")
    body = middleware.get_body()
    current_utc = body.get("current_utc")
    new_dt = db.parse_dt(current_utc)
    if new_dt is None:
        raise errors.err_invalid_request("current_utc must be an ISO 8601 datetime")
    with db.lock():
        db.set_clock(new_dt)
        svc.run_scheduled_transitions()
    return response.success_object({"current_utc": db.ts(new_dt)})


# ---------------------------------------------------------------------------
# PlasmaCenter
# ---------------------------------------------------------------------------
@bp.post("/plasma-centers")
def create_center():
    middleware.require_roles("PlatformAdmin")
    body = middleware.get_body()
    center_code = _require_str(body, "center_code")
    legal_name = _require_str(body, "legal_name")
    state_code = _require_str(body, "state_code")
    screening_lanes = _require_int(body, "screening_lanes")
    donor_floor_beds = _require_int(body, "donor_floor_beds")
    observation_chairs = _require_int(body, "observation_chairs")
    if len(state_code) != 2:
        raise errors.err_invalid_request("state_code must be a two-letter code")
    if screening_lanes < 1:
        raise errors.err_invalid_request("screening_lanes must be >= 1")
    if donor_floor_beds < 1:
        raise errors.err_invalid_request("donor_floor_beds must be >= 1")
    if observation_chairs < 1:
        raise errors.err_invalid_request("observation_chairs must be >= 1")
    with db.lock():
        for c in db.DB["plasma_centers"].values():
            if c["center_code"] == center_code:
                raise errors.err_invalid_request("center_code must be globally unique")
        center = {
            "id": db.next_id(),
            "center_code": center_code,
            "legal_name": legal_name,
            "state_code": state_code,
            "screening_lanes": screening_lanes,
            "donor_floor_beds": donor_floor_beds,
            "observation_chairs": observation_chairs,
            "status": "OPERATIONAL",
        }
        db.stamp_new(center)
        db.DB["plasma_centers"][center["id"]] = center
    return response.success_object(svc.center_view(center), status=201)


@bp.get("/plasma-centers")
def list_centers():
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Phlebotomist", "Recorder"
    )
    limit, offset = response.parse_pagination(request.args)
    state_code = request.args.get("state_code")
    items = list(db.DB["plasma_centers"].values())
    if state_code is not None:
        items = [c for c in items if c["state_code"] == state_code]
    items.sort(key=lambda c: c["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list([svc.center_view(c) for c in page], limit, offset, total)


@bp.get("/plasma-centers/<center_id>")
def get_center(center_id):
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Phlebotomist", "Recorder"
    )
    center = svc.get_center_or_404(center_id)
    return response.success_object(svc.center_view(center))


@bp.post("/plasma-centers/<center_id>/inspection-holds")
def place_inspection_hold(center_id):
    middleware.require_roles("ComplianceOfficer")
    center = svc.get_center_or_404(center_id)
    body = middleware.get_body()
    expected = body.get("expected_center_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_center_version must be an integer")
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise errors.err_invalid_request("reason must be a string")
    with db.lock():
        # OCC check before business rules (priority 5 before 6/7).
        if expected != center["version"]:
            raise errors.err_stale_version()
        if center["status"] != "OPERATIONAL":
            raise errors.err_center_not_operational()
        center["status"] = "INSPECTION_HOLD"
        db.touch(center)
        svc.move_scheduled_visits_to_no_show(center_id=center["id"])
        svc.expire_scheduled_screenings(center_id=center["id"])
        svc.write_snapshot(center["id"], "center.inspection_hold")
    return response.success_object(svc.center_view(center))


@bp.post("/plasma-centers/<center_id>/inspection-holds/clear")
def clear_inspection_hold(center_id):
    middleware.require_roles("ComplianceOfficer")
    center = svc.get_center_or_404(center_id)
    body = middleware.get_body()
    expected = body.get("expected_center_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_center_version must be an integer")
    with db.lock():
        if expected != center["version"]:
            raise errors.err_stale_version()
        if center["status"] != "INSPECTION_HOLD":
            raise errors.err_center_not_on_hold()
        center["status"] = "OPERATIONAL"
        db.touch(center)
        svc.write_snapshot(center["id"], "center.inspection_hold_cleared")
    return response.success_object(svc.center_view(center))


@bp.post("/plasma-centers/<center_id>/decommission")
def decommission_center(center_id):
    middleware.require_roles("PlatformAdmin")
    center = svc.get_center_or_404(center_id)
    body = middleware.get_body()
    expected = body.get("expected_center_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_center_version must be an integer")
    with db.lock():
        if expected != center["version"]:
            raise errors.err_stale_version()
        if center["status"] != "OPERATIONAL":
            raise errors.err_center_not_operational()
        active_donations = [
            v for v in db.DB["donation_visits"].values()
            if v["center_id"] == center["id"]
            and v["visit_status"] in ("SCHEDULED", "IN_PROGRESS", "OBSERVATION")
        ]
        active_screenings = [
            v for v in db.DB["screening_visits"].values()
            if v["center_id"] == center["id"]
            and v["visit_status"] in ("SCHEDULED", "IN_PROGRESS")
        ]
        if active_donations or active_screenings:
            raise errors.err_center_has_active_visits()
        center["status"] = "DECOMMISSIONED"
        db.touch(center)
        quarantined = [
            u for u in db.DB["donation_units"].values()
            if u["center_id"] == center["id"] and u["unit_status"] == "QUARANTINED"
        ]
        svc.destroy_units(quarantined, "EXPIRED_HOLD")
    return response.success_object(svc.center_view(center))


@bp.get("/plasma-centers/<center_id>/capacity-snapshots")
def list_capacity_snapshots(center_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer")
    svc.get_center_or_404(center_id)
    limit, offset = response.parse_pagination(request.args)
    items = [
        s for s in db.DB["capacity_snapshots"].values() if s["center_id"] == center_id
    ]
    # Newest first; stable secondary ordering on creation instant, then id.
    items.sort(key=lambda s: (s["snapshot_at"], s["created_at"], s["id"]), reverse=True)
    page, total = response.paginate(items, limit, offset)
    return response.success_list([svc.snapshot_view(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# CompensationSchedule
# ---------------------------------------------------------------------------
@bp.post("/plasma-centers/<center_id>/compensation-schedules")
def create_schedule(center_id):
    middleware.require_roles("PlatformAdmin")
    center = svc.get_center_or_404(center_id)
    body = middleware.get_body()
    effective_from_raw = body.get("effective_from")
    effective_to_raw = body.get("effective_to")
    ef = db.parse_dt(effective_from_raw)
    et = db.parse_dt(effective_to_raw)
    if ef is None:
        raise errors.err_invalid_request("effective_from must be an ISO 8601 datetime")
    if et is None:
        raise errors.err_invalid_request("effective_to must be an ISO 8601 datetime")
    if et <= ef:
        raise errors.err_invalid_request("effective_to must be later than effective_from")
    base_first = _require_int(body, "base_cents_first_donation")
    base_second = _require_int(body, "base_cents_second_donation")
    base_subsequent = _require_int(body, "base_cents_subsequent_donation")
    promo_code = body.get("promo_code")
    if promo_code is not None and not isinstance(promo_code, str):
        raise errors.err_invalid_request("promo_code must be a string or null")
    promo_bonus = body.get("promo_bonus_cents", 0)
    if not isinstance(promo_bonus, int) or isinstance(promo_bonus, bool):
        raise errors.err_invalid_request("promo_bonus_cents must be an integer")
    promo_qualifying = body.get("promo_qualifying_donation_count", 0)
    if not isinstance(promo_qualifying, int) or isinstance(promo_qualifying, bool):
        raise errors.err_invalid_request("promo_qualifying_donation_count must be an integer")
    expected = body.get("expected_center_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_center_version must be an integer")
    with db.lock():
        # OCC check (priority 5) precedes center-status gating (priority 7).
        if expected != center["version"]:
            raise errors.err_stale_version()
        svc.assert_center_operational(center)
        # Auto-supersede any overlapping ACTIVE schedule.
        for s in db.DB["compensation_schedules"].values():
            if (
                s["center_id"] == center["id"]
                and s["schedule_status"] == "ACTIVE"
                and ef < db.parse_dt(s["effective_to"])
            ):
                s["schedule_status"] = "SUPERSEDED"
                s["effective_to"] = db.ts(ef)
                db.touch(s)
        schedule = {
            "id": db.next_id(),
            "center_id": center["id"],
            "effective_from": db.ts(ef),
            "effective_to": db.ts(et),
            "base_cents_first_donation": base_first,
            "base_cents_second_donation": base_second,
            "base_cents_subsequent_donation": base_subsequent,
            "promo_code": promo_code,
            "promo_bonus_cents": promo_bonus,
            "promo_qualifying_donation_count": promo_qualifying,
            "schedule_status": "ACTIVE",
        }
        db.stamp_new(schedule)
        db.DB["compensation_schedules"][schedule["id"]] = schedule
        # New-schedule creation bumps the parent center's version by 1.
        db.touch(center)
    return response.success_object(svc.schedule_view(schedule), status=201)


@bp.get("/plasma-centers/<center_id>/compensation-schedules")
def list_schedules(center_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer")
    svc.get_center_or_404(center_id)
    limit, offset = response.parse_pagination(request.args)
    schedule_status = request.args.get("schedule_status")
    items = [
        s for s in db.DB["compensation_schedules"].values() if s["center_id"] == center_id
    ]
    if schedule_status is not None:
        items = [s for s in items if s["schedule_status"] == schedule_status]
    items.sort(key=lambda s: s["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list([svc.schedule_view(s) for s in page], limit, offset, total)


@bp.get("/compensation-schedules/<schedule_id>")
def get_schedule(schedule_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer")
    schedule = svc.get_schedule_or_404(schedule_id)
    return response.success_object(svc.schedule_view(schedule))


@bp.post("/compensation-schedules/<schedule_id>/retire")
def retire_schedule(schedule_id):
    middleware.require_roles("PlatformAdmin")
    schedule = svc.get_schedule_or_404(schedule_id)
    body = middleware.get_body()
    expected = body.get("expected_schedule_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_schedule_version must be an integer")
    with db.lock():
        # OCC before state check (priority 5 before 6).
        if expected != schedule["version"]:
            raise errors.err_stale_version()
        if schedule["schedule_status"] != "ACTIVE":
            raise errors.err_schedule_not_active()
        schedule["schedule_status"] = "RETIRED"
        db.touch(schedule)
    return response.success_object(svc.schedule_view(schedule))
