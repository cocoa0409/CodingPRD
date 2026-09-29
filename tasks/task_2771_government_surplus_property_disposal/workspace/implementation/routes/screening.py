"""Screening ladder endpoints (PRD section 3.4)."""
import db as store
from db import db, by_created, iso, iso_date, parse_instant
from errors import ApiError
from middleware import (Fields, agency_scope, endpoint, list_params,
                        plain_filters, read_body)
from response import collection, created, ok
from services import calc, rollups
from services.enums import CYCLE_STATUS, REQUEST_STATUS, TIER, TIER_LADDER
from services.serialize import view, views


def deadline(opened_at, window_days):
    return iso(store.add_days(parse_instant(opened_at), window_days))


def register(app):

    # -- cycles ------------------------------------------------------------

    @app.route("/screening-cycles", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def create_cycle(ctx):
        body = read_body()
        f = Fields(body)
        f.string("asset_id", required=True, minlen=1)
        f.instant("opens_at", required=True)
        f.integer("tier_window_days", required=True, minv=1, maxv=60)
        f.done()
        asset = rollups.fetch(db.assets, f["asset_id"], "ERR_ASSET_NOT_FOUND")
        turn_in = db.turn_ins.get(asset["turn_in_id"])
        fmv = asset["fair_market_value_cents"]
        if (asset["disposition_status"] != "ASSESSED"
                or turn_in is None or turn_in["status"] != "ACCEPTED"
                or fmv is None
                or fmv < calc.DE_MINIMIS_SCREENING_THRESHOLD_CENTS):
            raise ApiError("ERR_ASSET_NOT_DISPOSABLE",
                           "the asset is not eligible for tier screening")
        if calc.federal_use_period_active(asset):
            raise ApiError("ERR_FEDERAL_USE_PERIOD_ACTIVE",
                           "the federal use period has not expired")
        if f["opens_at"] < store.db.now:
            raise ApiError("ERR_INVALID_WINDOW",
                           "opens_at must be at or after the logical clock")
        cycle = store.base_row()
        cycle.update({
            "asset_id": asset["id"],
            "opens_at": iso(f["opens_at"]),
            "tier_window_days": f["tier_window_days"],
            "current_tier": "STATE_AGENCY",
            "tier_opened_at": iso(f["opens_at"]),
            "tier_deadline_at": iso(store.add_days(f["opens_at"], f["tier_window_days"])),
            "status": "OPEN",
            "tier_advance_count": 0,
            "awarded_by_user_id": None,
            "awarded_at": None,
            "open_request_count": 0,
        })
        db.cycles[cycle["id"]] = cycle
        asset["disposition_status"] = "SCREENING"
        ctx.touch(asset)
        return created(view("ScreeningCycle", cycle))

    @app.route("/screening-cycles/<cycle_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "AgencyOfficer"])
    def get_cycle(ctx, cycle_id):
        cycle = rollups.fetch(db.cycles, cycle_id, "ERR_SCREENING_CYCLE_NOT_FOUND")
        return ok(view("ScreeningCycle", cycle))

    @app.route("/screening-cycles", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "AgencyOfficer"])
    def list_cycles(ctx):
        filters, limit, offset = list_params({
            "current_tier": TIER, "status": CYCLE_STATUS})
        plain = plain_filters(["asset_id"])
        rows = by_created(db.cycles.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("ScreeningCycle", rows), limit, offset)

    @app.route("/screening-cycles/<cycle_id>/advance-tier", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def advance_tier(ctx, cycle_id):
        read_body()
        cycle = rollups.fetch(db.cycles, cycle_id, "ERR_SCREENING_CYCLE_NOT_FOUND")
        if cycle["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "only an OPEN cycle may advance")
        open_requests = rollups.count_open_requests(cycle["id"])
        if (open_requests != 0
                and store.db.now < parse_instant(cycle["tier_deadline_at"])):
            raise ApiError("ERR_TIER_WINDOW_OPEN",
                           "the current tier still has open requests inside its window")
        cycle["open_request_count"] = open_requests
        cycle["tier_advance_count"] += 1
        if cycle["current_tier"] == "PUBLIC_SALE":
            cycle["status"] = "EXHAUSTED"
            asset = db.assets.get(cycle["asset_id"])
            if asset is not None and asset["disposition_status"] == "SCREENING":
                asset["disposition_status"] = "AUCTION_ELIGIBLE"
                ctx.touch(asset)
        else:
            index = TIER_LADDER.index(cycle["current_tier"])
            cycle["current_tier"] = TIER_LADDER[index + 1]
            cycle["tier_opened_at"] = iso(store.db.now)
            cycle["tier_deadline_at"] = deadline(cycle["tier_opened_at"],
                                                 cycle["tier_window_days"])
        ctx.touch(cycle)
        return ok(view("ScreeningCycle", cycle))

    @app.route("/screening-cycles/<cycle_id>/award", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def award_cycle(ctx, cycle_id):
        body = read_body()
        f = Fields(body)
        f.string("screening_request_id", required=True, minlen=1)
        f.done()
        cycle = rollups.fetch(db.cycles, cycle_id, "ERR_SCREENING_CYCLE_NOT_FOUND")
        if cycle["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "only an OPEN cycle may be awarded")
        winner = rollups.fetch(db.requests, f["screening_request_id"],
                               "ERR_SCREENING_REQUEST_NOT_FOUND")
        if (winner["screening_cycle_id"] != cycle["id"]
                or winner["status"] != "SUBMITTED"):
            raise ApiError("ERR_REQUEST_CYCLE_MISMATCH",
                           "the named request does not belong to this cycle in a "
                           "SUBMITTED status")
        agency = db.agencies.get(winner["requesting_agency_id"])
        if agency is None or agency["status"] != "ACTIVE":
            raise ApiError("ERR_AGENCY_SUSPENDED",
                           "the requesting organisation is not ACTIVE")
        cycle["status"] = "AWARDED"
        cycle["awarded_by_user_id"] = ctx.user_id
        cycle["awarded_at"] = iso(store.db.now)
        winner["status"] = "APPROVED"
        ctx.touch(winner)
        for other in rollups.requests_of_cycle(cycle["id"]):
            if other is winner:
                continue
            if other["status"] in ("SUBMITTED", "INFO_REQUESTED"):
                other["status"] = "DENIED"
                other["denial_reason"] = "LOST_AWARD"
                ctx.touch(other)
        asset = db.assets.get(cycle["asset_id"])
        if asset is not None and asset["disposition_status"] == "SCREENING":
            asset["disposition_status"] = "AWARDED_TRANSFER"
            ctx.touch(asset)
        rollups.recompute_cycle_open_requests(cycle, ctx)
        ctx.touch(cycle)
        return ok(view("ScreeningCycle", cycle))

    # -- requests ----------------------------------------------------------

    @app.route("/screening-requests", methods=["POST"])
    @endpoint(["AgencyOfficer", "ProgramAdmin"])
    def create_request(ctx):
        body = read_body()
        agency_scope(ctx, body.get("requesting_agency_id")
                     if isinstance(body.get("requesting_agency_id"), str) else None)
        f = Fields(body)
        f.string("screening_cycle_id", required=True, minlen=1)
        f.string("requesting_agency_id", required=True, minlen=1)
        f.string("intended_use", required=True, minlen=1, maxlen=200)
        f.string("justification", required=True, minlen=1, maxlen=500)
        f.date("needed_by_date", required=True)
        f.done()
        cycle = rollups.fetch(db.cycles, f["screening_cycle_id"],
                              "ERR_SCREENING_CYCLE_NOT_FOUND")
        agency = rollups.fetch(db.agencies, f["requesting_agency_id"],
                               "ERR_AGENCY_NOT_FOUND")
        if cycle["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "the cycle no longer accepts screening requests")
        if agency["status"] != "ACTIVE":
            raise ApiError("ERR_AGENCY_SUSPENDED",
                           "a suspended organisation may not file a screening request")
        if agency["agency_type"] != cycle["current_tier"]:
            raise ApiError("ERR_TIER_PRIORITY_VIOLATION",
                           "the organisation's tier is not the cycle's current tier")
        now = store.db.now
        if (now < parse_instant(cycle["tier_opened_at"])
                or now > parse_instant(cycle["tier_deadline_at"])):
            raise ApiError("ERR_TIER_WINDOW_EXPIRED",
                           "the logical clock lies outside the tier window")
        row = store.base_row()
        row.update({
            "screening_cycle_id": cycle["id"],
            "requesting_agency_id": agency["id"],
            "intended_use": f["intended_use"],
            "justification": f["justification"],
            "needed_by_date": iso_date(f["needed_by_date"]),
            "tier_at_submission": cycle["current_tier"],
            "status": "SUBMITTED",
            "information_request_note": None,
            "resubmission_count": 0,
            "denial_reason": None,
        })
        db.requests[row["id"]] = row
        rollups.recompute_cycle_open_requests(cycle, ctx)
        return created(view("ScreeningRequest", row))

    @app.route("/screening-requests/<request_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "AgencyOfficer"])
    def get_request(ctx, request_id):
        row = rollups.fetch(db.requests, request_id, "ERR_SCREENING_REQUEST_NOT_FOUND")
        agency_scope(ctx, row["requesting_agency_id"])
        return ok(view("ScreeningRequest", row))

    @app.route("/screening-requests", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "AgencyOfficer"])
    def list_requests(ctx):
        filters, limit, offset = list_params({"status": REQUEST_STATUS})
        plain = plain_filters(["screening_cycle_id", "requesting_agency_id"])
        rows = by_created(db.requests.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("ScreeningRequest", rows), limit, offset)

    @app.route("/screening-requests/<request_id>/request-info", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def request_info(ctx, request_id):
        body = read_body()
        f = Fields(body)
        f.string("information_request_note", required=True, minlen=1)
        f.done()
        row = rollups.fetch(db.requests, request_id, "ERR_SCREENING_REQUEST_NOT_FOUND")
        cycle = db.cycles.get(row["screening_cycle_id"])
        if row["status"] != "SUBMITTED" or cycle is None or cycle["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "only a SUBMITTED request on an OPEN cycle may be queried")
        row["status"] = "INFO_REQUESTED"
        row["information_request_note"] = f["information_request_note"]
        ctx.touch(row)
        return ok(view("ScreeningRequest", row))

    @app.route("/screening-requests/<request_id>/resubmit", methods=["POST"])
    @endpoint(["AgencyOfficer"])
    def resubmit_request(ctx, request_id):
        body = read_body()
        f = Fields(body)
        f.string("justification", required=True, minlen=1, maxlen=500)
        f.done()
        row = rollups.fetch(db.requests, request_id, "ERR_SCREENING_REQUEST_NOT_FOUND")
        agency_scope(ctx, row["requesting_agency_id"])
        cycle = db.cycles.get(row["screening_cycle_id"])
        if row["status"] != "INFO_REQUESTED" or cycle is None or cycle["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "only an INFO_REQUESTED request on an OPEN cycle may be "
                           "resubmitted")
        if store.db.now > parse_instant(cycle["tier_deadline_at"]):
            raise ApiError("ERR_TIER_WINDOW_EXPIRED",
                           "the tier window has closed")
        row["justification"] = f["justification"]
        row["resubmission_count"] += 1
        row["information_request_note"] = None
        row["status"] = "SUBMITTED"
        ctx.touch(row)
        return ok(view("ScreeningRequest", row))
