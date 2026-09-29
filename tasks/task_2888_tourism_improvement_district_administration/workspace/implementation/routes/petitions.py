"""Petition drives and signatures (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate, require_owner
from errors import fail
from routes.common import ADMIN, AUDITOR, BOARD, OPERATOR, VIEWER, narrow
from services import core
from store import put, touch

bp = Blueprint("petitions", __name__)


def _pool_floor(district):
    if len(core.assessable_members(district)) < config.MIN_PETITION_POOL:
        fail("ERR_PETITION_POOL_TOO_SMALL",
             "The eligible assessable pool must hold at least %d businesses."
             % config.MIN_PETITION_POOL)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/petition-drives/<drive_id>")
def read_drive(drive_id):
    authenticate([ADMIN, BOARD, AUDITOR, VIEWER, OPERATOR], public=True)
    return envelope.ok(serialize.drive(validate.drive(drive_id)))


@bp.get("/petition-drives/<drive_id>/signatures")
def list_drive_signatures(drive_id):
    authenticate([ADMIN, BOARD, AUDITOR])
    drive = validate.drive(drive_id)
    status = envelope.enum_filter("status", config.SIGNATURE_STATUSES)
    records = narrow(core.signatures_of_drive(drive["id"]), status=status)
    return envelope.paginate(records, serialize.signature)


@bp.get("/petition-signatures/<signature_id>")
def read_signature(signature_id):
    authenticate([ADMIN, BOARD, AUDITOR, OPERATOR])
    return envelope.ok(serialize.signature(validate.signature(signature_id)))


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@bp.post("/petition-drives")
def open_drive():
    authenticate([ADMIN])
    b = validate.body()
    district_id = validate.id_ref(b, "district_id")
    drive_type = validate.enum(b, "drive_type", config.DRIVE_TYPES)
    closes_at = validate.instant(b, "closes_at")

    district = validate.district(district_id)
    if district["status"] in config.DISTRICT_TERMINAL:
        fail("ERR_DISTRICT_NOT_ACTIVE",
             "A district in %s accepts no new petition drive." % district["status"])

    now = store.clock()
    if drive_type == "FORMATION":
        if district["status"] != "PROPOSED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A formation drive may be opened only on a PROPOSED district.")
        if core.open_drives_of_district(district["id"]):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Another petition drive of this district is still OPEN.")
        if district["assessable_business_count"] < config.MIN_PETITION_POOL:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "At least %d assessable businesses are required to petition."
                 % config.MIN_PETITION_POOL)
        required_weighted = district["formation_threshold_pct"]
        required_headcount = Decimal("0.0000")
    else:
        expiry = district["expiration_date"]
        window_open = store.add_days(expiry, -config.RENEWAL_WINDOW_DAYS) if expiry else None
        if expiry is None or now < window_open or now >= expiry:
            fail("ERR_RENEWAL_WINDOW_NOT_OPEN",
                 "A renewal drive may open only inside the %d-day renewal window."
                 % config.RENEWAL_WINDOW_DAYS)
        required_weighted = district["renewal_threshold_pct"]
        required_headcount = district["renewal_headcount_threshold_pct"]

    rec = store.new_record("drive")
    rec.update({
        "district_id": district["id"],
        "drive_type": drive_type,
        "status": "OPEN",
        "opened_on": now,
        "required_weighted_pct": required_weighted,
        "required_headcount_pct": required_headcount,
        "signed_basis_cents": 0,
        "valid_signature_count": 0,
        "assessable_basis_snapshot_cents": 0,
        "assessable_count_snapshot": 0,
        "weighted_support_pct": Decimal("0.0000"),
        "headcount_support_pct": Decimal("0.0000"),
        "short_reason": "NONE",
        "tallied_at": None,
    })
    validate.assign(rec, "closes_at", closes_at)
    put("drives", rec)
    core.recompute_support(rec)

    if drive_type == "FORMATION":
        district["status"] = "PETITION_CIRCULATING"
        touch(district)
    return envelope.created(serialize.drive(rec))


@bp.post("/petition-drives/<drive_id>/signatures")
def sign_drive(drive_id):
    actor = authenticate([ADMIN, OPERATOR])
    b = validate.body()
    business_id = validate.id_ref(b, "lodging_business_id")
    drive = validate.drive(drive_id)
    business = validate.business(business_id)
    require_owner(actor, business["id"])

    if drive["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "The drive is no longer OPEN.")

    now = store.clock()
    if now < drive["opened_on"] or now >= drive["closes_at"]:
        fail("ERR_PETITION_WINDOW_CLOSED",
             "The signature window runs from opened_on up to but not including closes_at.")

    district = store.state.districts[drive["district_id"]]
    if business["district_id"] != district["id"]:
        fail("ERR_BUSINESS_OUTSIDE_BOUNDARY",
             "The signer does not belong to the district of this drive.")
    if business["exempt_status"] != "NONE" or business["status"] == "EXEMPT":
        fail("ERR_BUSINESS_EXEMPT", "An exempt property holds no petition standing.")
    if (business["boundary_zone"] not in district["included_zones"]
            or business["status"] != "ASSESSABLE"):
        fail("ERR_BUSINESS_OUTSIDE_BOUNDARY",
             "The signer must be ASSESSABLE and sit inside the district boundary.")
    for existing in core.signatures_of_drive(drive["id"]):
        if existing["lodging_business_id"] == business["id"] and existing["status"] == "VALID":
            fail("ERR_DUPLICATE_SIGNATURE",
                 "This property already holds a VALID signature on the drive.")

    rec = store.new_record("signature")
    rec.update({
        "petition_drive_id": drive["id"],
        "lodging_business_id": business["id"],
        "signed_at": now,
        "weight_basis_revenue_cents": business["prior_year_gross_room_revenue_cents"],
        "status": "VALID",
        "disqualification_reason": "NONE",
    })
    put("signatures", rec)

    core.recompute_support(drive)
    touch(drive)
    return envelope.created(serialize.signature(rec))


@bp.post("/petition-signatures/<signature_id>/withdrawal")
def withdraw_signature(signature_id):
    actor = authenticate([ADMIN, OPERATOR])
    b = validate.body()
    validate.text(b, "reason", required=False)
    signature = validate.signature(signature_id)
    require_owner(actor, signature["lodging_business_id"])

    if signature["status"] != "VALID":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a VALID signature may be withdrawn.")
    drive = store.state.drives[signature["petition_drive_id"]]
    if drive["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "The owning drive is no longer OPEN.")
    if store.clock() >= drive["closes_at"]:
        fail("ERR_PETITION_WINDOW_CLOSED", "The signature window has closed.")

    signature["status"] = "WITHDRAWN"
    touch(signature)
    core.recompute_support(drive)
    touch(drive)
    return envelope.ok(serialize.signature(signature))


@bp.post("/petition-drives/<drive_id>/tally")
def tally_drive(drive_id):
    authenticate([ADMIN])
    validate.body()
    drive = validate.drive(drive_id)
    if drive["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an OPEN drive may be tallied.")
    district = store.state.districts[drive["district_id"]]
    _pool_floor(district)

    core.recompute_support(drive)
    drive["tallied_at"] = store.clock()
    drive["_raw"].pop("tallied_at", None)

    weighted_short = drive["weighted_support_pct"] < drive["required_weighted_pct"]
    headcount_short = drive["headcount_support_pct"] < drive["required_headcount_pct"]
    if not weighted_short and not headcount_short:
        drive["status"] = "QUALIFIED"
        drive["short_reason"] = "NONE"
    else:
        drive["status"] = "SHORT_OF_THRESHOLD"
        drive["short_reason"] = ("WEIGHTED_BELOW_THRESHOLD" if weighted_short
                                 else "HEADCOUNT_BELOW_MINIMUM")
        if drive["drive_type"] == "FORMATION":
            district["status"] = "FORMATION_FAILED"
            touch(district)
    touch(drive)
    return envelope.ok(serialize.drive(drive))


@bp.post("/petition-drives/<drive_id>/certification")
def certify_drive(drive_id):
    authenticate([ADMIN])
    b = validate.body()
    validate.instant(b, "certified_on", required=False)
    drive = validate.drive(drive_id)

    if drive["status"] != "QUALIFIED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a QUALIFIED drive may be certified.")
    district = store.state.districts[drive["district_id"]]
    expected = "PETITION_CIRCULATING" if drive["drive_type"] == "FORMATION" else "RENEWAL_PENDING"
    if district["status"] != expected:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The district must be %s to certify a %s drive." % (expected, drive["drive_type"]))
    if drive["drive_type"] == "RENEWAL":
        core.transparency_gate(district)
    _pool_floor(district)

    drive["status"] = "CERTIFIED"
    touch(drive)

    now = store.clock()
    if drive["drive_type"] == "FORMATION":
        district["status"] = "FORMED"
        district["formed_on"] = now
        district["_raw"].pop("formed_on", None)
        district["expiration_date"] = store.add_years(now, district["term_years"])
        district["_raw"].pop("expiration_date", None)
    else:
        district["status"] = "ACTIVE"
        district["expiration_date"] = store.add_years(
            district["expiration_date"], district["term_years"])
        district["_raw"].pop("expiration_date", None)
        district["current_fiscal_year"] = district["current_fiscal_year"] + 1
    touch(district)
    return envelope.ok(serialize.drive(drive))
