"""Agency registry endpoints (PRD section 3.1)."""
import db as store
from db import db, by_created, iso_date
from errors import ApiError
from middleware import Fields, agency_scope, endpoint, list_params, plain_filters, read_body
from response import collection, created, ok
from services import rollups
from services.enums import AGENCY_STATUS, AGENCY_TYPE, DONEE_STATUS
from services.serialize import view, views


def register(app):

    @app.route("/agencies", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def create_agency(ctx):
        body = read_body()
        f = Fields(body)
        f.string("name", required=True, minlen=1, maxlen=160)
        f.string("agency_code", required=True, minlen=1, maxlen=24)
        f.enum("agency_type", AGENCY_TYPE, required=True)
        f.enum("federal_donee_status", DONEE_STATUS, default="NONE")
        f.date("donee_certification_expires_on")
        f.done()
        if f["federal_donee_status"] == "CERTIFIED" and f["donee_certification_expires_on"] is None:
            raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                           "donee_certification_expires_on is required when "
                           "federal_donee_status is CERTIFIED")
        for row in db.agencies.values():
            if row["agency_code"] == f["agency_code"]:
                raise ApiError("ERR_DUPLICATE_AGENCY_CODE",
                               "agency_code is already registered")
        expires = f["donee_certification_expires_on"]
        if f["federal_donee_status"] == "NONE":
            expires = None
        agency = store.base_row()
        agency.update({
            "name": f["name"],
            "agency_code": f["agency_code"],
            "agency_type": f["agency_type"],
            "status": "ACTIVE",
            "federal_donee_status": f["federal_donee_status"],
            "donee_certification_expires_on": iso_date(expires),
            "proceeds_account_balance_cents": 0,
            "posted_distribution_count": 0,
        })
        db.agencies[agency["id"]] = agency
        return created(view("Agency", agency))

    @app.route("/agencies/<agency_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "AgencyOfficer"])
    def get_agency(ctx, agency_id):
        agency_scope(ctx, agency_id)
        agency = rollups.fetch(db.agencies, agency_id, "ERR_AGENCY_NOT_FOUND")
        return ok(view("Agency", agency))

    @app.route("/agencies", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController"])
    def list_agencies(ctx):
        filters, limit, offset = list_params({
            "agency_type": AGENCY_TYPE,
            "status": AGENCY_STATUS,
            "federal_donee_status": DONEE_STATUS,
        })
        rows = by_created(db.agencies.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("Agency", rows), limit, offset)

    @app.route("/agencies/<agency_id>/status", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def set_agency_status(ctx, agency_id):
        body = read_body()
        f = Fields(body)
        f.enum("status", AGENCY_STATUS, required=True)
        f.done()
        agency = rollups.fetch(db.agencies, agency_id, "ERR_AGENCY_NOT_FOUND")
        target = f["status"]
        if agency["status"] == target:
            raise ApiError("ERR_INVALID_STATE",
                           "the agency is already " + target)
        agency["status"] = target
        ctx.touch(agency)
        return ok(view("Agency", agency))

    @app.route("/agencies/<agency_id>/donee-certification", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def set_donee_certification(ctx, agency_id):
        body = read_body()
        f = Fields(body)
        f.enum("federal_donee_status", DONEE_STATUS, required=True)
        f.date("donee_certification_expires_on")
        f.done()
        agency = rollups.fetch(db.agencies, agency_id, "ERR_AGENCY_NOT_FOUND")
        agency["federal_donee_status"] = f["federal_donee_status"]
        if f["federal_donee_status"] == "NONE":
            agency["donee_certification_expires_on"] = None
        elif f["donee_certification_expires_on"] is not None:
            agency["donee_certification_expires_on"] = iso_date(
                f["donee_certification_expires_on"])
        ctx.touch(agency)
        return ok(view("Agency", agency))
