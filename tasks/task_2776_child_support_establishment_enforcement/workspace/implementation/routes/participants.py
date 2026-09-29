"""Participant intake, income maintenance and locate results (PRD 3.1)."""
import common
import db
import middleware
import response
import serialize
import validate
from common import PREFIX
from services import risk

ROLE_TYPES = ("CUSTODIAL_PARTY", "NONCUSTODIAL_PARTY")
INCOME_SOURCES = ("VERIFIED_WAGE_RECORD", "SELF_REPORTED", "NONE")
LOCATE_OUTCOMES = ("LOCATED", "UNLOCATABLE")

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "InterstateLiaison", "ProgramAdmin", "CustodialParty",
              "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "FinanceOfficer",
              "InterstateLiaison", "ProgramAdmin"]


def _state_code(payload, key, required=True):
    if required:
        value = validate.req_str(payload, key)
    else:
        value = validate.opt_str(payload, key)
        if value is None:
            return None
    if value not in db.STATE_CODES:
        validate.fail("%s must be one of %s." % (key, ", ".join(db.STATE_CODES)))
    return value


def register(app):
    @app.post(PREFIX + "/participants")
    def create_participant():
        middleware.authenticate(["CaseWorker"])
        payload = validate.body()
        role_type = validate.req_enum(payload, "role_type", ROLE_TYPES)
        full_name = validate.req_str(payload, "full_name", 1, 120)
        ssn_last4 = validate.req_str(payload, "ssn_last4")
        if len(ssn_last4) != 4 or not ssn_last4.isdigit():
            validate.fail("ssn_last4 must be exactly four digits.")
        residence = _state_code(payload, "residence_state_code")
        employer_name = validate.opt_str(payload, "employer_name")
        income = validate.opt_money(payload, "monthly_gross_income_cents")
        source = validate.opt_enum(payload, "income_verification_source",
                                   INCOME_SOURCES, "NONE")
        second_family = validate.opt_bool(payload, "supports_second_family", False)
        licensed = validate.opt_bool(payload, "has_valid_drivers_license", True)

        row = db.stamp_new({
            "role_type": role_type,
            "full_name": full_name,
            "ssn_last4": ssn_last4,
            "residence_state_code": residence,
            "employer_name": employer_name,
            "monthly_gross_income_cents": income,
            "income_verification_source": source,
            "supports_second_family": second_family,
            "has_valid_drivers_license": licensed,
            "locate_status": "NOT_NEEDED",
            "locate_attempt_count": 0,
            "license_suspension_active": False,
            "lien_recorded": False,
            "credit_bureau_reported": False,
        })
        db.participants[row["id"]] = row
        return response.created(serialize.participant(row))

    @app.get(PREFIX + "/participants/<participant_id>")
    def read_participant(participant_id):
        middleware.authenticate(READ_ROLES)
        row = common.participant(participant_id)
        middleware.require_participant_visibility(row)
        return response.ok(serialize.participant(row))

    @app.get(PREFIX + "/participants")
    def list_participants():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.participants.values()))
        rows = common.apply_filters(rows, [
            ("role_type", "role_type", "str"),
            ("residence_state_code", "residence_state_code", "str"),
            ("locate_status", "locate_status", "str"),
        ])
        tier = common.qp("enforcement_risk_tier")
        if tier is not None:
            rows = [r for r in rows if risk.scores(r)[1] == tier]
        return response.paginate(rows, serialize.participant)

    @app.patch(PREFIX + "/participants/<participant_id>/income")
    def update_income(participant_id):
        middleware.authenticate(["CaseWorker"])
        row = common.participant(participant_id)
        payload = validate.body()
        income = validate.req_money(payload, "monthly_gross_income_cents")
        source = validate.req_enum(payload, "income_verification_source",
                                   INCOME_SOURCES)
        employer_name = validate.opt_str(payload, "employer_name")
        row["monthly_gross_income_cents"] = income
        row["income_verification_source"] = source
        if employer_name is not None:
            row["employer_name"] = employer_name
        db.touch(row)
        return response.ok(serialize.participant(row))

    @app.post(PREFIX + "/participants/<participant_id>/locate-results")
    def record_locate_result(participant_id):
        middleware.authenticate(["CaseWorker"])
        row = common.participant(participant_id)
        payload = validate.body()
        outcome = validate.req_enum(payload, "locate_outcome", LOCATE_OUTCOMES)
        employer_name = validate.opt_str(payload, "employer_name")
        row["locate_status"] = outcome
        if employer_name is not None:
            row["employer_name"] = employer_name
        db.touch(row)
        return response.ok(serialize.participant(row))
