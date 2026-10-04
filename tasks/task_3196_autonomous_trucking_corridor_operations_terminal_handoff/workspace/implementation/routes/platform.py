"""Platform controls: the logical clock and the ledger epoch — PRD §2.5,
endpoints 1-6 of §4.
"""

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, to_iso, parse_iso, try_iso
from response import ok, ok_empty, page_of
from http_util import bind, pagination, must_get, body, require_enum
from routes._common import route


def _checkpoint_payload(raw):
    allowed = {"checkpoint_code", "epoch_start_at", "epoch_end_at", "hours_per_epoch"}
    for key in raw:
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
    for key in ("checkpoint_code", "epoch_start_at", "epoch_end_at"):
        if key not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Required field '%s' is missing." % key)
    start = parse_iso(raw["epoch_start_at"])
    end = parse_iso(raw["epoch_end_at"])
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", "Epoch instants must be ISO 8601 UTC.")
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "epoch_end_at must be strictly after epoch_start_at.")
    payload = {
        "checkpoint_code": raw["checkpoint_code"],
        "epoch_start_at": to_iso(start),
        "epoch_end_at": to_iso(end),
        "hours_per_epoch": int(raw.get("hours_per_epoch", 24)),
    }
    return payload


def register(app):

    @route(app, "/_clock/set_current_utc", ["POST"], ["PlatformAdmin"])
    def set_current_utc():
        """§2.5: advancing the clock "mutates no business field on any entity"."""
        raw = body()
        for key in raw:
            if key != "current_utc":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "current_utc" not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Required field 'current_utc' is missing.")
        parsed = parse_iso(raw["current_utc"])
        if parsed is None:
            raise ApiError("ERR_INVALID_REQUEST", "current_utc must be ISO 8601 UTC.")
        core.set_clock(raw["current_utc"])
        return ok_empty(200)

    @route(app, "/api/ledger-checkpoints", ["POST"], ["PlatformAdmin"])
    def create_checkpoint():
        from models import create
        payload = _checkpoint_payload(body())
        row = create("LedgerCheckpoint", payload)
        return ok(row, 201)

    @route(app, "/api/ledger-checkpoints", ["GET"], ["Any"])
    def list_checkpoints():
        limit, offset = pagination()
        rows = db.sort_created(db.all_rows("ledger_checkpoints"))
        return page_of(rows, limit, offset)

    @route(app, "/api/ledger-checkpoints/<rid>", ["GET"], ["Any"])
    def get_checkpoint(rid):
        return ok(must_get("LedgerCheckpoint", rid))

    @route(app, "/api/ledger-checkpoints/<rid>/adopt", ["POST"], ["PlatformAdmin"])
    def adopt_checkpoint(rid):
        row = must_get("LedgerCheckpoint", rid)
        if row.get("checkpoint_status") == "ROLLED_OVER":
            raise ApiError("ERR_INVALID_STATE",
                           "A rolled-over epoch can no longer be adopted.")
        if row.get("checkpoint_status") != "ADOPTED":
            row["checkpoint_status"] = "ADOPTED"
            row["adopted_at"] = now_iso()
            db.touch(row, now_iso())
        # §2.5: the earlier of two same-epoch checkpoints wins the debits.  Both
        # rows are marked ADOPTED so the earlier one keeps the debits.
        for other in db.by("ledger_checkpoints", "epoch_start_at", row.get("epoch_start_at")):
            if other["id"] == row["id"]:
                continue
            if other.get("checkpoint_status") == "OPEN":
                other["checkpoint_status"] = "ADOPTED"
                other["adopted_at"] = now_iso()
                db.touch(other, now_iso())
        for a in db.all_rows("state_authorities"):
            services.recompute_authority(a)
            services.flush(a)
        return ok(row)

    @route(app, "/api/ledger-checkpoints/<rid>/roll-over", ["POST"], ["PlatformAdmin"])
    def roll_over(rid):
        row = must_get("LedgerCheckpoint", rid)
        if row.get("checkpoint_status") == "ROLLED_OVER":
            raise ApiError("ERR_INVALID_STATE", "This epoch has already rolled over.")
        row["checkpoint_status"] = "ROLLED_OVER"
        row["rolled_over_at"] = now_iso()
        db.touch(row, now_iso())
        _roll_over_consequences()
        return ok(row)


def _roll_over_consequences():
    """§2.5: rolling an epoch over is the single largest reconciliation."""
    # Every carrier's previous_epoch_incidents is overwritten with that carrier's
    # recordable_incidents_last_epoch, and recordable_incidents_last_epoch is then
    # reset to 0.
    for c in db.all_rows("carriers"):
        c["previous_epoch_incidents"] = int(c.get("recordable_incidents_last_epoch") or 0)
        services.mark(c, "recordable_incidents_last_epoch", 0)
        services.mark(c, "incident_band",
                      calc.incident_band_for(c.get("previous_epoch_incidents")))
        services.mark(c, "safety_tier", calc.safety_tier_for_score(c.get("safety_score", 0)))
        services.mark(c, "committed_discount_cents",
                      calc.discount_for_tier(c.get("safety_tier")))
        services.recompute_carrier_rate_settlement(c)
        services.flush(c)

    # Every state authority's hours_used resets to 0.
    for a in db.all_rows("state_authorities"):
        services.mark(a, "hours_used", 0)
        services.mark(a, "remaining_autonomous_hours",
                      max(int(a.get("autonomous_hours_allowed") or 0), 0))
        services.flush(a)

    # Readiness checks: elapsed windows expire; CALIBRATION_PASSED checks on a
    # corridor that did receive a launch authorisation advance to VALIDATED.
    touched_corridors = {}
    for c in db.all_rows("launch_readiness_checks"):
        corridor = db.get("corridors", c.get("corridor_id"))
        if corridor is None:
            continue
        elapsed = _window_elapsed(c)
        status = c.get("check_status")
        if status in ("CALIBRATION_PASSED", "VALIDATED") and elapsed:
            services.mark(c, "check_status", "EXPIRED_FAILED")
            services.flush(c)
            touched_corridors[corridor["id"]] = corridor
        elif status == "INITIALIZED" and elapsed:
            services.mark(c, "check_status", "EXPIRED_FAILED")
            services.flush(c)
            touched_corridors[corridor["id"]] = corridor
        elif status == "CALIBRATION_PASSED" and corridor.get("launch_authorized_at"):
            services.mark(c, "check_status", "VALIDATED")
            services.flush(c)
            touched_corridors[corridor["id"]] = corridor

    for corridor in touched_corridors.values():
        services.recompute_corridor(corridor)
        services.flush(corridor)

    # Any carrier whose carrier_status is ACTIVE and whose recomputed incident_band
    # reaches SUSPENDED is moved to SUSPENDED, and every run plan on that carrier
    # sitting in DRAFT or READINESS_PENDING is aborted.
    for c in db.all_rows("carriers"):
        if c.get("carrier_status") == "ACTIVE" and c.get("incident_band") == "SUSPENDED":
            services.suspend_carrier(c)
        services.flush(c)


def _window_elapsed(check):
    start = parse_iso(check.get("valid_window_start_at"))
    if start is None:
        return False
    days = int(check.get("valid_window_days") or 0)
    from datetime import timedelta
    return core.now() > start + timedelta(days=days)