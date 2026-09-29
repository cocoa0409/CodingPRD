"""Assessment statements: the filing dimension and the remittance waterfall."""
from decimal import Decimal

from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate, require_owner
from errors import fail
from routes.common import ADMIN, AUDITOR, HEARING, OPERATOR, narrow
from services import core, plans as planservice
from store import put, set_if_changed, touch

bp = Blueprint("statements", __name__)


def _filing_window(statement):
    """Rung 10 for filings and amendments (PRD 3.3)."""
    period = core.period_of_statement(statement)
    if period["status"] != "OPEN" or store.clock() > period["due_date"]:
        fail("ERR_FILING_WINDOW_CLOSED",
             "The filing window of the owning period has closed.")
    return period


def _after_filing_change(statement):
    core.derive_payment_status(statement)
    touch(statement)
    core.recompute_period_billed(core.period_of_statement(statement))
    core.recompute_district_money(core.district_of_statement(statement))
    planservice.reevaluate_for_statement(statement)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/assessment-statements/<statement_id>")
def read_statement(statement_id):
    authenticate([ADMIN, AUDITOR, HEARING, OPERATOR])
    return envelope.ok(serialize.statement(validate.statement(statement_id)))


@bp.get("/assessment-statements/<statement_id>/remittances")
def list_statement_remittances(statement_id):
    authenticate([ADMIN, AUDITOR, OPERATOR])
    statement = validate.statement(statement_id)
    status = envelope.enum_filter("status", config.REMITTANCE_STATUSES)
    records = narrow(core.remittances_of_statement(statement["id"]), status=status)
    return envelope.paginate(records, serialize.remittance)


@bp.get("/assessment-statements/<statement_id>/disputes")
def list_statement_disputes(statement_id):
    authenticate([ADMIN, HEARING, AUDITOR, OPERATOR])
    statement = validate.statement(statement_id)
    status = envelope.enum_filter("status", config.DISPUTE_STATUSES)
    dispute_type = envelope.enum_filter("dispute_type", config.DISPUTE_TYPES)
    records = narrow(core.disputes_of_statement(statement["id"]),
                     status=status, dispute_type=dispute_type)
    return envelope.paginate(records, serialize.dispute)


@bp.get("/remittances/<remittance_id>")
def read_remittance(remittance_id):
    authenticate([ADMIN, AUDITOR, OPERATOR])
    return envelope.ok(serialize.remittance(validate.remittance(remittance_id)))


# ---------------------------------------------------------------------------
# the filing dimension
# ---------------------------------------------------------------------------
@bp.post("/assessment-statements/<statement_id>/filings")
def file_statement(statement_id):
    actor = authenticate([OPERATOR, ADMIN])
    b = validate.body()
    nights = validate.integer(b, "reported_room_nights", minimum=0)
    revenue = validate.cents(b, "reported_gross_room_revenue_cents")
    statement = validate.statement(statement_id)
    require_owner(actor, statement["lodging_business_id"])

    if statement["filing_status"] == "CERTIFIED":
        fail("ERR_STATEMENT_ALREADY_CERTIFIED",
             "A CERTIFIED statement accepts no filing.")
    if statement["filing_status"] != "NOT_FILED":
        fail("ERR_INVALID_STATE_TRANSITION", "The statement has already been filed.")
    _filing_window(statement)

    statement["reported_room_nights"] = nights
    statement["reported_gross_room_revenue_cents"] = revenue
    statement["_original_reported_revenue_cents"] = revenue
    statement["filed_at"] = store.clock()
    statement["_raw"].pop("filed_at", None)
    statement["filing_status"] = "FILED"
    statement["provisional_assessment_cents"] = core.compute_provisional(statement)
    _after_filing_change(statement)
    return envelope.ok(serialize.statement(statement))


@bp.post("/assessment-statements/<statement_id>/amendments")
def amend_statement(statement_id):
    actor = authenticate([OPERATOR, ADMIN])
    b = validate.body()
    expected_version = validate.integer(b, "expected_statement_version")
    nights = validate.integer(b, "reported_room_nights", minimum=0)
    revenue = validate.cents(b, "reported_gross_room_revenue_cents")
    validate.text(b, "amendment_reason", required=False)
    statement = validate.statement(statement_id)
    require_owner(actor, statement["lodging_business_id"])

    if statement["filing_status"] == "CERTIFIED":
        fail("ERR_STATEMENT_ALREADY_CERTIFIED",
             "A CERTIFIED statement accepts no amendment.")
    if statement["filing_status"] not in ("FILED", "AMENDED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a FILED or AMENDED statement may be amended.")
    if statement["amendment_count"] >= config.MAX_REVISIONS:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A statement may take at most %d revisions." % config.MAX_REVISIONS)
    original = statement["_original_reported_revenue_cents"] or 0
    allowed = Decimal(original) * config.AMENDMENT_VARIANCE_PCT
    if abs(Decimal(revenue) - Decimal(original)) > allowed:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The amended revenue may deviate from the original filing by at most 25 percent.")
    if expected_version != statement["version"]:
        fail("ERR_STALE_STATEMENT_VERSION",
             "expected_statement_version %d does not match the stored version %d."
             % (expected_version, statement["version"]))
    _filing_window(statement)

    statement["reported_room_nights"] = nights
    statement["reported_gross_room_revenue_cents"] = revenue
    statement["amendment_count"] = statement["amendment_count"] + 1
    statement["filed_at"] = store.clock()
    statement["_raw"].pop("filed_at", None)
    statement["filing_status"] = "AMENDED"
    statement["provisional_assessment_cents"] = core.compute_provisional(statement)
    _after_filing_change(statement)
    return envelope.ok(serialize.statement(statement))


@bp.post("/assessment-statements/<statement_id>/audit-certification")
def audit_statement(statement_id):
    actor = authenticate([AUDITOR])
    b = validate.body()
    action = validate.enum(b, "action", config.AUDIT_ACTIONS)
    audited_nights = validate.integer(b, "audited_room_nights", required=False, minimum=0)
    audited_revenue = validate.cents(b, "audited_gross_room_revenue_cents", required=False)
    validate.text(b, "audit_note", required=False)
    statement = validate.statement(statement_id)

    if statement["filing_status"] == "CERTIFIED":
        fail("ERR_STATEMENT_ALREADY_CERTIFIED",
             "The statement is already CERTIFIED.")

    if action == "AUDIT":
        if statement["filing_status"] not in ("FILED", "AMENDED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Only a FILED or AMENDED statement may be audited.")
        period = core.period_of_statement(statement)
        if period["status"] == "OPEN":
            fail("ERR_PERIOD_NOT_CLOSED",
                 "The owning assessment period must have left OPEN.")
        if audited_nights is not None:
            statement["audited_room_nights"] = audited_nights
        if audited_revenue is not None:
            statement["audited_gross_room_revenue_cents"] = audited_revenue
        statement["audited_by_user_id"] = actor.user_id
        statement["filing_status"] = "AUDITED"
        statement["final_assessment_cents"] = core.compute_final(statement)
    else:
        if statement["filing_status"] != "AUDITED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Only an AUDITED statement may be certified.")
        live = [d for d in core.disputes_of_statement(statement["id"])
                if d["status"] in config.DISPUTE_LIVE]
        if live:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A dispute on this statement is still live.")
        if actor.user_id == statement["audited_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The certifying user must differ from the auditing user.")
        statement["filing_status"] = "CERTIFIED"

    _after_filing_change(statement)
    return envelope.ok(serialize.statement(statement))


# ---------------------------------------------------------------------------
# the payment dimension (PRD 3.4)
# ---------------------------------------------------------------------------
def _allocate(statement, amount):
    """The waterfall: interest, penalty, principal, credit.  No rounding anywhere."""
    remainder = amount
    interest_out = max(statement["interest_cents"] - statement["interest_paid_cents"], 0)
    to_interest = min(remainder, interest_out)
    remainder -= to_interest
    penalty_out = max(statement["penalty_cents"] - statement["penalty_paid_cents"], 0)
    to_penalty = min(remainder, penalty_out)
    remainder -= to_penalty
    principal_out = max(
        statement["effective_assessment_cents"] - statement["principal_paid_cents"], 0)
    to_principal = min(remainder, principal_out)
    remainder -= to_principal
    return to_interest, to_penalty, to_principal, remainder


@bp.post("/assessment-statements/<statement_id>/remittances")
def create_remittance(statement_id):
    actor = authenticate([OPERATOR, ADMIN])
    b = validate.body()
    amount = validate.cents(b, "amount_cents", minimum=1)
    received_on = validate.instant(b, "received_on")
    method = validate.enum(b, "method", config.REMITTANCE_METHODS)
    if received_on.dt > store.clock():
        fail("ERR_INVALID_REQUEST", "received_on may not be after the logical clock.")
    statement = validate.statement(statement_id)
    require_owner(actor, statement["lodging_business_id"])

    if statement["filing_status"] == "NOT_FILED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A statement must be filed before it can be paid.")
    if amount > statement["total_due_cents"] + config.OVERPAY_TOLERANCE_CENTS:
        fail("ERR_REMITTANCE_EXCEEDS_TOTAL_DUE",
             "amount_cents may exceed total_due_cents by at most %d cents."
             % config.OVERPAY_TOLERANCE_CENTS)

    to_interest, to_penalty, to_principal, to_credit = _allocate(statement, amount)

    rec = store.new_record("remittance")
    rec.update({
        "assessment_statement_id": statement["id"],
        "amount_cents": amount,
        "method": method,
        "applied_to_interest_cents": to_interest,
        "applied_to_penalty_cents": to_penalty,
        "applied_to_principal_cents": to_principal,
        "applied_to_credit_cents": to_credit,
        "status": "APPLIED",
        "reversed_on": None,
        "reversal_reason": None,
    })
    validate.assign(rec, "received_on", received_on)
    put("remittances", rec)

    statement["interest_paid_cents"] += to_interest
    statement["penalty_paid_cents"] += to_penalty
    statement["principal_paid_cents"] += to_principal
    statement["credit_balance_cents"] += to_credit
    core.derive_payment_status(statement)
    touch(statement)

    period = core.period_of_statement(statement)
    set_if_changed(period, {"collected_total_cents": period["collected_total_cents"] + amount})
    core.recompute_district_money(core.district_of_statement(statement))
    return envelope.created(serialize.remittance(rec))


@bp.post("/assessment-statements/<statement_id>/remittance-reversals")
def reverse_remittance(statement_id):
    authenticate([ADMIN])
    b = validate.body()
    remittance_id = validate.id_ref(b, "remittance_id")
    reason = validate.text(b, "reversal_reason")
    statement = validate.statement(statement_id)
    remittance = validate.remittance(remittance_id)
    if remittance["assessment_statement_id"] != statement["id"]:
        fail("ERR_REMITTANCE_NOT_FOUND",
             "The remittance does not belong to the statement in the path.")

    if statement["filing_status"] == "CERTIFIED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A remittance against a CERTIFIED statement may not be reversed.")
    if remittance["status"] != "APPLIED":
        fail("ERR_REMITTANCE_ALREADY_REVERSED", "The remittance is already REVERSED.")

    remittance["status"] = "REVERSED"
    remittance["reversed_on"] = store.clock()
    remittance["_raw"].pop("reversed_on", None)
    remittance["reversal_reason"] = reason
    touch(remittance)

    statement["interest_paid_cents"] -= remittance["applied_to_interest_cents"]
    statement["penalty_paid_cents"] -= remittance["applied_to_penalty_cents"]
    statement["principal_paid_cents"] -= remittance["applied_to_principal_cents"]
    statement["credit_balance_cents"] -= remittance["applied_to_credit_cents"]
    core.derive_payment_status(statement)
    touch(statement)

    period = core.period_of_statement(statement)
    set_if_changed(period, {
        "collected_total_cents": period["collected_total_cents"] - remittance["amount_cents"]})
    core.recompute_district_money(core.district_of_statement(statement))
    return envelope.ok(serialize.remittance(remittance))
