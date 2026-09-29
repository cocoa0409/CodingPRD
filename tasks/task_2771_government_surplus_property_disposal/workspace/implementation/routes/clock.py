"""Logical-clock control surface (PRD section 2.4)."""
import db as store
from middleware import Fields, endpoint, read_body
from response import ok


def register(app):

    @app.route("/_clock/set_current_utc", methods=["POST"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController",
               "ClearanceTechnician", "SurplusAssessor", "AgencyOfficer",
               "Bidder"])
    def set_current_utc(ctx):
        body = read_body()
        f = Fields(body)
        f.instant("current_utc", required=True)
        f.done()
        store.db.now = f["current_utc"]
        return ok({})
