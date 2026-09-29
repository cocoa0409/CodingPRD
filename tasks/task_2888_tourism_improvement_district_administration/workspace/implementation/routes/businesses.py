"""Lodging business reads and writes (PRD 3.1)."""
from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate, require_owner
from errors import fail
from routes.common import ADMIN, AUDITOR, BOARD, DMO, HEARING, OPERATOR, narrow
from services import core
from store import put, touch

bp = Blueprint("businesses", __name__)

BLOCKING_PAYMENT_STATUSES = ("UNPAID", "PARTIALLY_PAID", "DELINQUENT")


def _email(value, field="operator_contact_email"):
    if not value.strip() or "@" not in value:
        fail("ERR_INVALID_REQUEST", "%s must be non-blank and contain an at-sign." % field)
    return value


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/lodging-businesses/<business_id>")
def read_business(business_id):
    actor = authenticate([ADMIN, BOARD, AUDITOR, HEARING, OPERATOR])
    business = validate.business(business_id)
    require_owner(actor, business["id"])
    return envelope.ok(serialize.business(business))


@bp.get("/lodging-businesses/<business_id>/petition-signatures")
def list_business_signatures(business_id):
    actor = authenticate([ADMIN, BOARD, AUDITOR, OPERATOR])
    business = validate.business(business_id)
    require_owner(actor, business["id"])
    status = envelope.enum_filter("status", config.SIGNATURE_STATUSES)
    records = narrow(core.signatures_of_business(business["id"]), status=status)
    return envelope.paginate(records, serialize.signature)


@bp.get("/lodging-businesses/<business_id>/assessment-statements")
def list_business_statements(business_id):
    actor = authenticate([ADMIN, AUDITOR, HEARING, OPERATOR])
    business = validate.business(business_id)
    require_owner(actor, business["id"])
    payment_status = envelope.enum_filter("payment_status", config.PAYMENT_STATUSES)
    filing_status = envelope.enum_filter("filing_status", config.FILING_STATUSES)
    records = narrow(core.statements_of_business(business["id"]),
                     payment_status=payment_status, filing_status=filing_status)
    return envelope.paginate(records, serialize.statement)


@bp.get("/lodging-businesses/<business_id>/room-night-claims")
def list_business_claims(business_id):
    actor = authenticate([ADMIN, DMO, AUDITOR, OPERATOR])
    business = validate.business(business_id)
    require_owner(actor, business["id"])
    status = envelope.enum_filter("status", config.CLAIM_STATUSES)
    records = narrow(core.claims_of_business(business["id"]), status=status)
    return envelope.paginate(records, serialize.claim)


@bp.get("/lodging-businesses/<business_id>/disputes")
def list_business_disputes(business_id):
    actor = authenticate([ADMIN, HEARING, AUDITOR, OPERATOR])
    business = validate.business(business_id)
    require_owner(actor, business["id"])
    status = envelope.enum_filter("status", config.DISPUTE_STATUSES)
    dispute_type = envelope.enum_filter("dispute_type", config.DISPUTE_TYPES)
    records = narrow(core.disputes_of_business(business["id"]),
                     status=status, dispute_type=dispute_type)
    return envelope.paginate(records, serialize.dispute)


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@bp.post("/lodging-businesses")
def create_business():
    authenticate([ADMIN])
    b = validate.body()

    district_id = validate.id_ref(b, "district_id")
    legal_name = validate.text(b, "legal_name", max_len=120)
    if not legal_name.strip():
        fail("ERR_INVALID_REQUEST", "legal_name may not be blank.")
    zone = validate.enum(b, "boundary_zone", config.ZONES)
    classification = validate.enum(b, "classification", config.CLASSIFICATIONS)
    room_count = validate.integer(b, "room_count", minimum=1)
    revenue = validate.cents(b, "prior_year_gross_room_revenue_cents")
    email = _email(validate.text(b, "operator_contact_email"))
    exempt_status = validate.enum(b, "exempt_status", config.EXEMPT_STATUSES,
                                  required=False, default="NONE")
    frequency = validate.enum(b, "remittance_frequency", config.REMITTANCE_FREQUENCIES,
                              required=False, default="MONTHLY")

    district = validate.district(district_id)

    status, exempt_status = core.resolve_business_status(
        district, exempt_status, room_count, zone)

    rec = store.new_record("business")
    rec.update({
        "district_id": district["id"],
        "legal_name": legal_name,
        "boundary_zone": zone,
        "classification": classification,
        "room_count": room_count,
        "prior_year_gross_room_revenue_cents": revenue,
        "exempt_status": exempt_status,
        "status": status,
        "remittance_frequency": frequency,
        "delinquency_strike_count": 0,
        "compliance_standing": "GOOD",
        "operator_contact_email": email,
    })
    put("businesses", rec)

    core.recompute_district_aggregates(district)
    core.rescore_open_drives(district)
    return envelope.created(serialize.business(rec))


@bp.post("/lodging-businesses/<business_id>/revisions")
def revise_business(business_id):
    authenticate([ADMIN])
    b = validate.body()

    zone = validate.enum(b, "boundary_zone", config.ZONES, required=False)
    classification = validate.enum(b, "classification", config.CLASSIFICATIONS, required=False)
    room_count = validate.integer(b, "room_count", required=False, minimum=1)
    revenue = validate.cents(b, "prior_year_gross_room_revenue_cents", required=False)
    exempt_status = validate.enum(b, "exempt_status", config.EXEMPT_STATUSES, required=False)
    frequency = validate.enum(b, "remittance_frequency", config.REMITTANCE_FREQUENCIES,
                              required=False)
    email = validate.text(b, "operator_contact_email", required=False)
    if email is not None:
        _email(email)
    close_out = validate.flag(b, "close_out", default=False)

    business = validate.business(business_id)
    district = store.state.districts[business["district_id"]]
    previous_status = business["status"]

    if previous_status == "CLOSED_OUT":
        fail("ERR_INVALID_STATE_TRANSITION", "A CLOSED_OUT property accepts no revision.")

    if close_out:
        for statement in core.statements_of_business(business["id"]):
            if (statement["payment_status"] in BLOCKING_PAYMENT_STATUSES
                    and statement["total_due_cents"] > 0):
                fail("ERR_INVALID_STATE_TRANSITION",
                     "The property still owes money on at least one statement.")

    if zone is not None:
        business["boundary_zone"] = zone
    if classification is not None:
        business["classification"] = classification
    if room_count is not None:
        business["room_count"] = room_count
    if revenue is not None:
        business["prior_year_gross_room_revenue_cents"] = revenue
    if exempt_status is not None:
        business["exempt_status"] = exempt_status
    if frequency is not None:
        business["remittance_frequency"] = frequency
    if email is not None:
        business["operator_contact_email"] = email

    if close_out:
        business["status"] = "CLOSED_OUT"
        touch(business)
        core.recompute_district_aggregates(district)
        core.rescore_open_drives(district)
        return envelope.ok(serialize.business(business))

    status, resolved_exempt = core.resolve_business_status(
        district, business["exempt_status"], business["room_count"], business["boundary_zone"])
    business["exempt_status"] = resolved_exempt
    business["status"] = status
    touch(business)

    core.apply_status_cascade(business, district, previous_status)
    return envelope.ok(serialize.business(business))
