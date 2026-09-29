"""Turn-in intake endpoints (PRD section 3.2)."""
import db as store
from db import db, by_created
from errors import ApiError
from middleware import Fields, agency_scope, endpoint, list_params, plain_filters, read_body
from response import collection, created, ok
from services import rollups
from services.enums import REVIEW_DECISION, TURN_IN_STATUS
from services.serialize import view, views


def register(app):

    @app.route("/turn-ins", methods=["POST"])
    @endpoint(["AgencyOfficer", "ProgramAdmin"])
    def create_turn_in(ctx):
        body = read_body()
        agency_scope(ctx, body.get("turning_in_agency_id")
                     if isinstance(body.get("turning_in_agency_id"), str) else None)
        f = Fields(body)
        f.string("turning_in_agency_id", required=True, minlen=1)
        f.string("custody_location", required=True, minlen=1, maxlen=120)
        f.string("remarks")
        f.done()
        agency = rollups.fetch(db.agencies, f["turning_in_agency_id"],
                               "ERR_AGENCY_NOT_FOUND")
        if agency["status"] != "ACTIVE":
            raise ApiError("ERR_AGENCY_SUSPENDED",
                           "a suspended agency may not open a turn-in")
        turn_in = store.base_row()
        turn_in.update({
            "turning_in_agency_id": agency["id"],
            "custody_location": f["custody_location"],
            "remarks": f["remarks"],
            "status": "DRAFT",
            "rejection_reason": None,
            "asset_count": 0,
            "appraised_total_cents": 0,
            "submitted_at": None,
            "reviewed_at": None,
        })
        db.turn_ins[turn_in["id"]] = turn_in
        return created(view("TurnIn", turn_in))

    @app.route("/turn-ins/<turn_in_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "SurplusAssessor", "AgencyOfficer"])
    def get_turn_in(ctx, turn_in_id):
        turn_in = rollups.fetch(db.turn_ins, turn_in_id, "ERR_TURN_IN_NOT_FOUND")
        agency_scope(ctx, turn_in["turning_in_agency_id"])
        return ok(view("TurnIn", turn_in))

    @app.route("/turn-ins", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "SurplusAssessor"])
    def list_turn_ins(ctx):
        filters, limit, offset = list_params({"status": TURN_IN_STATUS})
        plain = plain_filters(["turning_in_agency_id"])
        rows = by_created(db.turn_ins.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("TurnIn", rows), limit, offset)

    @app.route("/turn-ins/<turn_in_id>/submit", methods=["POST"])
    @endpoint(["AgencyOfficer", "ProgramAdmin"])
    def submit_turn_in(ctx, turn_in_id):
        read_body()
        turn_in = rollups.fetch(db.turn_ins, turn_in_id, "ERR_TURN_IN_NOT_FOUND")
        agency_scope(ctx, turn_in["turning_in_agency_id"])
        if turn_in["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE",
                           "only a DRAFT turn-in may be submitted")
        if len(rollups.assets_of_turn_in(turn_in["id"])) < 1:
            raise ApiError("ERR_TURN_IN_NOT_ASSESSED",
                           "a turn-in must carry at least one asset to be submitted")
        turn_in["status"] = "SUBMITTED"
        turn_in["submitted_at"] = store.iso(store.db.now)
        ctx.touch(turn_in)
        return ok(view("TurnIn", turn_in))

    @app.route("/turn-ins/<turn_in_id>/review", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def review_turn_in(ctx, turn_in_id):
        body = read_body()
        f = Fields(body)
        f.enum("decision", REVIEW_DECISION, required=True)
        f.string("rejection_reason", minlen=1)
        f.done()
        if f["decision"] == "REJECT" and f["rejection_reason"] is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "'rejection_reason' is required when rejecting a turn-in")
        turn_in = rollups.fetch(db.turn_ins, turn_in_id, "ERR_TURN_IN_NOT_FOUND")
        if turn_in["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE",
                           "only a SUBMITTED turn-in may be reviewed")
        children = rollups.assets_of_turn_in(turn_in["id"])
        if f["decision"] == "ACCEPT":
            for asset in children:
                if asset["disposition_status"] == "INTAKE":
                    raise ApiError("ERR_TURN_IN_NOT_ASSESSED",
                                   "every asset on the turn-in must be assessed "
                                   "before acceptance")
            turn_in["status"] = "ACCEPTED"
            turn_in["reviewed_at"] = store.iso(store.db.now)
            rollups.recompute_turn_in(turn_in, ctx)
            ctx.touch(turn_in)
        else:
            turn_in["status"] = "REJECTED"
            turn_in["reviewed_at"] = store.iso(store.db.now)
            turn_in["rejection_reason"] = f["rejection_reason"]
            ctx.touch(turn_in)
            for asset in children:
                if asset["disposition_status"] in ("INTAKE", "ASSESSED"):
                    asset["disposition_status"] = "RETAINED"
                    ctx.touch(asset)
        return ok(view("TurnIn", turn_in))
