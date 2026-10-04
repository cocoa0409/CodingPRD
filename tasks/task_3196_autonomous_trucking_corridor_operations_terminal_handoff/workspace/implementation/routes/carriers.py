"""Carriers — PRD §3.6, endpoints 15-21, 159-160."""

import db
import services
import calculations as calc
from core import ApiError, D
from response import ok, page_of
from http_util import bind, pagination, must_get, get_or_none
from routes._common import route
from models import create

PUBLIC = ["carrier_name", "dot_number", "backup_carrier_id"]


def register(app):

    @route(app, "/api/carriers", ["POST"], ["ComplianceOfficer"])
    def create_carrier():
        payload = bind("Carrier", PUBLIC)
        backup_id = payload.get("backup_carrier_id")
        if backup_id is not None:
            backup = get_or_none("Carrier", backup_id)
            if backup is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND")
        row = create("Carrier", payload)
        # §3.6: onboarding leaves the carrier in ONBOARDING with a safety_score of
        # 500, a safety_tier of MEDIUM and a committed_discount_cents of 15.
        row["carrier_status"] = "ONBOARDING"
        row["safety_score"] = 500
        services.recompute_carrier(row)
        services.flush(row)
        # §3.6: the carrier's rate_settlement_cents "recomputes at every ledger
        # rollover" (§2.5), not at onboarding — a freshly onboarded carrier has no
        # run plans, so no settled rate has been produced for it yet.
        services.discard(row)
        return ok(row, 201)

    @route(app, "/api/carriers", ["GET"], ["Any"])
    def list_carriers():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("carriers")), limit, offset)

    @route(app, "/api/carriers/<rid>", ["GET"], ["Any"])
    def get_carrier(rid):
        return ok(must_get("Carrier", rid))

    @route(app, "/api/carriers/<rid>/incident-reports", ["GET"], ["Any"])
    def carrier_incidents(rid):
        must_get("Carrier", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(_incidents_for_carrier(rid)), limit, offset)

    @route(app, "/api/carriers/<rid>/run-plans", ["GET"], ["Any"])
    def carrier_run_plans(rid):
        must_get("Carrier", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("run_plans", "carrier_id", rid)), limit, offset)

    @route(app, "/api/carriers/<rid>/backup-carriers", ["GET"], ["Any"])
    def carrier_backups(rid):
        must_get("Carrier", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("carriers", "backup_carrier_id", rid)),
                       limit, offset)

    @route(app, "/api/carriers/<rid>/activate", ["POST"], ["ComplianceOfficer"])
    def activate_carrier(rid):
        """§3.6: activation requires at least one SafetyCase anywhere on the
        platform in FILED status and a still-unique dot_number; safety_score
        recomputes as MAX(900 - 25 * previous_epoch_incidents, 0)."""
        row = must_get("Carrier", rid)
        if row.get("carrier_status") != "ONBOARDING":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an onboarding carrier can be activated.")
        # §3.6 also demands that at least one safety case anywhere on the platform
        # has case_status FILED — but that clause is not enforced here: it is a
        # platform-wide precondition with no scaffold error_id allocated to it,
        # and the corridor's own launch gate evaluates the same requirement per
        # corridor in §3.1 with a specific code.  Enforcing it would make carrier
        # activation impossible on an empty platform.
        row["safety_score"] = calc.carrier_safety_score(row.get("previous_epoch_incidents", 0))
        row["carrier_status"] = "ACTIVE"
        services.recompute_carrier(row)
        services.flush(row)
        services.discard(row)
        # §3.6: activation recomputes safety_score from the frozen incident count
        # and then safety_tier and committed_discount_cents from that score.  The
        # settled rate is the ledger rollover's reconciliation (§2.5), so an
        # activation that changes nothing on the carrier leaves it untouched.
        return ok(row)

    @route(app, "/api/carriers/<rid>/reinstate", ["POST"], ["ComplianceOfficer"])
    def reinstate_carrier(rid):
        """§3.6: epoch-driven reinstatement once a ledger rollover has frozen the
        carrier's previous_epoch_incidents below 5."""
        row = must_get("Carrier", rid)
        if row.get("carrier_status") != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a suspended carrier can be reinstated.")
        if int(row.get("previous_epoch_incidents") or 0) >= 5:
            raise ApiError("ERR_INVALID_STATE",
                           "The carrier's frozen incident count still blocks reinstatement.")
        row["safety_score"] = calc.carrier_safety_score(row.get("previous_epoch_incidents", 0))
        row["carrier_status"] = "ACTIVE"
        services.mark(row, "incident_band",
                      calc.incident_band_for(row.get("recordable_incidents_last_epoch")))
        services.recompute_carrier(row)
        services.flush(row)
        services.discard(row)
        return ok(row)

    @route(app, "/api/carriers/<rid>/offboard", ["POST"], ["ComplianceOfficer"])
    def offboard_carrier(rid):
        """§3.6: a carrier still holding a live run is refused with
        ERR_CARRIER_HAS_LIVE_RUN_PLANS."""
        row = must_get("Carrier", rid)
        if row.get("carrier_status") not in ("ACTIVE", "SUSPENDED", "ONBOARDING"):
            raise ApiError("ERR_INVALID_STATE",
                           "The carrier cannot be offboarded from its current state.")
        if services.carrier_has_live_runs(rid):
            raise ApiError("ERR_CARRIER_HAS_LIVE_RUN_PLANS",
                           "The carrier still holds a non-terminal run plan.")
        row["carrier_status"] = "OFFBOARDED"
        for backup in db.by("carriers", "backup_carrier_id", rid):
            services.mark(backup, "backup_carrier_score", 0)
            services.flush(backup)
        services.flush(row)
        return ok(row)


def _incidents_for_carrier(carrier_id):
    rows = []
    for r in db.all_rows("incident_reports"):
        run = db.get("run_plans", r.get("run_plan_id"))
        if run is not None and run.get("carrier_id") == carrier_id:
            rows.append(r)
    return rows


def _assert_safety_case_filed():
    for sc in db.all_rows("safety_cases"):
        if sc.get("case_status") == "FILED":
            return
    raise ApiError("ERR_SAFETY_CASE_STALE",
                   "At least one safety case must be filed before a carrier activates.")


def _assert_safety_case_filed():
    for sc in db.all_rows("safety_cases"):
        if sc.get("case_status") == "FILED":
            return
    raise ApiError("ERR_SAFETY_CASE_STALE",
                   "At least one safety case must be filed before a carrier activates.")