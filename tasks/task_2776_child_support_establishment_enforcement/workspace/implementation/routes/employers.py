"""Employer registry (PRD 3.4)."""
import re

import common
import db
import middleware
import response
import serialize
import validate
from common import PREFIX
from services import withholding

FEIN_PATTERN = re.compile(r"^[0-9]{2}-[0-9]{7}$")
PAY_FREQUENCIES = ("WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY")
MAX_REMITTANCE_FEE_CENTS = 500

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "ProgramAdmin", "EmployerAgent"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer", "ProgramAdmin"]


def register(app):
    @app.post(PREFIX + "/employers")
    def create_employer():
        middleware.authenticate(["ProgramAdmin"])
        payload = validate.body()
        legal_name = validate.req_str(payload, "legal_name", 1, 200)
        fein = validate.req_str(payload, "fein")
        if not FEIN_PATTERN.match(fein):
            validate.fail("fein must match ^[0-9]{2}-[0-9]{7}$.")
        state_code = validate.req_str(payload, "state_code")
        if state_code not in db.STATE_CODES:
            validate.fail("state_code must be one of %s." % ", ".join(db.STATE_CODES))
        pay_frequency = validate.req_enum(payload, "pay_frequency", PAY_FREQUENCIES)
        fee = validate.opt_int(payload, "remittance_fee_cents", 0, 0,
                               MAX_REMITTANCE_FEE_CENTS)
        if any(e["fein"] == fein for e in db.employers.values()):
            validate.fail("fein must be unique across employers.")

        row = db.stamp_new({
            "legal_name": legal_name,
            "fein": fein,
            "state_code": state_code,
            "pay_frequency": pay_frequency,
            "remittance_fee_cents": fee,
            "statutory_cap_pct": withholding.statutory_cap_pct(state_code),
            "active_iwo_count": 0,
        })
        db.employers[row["id"]] = row
        return response.created(serialize.employer(row))

    @app.get(PREFIX + "/employers/<employer_id>")
    def read_employer(employer_id):
        middleware.authenticate(READ_ROLES)
        row = common.employer(employer_id)
        middleware.require_employer_self(row["id"])
        return response.ok(serialize.employer(row))

    @app.get(PREFIX + "/employers")
    def list_employers():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.employers.values()))
        rows = common.apply_filters(rows, [
            ("state_code", "state_code", "str"),
            ("fein", "fein", "str"),
        ])
        return response.paginate(rows, serialize.employer)
