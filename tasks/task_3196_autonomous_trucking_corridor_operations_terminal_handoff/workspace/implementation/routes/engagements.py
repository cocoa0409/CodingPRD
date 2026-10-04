"""Regulatory engagements and the autonomous-hour budget — PRD §2.5, §3.12,
endpoints 118-123.
"""

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, parse_iso, to_iso
from response import ok, page_of
from http_util import pagination, must_get, get_or_none, body, coerce_int, arg
from routes._common import route
from models import create

ENGAGEMENT_TYPES = ("SAFETY_BRIEFING", "OPERATIONAL_NOTICE", "INCIDENT_DISCLOSURE",
                    "HOURS_ALLOCATION_REQUEST")


def register(app):

    @route(app, "/api/regulatory-engagements", ["POST"], ["RegulatoryLiaison"])
    def create_engagement():
        """§3.12: its engaged_at must fall inside the current epoch's closed-open
        window and the autonomous_hours_requested must not exceed the state
        authority's remaining_autonomous_hours for the epoch."""
        raw = body()
        allowed = {"corridor_id", "state_authority_id", "engagement_type",
                   "autonomous_hours_requested", "autonomous_hours_logged",
                   "engaged_at"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("corridor_id", "state_authority_id", "engagement_type",
                    "autonomous_hours_requested", "engaged_at"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        corridor = get_or_none("Corridor", raw["corridor_id"])
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        authority = get_or_none("StateAuthority", raw["state_authority_id"])
        if authority is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND")
        if raw["engagement_type"] not in ENGAGEMENT_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown engagement_type.")
        requested = coerce_int(raw["autonomous_hours_requested"])
        logged = int(raw.get("autonomous_hours_logged", 0) or 0)
        engaged_at = parse_iso(raw["engaged_at"])
        if engaged_at is None:
            raise ApiError("ERR_INVALID_REQUEST", "engaged_at must be ISO 8601 UTC.")

        # Priority 31 — the requested hours must not overshoot the authority's
        # remaining_autonomous_hours for the epoch.
        remaining = calc.remaining_autonomous_hours(authority)
        if requested > remaining:
            raise ApiError("ERR_HOURS_BUDGET_EXCEEDED",
                           "The requested autonomous hours exceed the remaining budget.")
        # Priority 32 — the engagement moment must fall inside the current epoch
        # window [epoch_start_at, epoch_end_at).
        epoch_start, epoch_end = core.epoch_window()
        if epoch_start is not None and epoch_end is not None:
            if not (epoch_start <= engaged_at < epoch_end):
                raise ApiError("ERR_OUTSIDE_EPOCH_WINDOW",
                               "The engagement falls outside the current epoch window.")

        row = create("RegulatoryEngagement", {
            "corridor_id": corridor["id"],
            "state_authority_id": authority["id"],
            "engagement_type": raw["engagement_type"],
            "autonomous_hours_requested": requested,
            "autonomous_hours_logged": logged,
            "engaged_at": to_iso(engaged_at),
        })
        row["engagement_status"] = "DRAFT"
        services.mark(row, "state_status",
                      calc.state_status_for(raw["engagement_type"],
                                            corridor.get("weather_profile")))
        services.mark(row, "hours_charge_allowed", calc.hours_charge_allowed(row))
        services.flush(row)
        services.recompute_authority(authority)
        services.flush(authority)
        return ok(row, 201)

    @route(app, "/api/regulatory-engagements", ["GET"], ["Any"])
    def list_engagements():
        limit, offset = pagination()
        rows = db.all_rows("regulatory_engagements")
        for field in ("corridor_id", "state_authority_id", "engagement_status"):
            value = arg(field)
            if value:
                rows = [r for r in rows if r.get(field) == value]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/regulatory-engagements/<rid>", ["GET"], ["Any"])
    def get_engagement(rid):
        return ok(must_get("RegulatoryEngagement", rid))

    @route(app, "/api/regulatory-engagements/<rid>/submit", ["POST"], ["RegulatoryLiaison"])
    def submit_engagement(rid):
        """§3.12: submission debits the authority's hour budget; an engagement
        whose state_status is not FORMAL or INFORMAL, or which has no accepted
        prior engagement in the same epoch, is refused with ERR_CHARGE_NOT_ALLOWED."""
        row = must_get("RegulatoryEngagement", rid)
        raw = body()
        _reject_unknown(raw)
        if row.get("engagement_status") not in ("DRAFT",):
            raise ApiError("ERR_INVALID_STATE", "Only a draft engagement can be submitted.")
        # Priority 30 — the charge permission.
        if row.get("state_status") not in ("FORMAL", "INFORMAL") \
                or calc.prior_accepted_in_epoch(row.get("state_authority_id"),
                                                exclude_id=rid) is None:
            raise ApiError("ERR_CHARGE_NOT_ALLOWED",
                           "The autonomous-hour charge is not permitted for this engagement.")
        services.mark(row, "engagement_status", "SUBMITTED")
        services.flush(row)
        authority = db.get("state_authorities", row.get("state_authority_id"))
        if authority is not None:
            services.recompute_authority(authority)
            services.flush(authority)
        return ok(row)

    @route(app, "/api/regulatory-engagements/<rid>/accept", ["POST"], ["RegulatoryLiaison"])
    def accept_engagement(rid):
        """§3.12: accepting recomputes hours_charge_allowed on later engagements in
        the same epoch."""
        row = must_get("RegulatoryEngagement", rid)
        raw = body()
        _reject_unknown(raw)
        if row.get("engagement_status") not in ("DRAFT", "SUBMITTED"):
            raise ApiError("ERR_INVALID_STATE", "The engagement is already terminal.")
        services.mark(row, "engagement_status", "ACCEPTED")
        services.flush(row)
        for other in db.by("regulatory_engagements", "state_authority_id",
                           row.get("state_authority_id")):
            if other["id"] == row["id"]:
                continue
            services.mark(other, "hours_charge_allowed", calc.hours_charge_allowed(other))
            services.flush(other)
        return ok(row)

    @route(app, "/api/regulatory-engagements/<rid>/reject", ["POST"], ["RegulatoryLiaison"])
    def reject_engagement(rid):
        """§3.12: rejecting recomputes the owning authority's hours_used downward,
        releasing the hours it had debited."""
        row = must_get("RegulatoryEngagement", rid)
        raw = body()
        _reject_unknown(raw)
        if row.get("engagement_status") in ("ACCEPTED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE", "The engagement is already terminal.")
        services.mark(row, "engagement_status", "REJECTED")
        services.flush(row)
        authority = db.get("state_authorities", row.get("state_authority_id"))
        if authority is not None:
            services.recompute_authority(authority)
            services.flush(authority)
        return ok(row)


def _reject_unknown(raw):
    for key in raw:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)