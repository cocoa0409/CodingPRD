"""Resident, Device and data-control endpoints (PRD 3.2)."""
from flask import Blueprint

import auth
import calc
import engine
import envelope
import fetch
import serialize
import store
import validators as v
from errors import ApiError
from store import db, now

bp = Blueprint("resident", __name__)

DEVICE_STATUSES = ("ACTIVE", "OFFLINE", "DECOMMISSIONED")
ACTION_TYPES = ("OPT_OUT_OF_REQUESTS", "OPT_IN_TO_REQUESTS", "PURGE_HISTORY",
                "DEACTIVATE_ACCOUNT")
DISPATCH_KINDS = ("CONSENT_SOLICITATION", "POST_ALERT")


def require_active(resident):
    """Refusal ladder rule 8 -- every Resident-role write endpoint."""
    if resident is not None and resident["status"] != "ACTIVE":
        raise ApiError("ERR_RESIDENT_DEACTIVATED",
                       "Resident %s is deactivated" % resident["id"])


# --------------------------------------------------------------------------
# residents
# --------------------------------------------------------------------------

@bp.post("/neighborhood-safety/residents")
def create_resident():
    auth.authenticate(("Anonymous", "PlatformAdmin"), auth_exempt=True)
    body = v.body_json()
    display_name = v.str_field(body, "display_name", min_len=1, max_len=80)
    email = v.str_field(body, "email", min_len=1)
    home_x = v.coord_field(body, "home_x_m")
    home_y = v.coord_field(body, "home_y_m")
    alert_radius = v.int_field(body, "alert_radius_m", required=False,
                               default=800, lo=0, hi=5000)
    budget = v.int_field(body, "notification_budget_per_day", required=False,
                         default=6, lo=0, hi=100)
    muted = v.bool_field(body, "notification_mute_enabled", required=False,
                         default=False)
    for other in db.residents.values():
        if other["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST",
                           "email must be unique portal-wide")
    row = engine.new_row({
        "display_name": display_name,
        "email": email,
        "home_x_m": home_x,
        "home_y_m": home_y,
        "status": "ACTIVE",
        "data_sharing_opt_out": False,
        "alert_radius_m": alert_radius,
        "notification_budget_per_day": budget,
        "notification_mute_enabled": muted,
        "notifications_sent_today": 0,
        "fatigue_state": "NORMAL",
        "accuracy_strike_count": 0,
        "discrimination_strike_count": 0,
        "total_strike_score": 0,
        "post_privilege_state": "UNRESTRICTED",
        "lifetime_shared_footage_seconds": 0,
        "retained_footage_seconds": 0,
        "purged_footage_seconds": 0,
    })
    db.residents[row["id"]] = row
    return envelope.created(serialize.dump("Resident", row))


@bp.patch("/neighborhood-safety/residents/<resident_id>/alert-settings")
def patch_alert_settings(resident_id):
    actor = auth.authenticate(("Resident",))
    resident = fetch.must("Resident", resident_id)
    body = v.body_json()
    radius = v.int_field(body, "alert_radius_m", required=False,
                         default=None, lo=0, hi=5000)
    budget = v.int_field(body, "notification_budget_per_day", required=False,
                         default=None, lo=0, hi=100)
    muted = v.bool_field(body, "notification_mute_enabled", required=False,
                         default=None)
    auth.require_resident_scope(actor, resident["id"])
    require_active(resident)
    if radius is not None:
        resident["alert_radius_m"] = radius
    if budget is not None:
        resident["notification_budget_per_day"] = budget
    if muted is not None:
        resident["notification_mute_enabled"] = muted
    engine.rederive_fatigue(resident)
    engine.touch(resident)
    return envelope.ok(serialize.dump("Resident", resident))


@bp.get("/neighborhood-safety/residents/<resident_id>")
def read_resident(resident_id):
    auth.authenticate(("PlatformAdmin", "Moderator", "Resident"))
    resident = fetch.must("Resident", resident_id)
    return envelope.ok(serialize.dump("Resident", resident))


@bp.get("/neighborhood-safety/residents/<resident_id>/notification-dispatches")
def list_dispatches(resident_id):
    auth.authenticate(("PlatformAdmin", "Resident"))
    resident = fetch.must("Resident", resident_id)
    limit, offset = v.pagination()
    kind = v.query_enum("kind", DISPATCH_KINDS)
    suppressed = v.query_bool("suppressed")
    rows = [d for d in db.dispatches.values()
            if d["resident_id"] == resident["id"]]
    if kind is not None:
        rows = [d for d in rows if d["kind"] == kind]
    if suppressed is not None:
        rows = [d for d in rows if d["suppressed"] == suppressed]
    rows.sort(key=lambda d: (d["dispatched_at"], d["batch_sequence_no"]))
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(
        serialize.dump_all("NotificationDispatch", page), limit, offset, total)


@bp.get("/neighborhood-safety/residents/<resident_id>/data-control-actions")
def list_data_controls(resident_id):
    auth.authenticate(("PlatformAdmin", "Resident"))
    resident = fetch.must("Resident", resident_id)
    limit, offset = v.pagination()
    action_type = v.query_enum("action_type", ACTION_TYPES)
    rows = [a for a in db.data_control_actions.values()
            if a["resident_id"] == resident["id"]]
    if action_type is not None:
        rows = [a for a in rows if a["action_type"] == action_type]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(
        serialize.dump_all("DataControlAction", page), limit, offset, total)


# --------------------------------------------------------------------------
# devices
# --------------------------------------------------------------------------

@bp.post("/neighborhood-safety/devices")
def create_device():
    actor = auth.authenticate(("Resident",))
    body = v.body_json()
    v.require_present(body, "owner_resident_id")
    owner = fetch.must("Resident", body.get("owner_resident_id"))
    label = v.str_field(body, "label", min_len=1, max_len=80)
    grid_x = v.coord_field(body, "grid_x_m")
    grid_y = v.coord_field(body, "grid_y_m")
    retention = v.int_field(body, "retention_window_days", required=False,
                            default=30, lo=1, hi=180)
    auto_decline = v.bool_field(body, "auto_decline_requests", required=False,
                                default=False)
    auth.require_resident_scope(actor, owner["id"])
    require_active(owner)
    for other in engine.devices_of_resident(owner["id"]):
        if (other["status"] != "DECOMMISSIONED"
                and other["grid_x_m"] == grid_x and other["grid_y_m"] == grid_y):
            raise ApiError("ERR_DUPLICATE_DEVICE_LOCATION",
                           "This owner already has a camera at that position")
    source = "NONE"
    if owner["data_sharing_opt_out"]:
        auto_decline = True
        source = "OPT_OUT"
    elif auto_decline:
        source = "OWNER_MANUAL"
    row = engine.new_row({
        "owner_resident_id": owner["id"],
        "label": label,
        "grid_x_m": grid_x,
        "grid_y_m": grid_y,
        "retention_window_days": retention,
        "status": "ACTIVE",
        "auto_decline_requests": auto_decline,
        "auto_decline_source": source,
        "solicitations_received_count": 0,
        "pending_solicitation_count": 0,
    })
    db.devices[row["id"]] = row
    return envelope.created(serialize.dump("Device", row))


@bp.patch("/neighborhood-safety/devices/<device_id>")
def patch_device(device_id):
    actor = auth.authenticate(("Resident",))
    device = fetch.must("Device", device_id)
    body = v.body_json()
    label = v.str_field(body, "label", required=False, default=None, min_len=1,
                        max_len=80)
    retention = v.int_field(body, "retention_window_days", required=False,
                            default=None, lo=1, hi=180)
    auto_decline = v.bool_field(body, "auto_decline_requests", required=False,
                                default=None)
    status = v.enum_field(body, "status", DEVICE_STATUSES, required=False,
                          default=None)
    owner = db.residents.get(device["owner_resident_id"])
    auth.require_resident_scope(actor, device["owner_resident_id"])
    require_active(owner)
    if label is not None:
        device["label"] = label
    if retention is not None:
        device["retention_window_days"] = retention
    if auto_decline is not None:
        device["auto_decline_requests"] = auto_decline
        device["auto_decline_source"] = "OWNER_MANUAL" if auto_decline else "NONE"
    status_changed = status is not None and status != device["status"]
    if status is not None:
        device["status"] = status
    engine.touch(device)
    if status_changed:
        engine.check_eligibility_collapse([device["id"]])
    return envelope.ok(serialize.dump("Device", device))


@bp.get("/neighborhood-safety/devices/<device_id>")
def read_device(device_id):
    auth.authenticate(("PlatformAdmin", "Officer", "Resident"))
    device = fetch.must("Device", device_id)
    return envelope.ok(serialize.dump("Device", device))


@bp.get("/neighborhood-safety/devices")
def list_devices():
    auth.authenticate(("PlatformAdmin", "Officer", "Resident"))
    limit, offset = v.pagination()
    owner_id = v.query_str("owner_resident_id")
    status = v.query_enum("status", DEVICE_STATUSES)
    auto_decline = v.query_bool("auto_decline_requests")
    rows = list(db.devices.values())
    if owner_id is not None:
        rows = [r for r in rows if r["owner_resident_id"] == owner_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if auto_decline is not None:
        rows = [r for r in rows if r["auto_decline_requests"] == auto_decline]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("Device", page), limit,
                               offset, total)


# --------------------------------------------------------------------------
# account-level data controls (PRD 3.2)
# --------------------------------------------------------------------------

@bp.post("/neighborhood-safety/residents/<resident_id>/data-controls")
def create_data_control(resident_id):
    actor = auth.authenticate(("Resident",))
    resident = fetch.must("Resident", resident_id)
    body = v.body_json()
    action_type = v.enum_field(body, "action_type", ACTION_TYPES)
    reason = v.str_field(body, "reason", required=False, default=None,
                        allow_empty=True)
    auth.require_resident_scope(actor, resident["id"])
    require_active(resident)
    if action_type in ("PURGE_HISTORY", "DEACTIVATE_ACCOUNT"):
        for clip in engine.clips_of_resident(resident["id"]):
            if clip["status"] == "LEGAL_HOLD":
                raise ApiError("ERR_DATA_CONTROL_BLOCKED_BY_HOLD",
                               "A clip of this resident is under legal hold")

    counts = {"device": 0, "solicitation": 0, "clip": 0, "request": 0}
    if action_type == "OPT_OUT_OF_REQUESTS":
        _opt_out(resident, counts)
    elif action_type == "OPT_IN_TO_REQUESTS":
        _opt_in(resident, counts)
    elif action_type == "PURGE_HISTORY":
        _purge_history(resident, counts)
    else:
        _deactivate(resident, counts)

    receipt = engine.new_row({
        "resident_id": resident["id"],
        "action_type": action_type,
        "reason": reason,
        "affected_device_count": counts["device"],
        "affected_solicitation_count": counts["solicitation"],
        "affected_clip_count": counts["clip"],
        "affected_request_count": counts["request"],
        "applied_at": now(),
    }, versioned=False)
    db.data_control_actions[receipt["id"]] = receipt
    return envelope.created(serialize.dump("DataControlAction", receipt))


def _resolve_affected_requests(request_ids):
    """Cascade level four -- video requests in ascending created_at (PRD 2.11)."""
    rows = [db.video_requests[r] for r in request_ids if r in db.video_requests]
    for row in store.by_created(rows):
        engine.sync_request(row)


def _opt_out(resident, counts):
    resident["data_sharing_opt_out"] = True
    engine.touch(resident)
    devices = [d for d in engine.devices_of_resident(resident["id"])
               if d["status"] != "DECOMMISSIONED"]
    for device in store.by_created(devices):
        device["auto_decline_requests"] = True
        device["auto_decline_source"] = "OPT_OUT"
        engine.touch(device)
    counts["device"] = len(devices)
    device_ids = set(d["id"] for d in devices)
    pending = [s for s in engine.solicitations_of_resident(resident["id"])
               if s["status"] == "SOLICITED" and s["device_id"] in device_ids]
    pending = store.by_created(pending)
    touched_requests = []
    for sol in pending:
        engine.decline_solicitation(sol, "OWNER_OPT_OUT")
        if sol["video_request_id"] not in touched_requests:
            touched_requests.append(sol["video_request_id"])
    counts["solicitation"] = len(pending)
    counts["request"] = len(touched_requests)
    _resolve_affected_requests(touched_requests)
    engine.check_eligibility_collapse(
        [d["id"] for d in engine.devices_of_resident(resident["id"])])


def _opt_in(resident, counts):
    resident["data_sharing_opt_out"] = False
    engine.touch(resident)
    devices = [d for d in engine.devices_of_resident(resident["id"])
               if d["auto_decline_source"] == "OPT_OUT"]
    for device in store.by_created(devices):
        device["auto_decline_requests"] = False
        device["auto_decline_source"] = "NONE"
        engine.touch(device)
    counts["device"] = len(devices)
    engine.check_eligibility_collapse(
        [d["id"] for d in engine.devices_of_resident(resident["id"])])


def _purge_history(resident, counts):
    engine.touch(resident)
    clips = [c for c in engine.clips_of_resident(resident["id"])
             if c["status"] == "RETAINED"]
    withdrawn = 0
    touched_requests = []
    for clip in store.by_created(clips):
        if engine.purge_clip(clip, "OWNER_REVOCATION"):
            withdrawn += 1
            if clip["video_request_id"] not in touched_requests:
                touched_requests.append(clip["video_request_id"])
    counts["clip"] = len(clips)
    counts["solicitation"] = withdrawn
    counts["request"] = len(touched_requests)


def _deactivate(resident, counts):
    resident["status"] = "DEACTIVATED"
    resident["data_sharing_opt_out"] = True
    engine.touch(resident)
    devices = [d for d in engine.devices_of_resident(resident["id"])
               if d["status"] != "DECOMMISSIONED"]
    for device in store.by_created(devices):
        device["status"] = "DECOMMISSIONED"
        engine.touch(device)
    counts["device"] = len(devices)
    pending = [s for s in engine.solicitations_of_resident(resident["id"])
               if s["status"] == "SOLICITED"]
    pending = store.by_created(pending)
    touched_requests = []
    for sol in pending:
        engine.decline_solicitation(sol, "ACCOUNT_DEACTIVATED")
        if sol["video_request_id"] not in touched_requests:
            touched_requests.append(sol["video_request_id"])
    counts["solicitation"] = len(pending)
    clips = [c for c in engine.clips_of_resident(resident["id"])
             if c["status"] == "RETAINED"]
    for clip in store.by_created(clips):
        clip["status"] = "PURGE_PENDING"
        engine.touch(clip)
    counts["clip"] = len(clips)
    counts["request"] = len(touched_requests)
    _resolve_affected_requests(touched_requests)
    engine.check_eligibility_collapse(
        [d["id"] for d in engine.devices_of_resident(resident["id"])])
