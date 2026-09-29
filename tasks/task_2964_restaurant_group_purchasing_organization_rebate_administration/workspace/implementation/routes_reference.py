"""Program tiers, distributors, members and authorization letters (PRD §3.1)."""

from flask import Blueprint, request

from authz import (endpoint, require_distributor_scope, require_member_scope,
                   resolve)
from envelope import created, ok
from errors import ApiError
from money import BPS_DENOMINATOR
from pageutil import paged
from serializers import dump
from shapes import Enum, Int, Instant, Str, UPPER_CODE_RE, parse_body, raw_body
from store import db, new_record, parse_instant, touch
from svc_common import (active_letters, recompute_distributor_letter_count,
                       recompute_member_letter_count)

bp = Blueprint("reference", __name__)

ALL_ROLES = ("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "MemberOperator",
             "DistributorFeed", "ManufacturerRep")

TIER_CODES = ("CORE", "PLUS", "ELITE")


def _filtered(records, spec):
    """Keep records whose fields equal the supplied query filters."""
    out = list(records)
    for field_name, arg_name in spec:
        if arg_name in request.args:
            wanted = request.args.get(arg_name)
            out = [r for r in out if r.get(field_name) == wanted]
    return out


# --------------------------------------------------------------------------
# program tiers
# --------------------------------------------------------------------------

@bp.post("/program-tiers")
@endpoint("GpoAdmin")
def create_program_tier(caller):
    body = parse_body([
        Enum("tier_code", TIER_CODES),
        Int("member_share_bps", 0, BPS_DENOMINATOR),
        Int("gpo_retention_bps", 0, BPS_DENOMINATOR),
        Int("admin_fee_bps_low", 0, BPS_DENOMINATOR),
        Int("admin_fee_bps_high", 0, BPS_DENOMINATOR),
        Int("compliance_min_ratio_bps", 0, BPS_DENOMINATOR),
        Int("markup_cap_bps", 0, BPS_DENOMINATOR),
        Int("dispute_window_days", 1, None),
        Int("reversal_posture_limit", 1, None, required=False),
    ])
    # priority 27 - the two halves of the split must add to the whole
    if body["member_share_bps"] + body["gpo_retention_bps"] != BPS_DENOMINATOR:
        raise ApiError("ERR_TIER_SPLIT_NOT_BALANCED")
    # priority 31 - tier_code unused
    for tier in db.program_tiers.values():
        if tier["tier_code"] == body["tier_code"]:
            raise ApiError("ERR_DUPLICATE_TIER_CODE")

    limit = body["reversal_posture_limit"]
    rec = new_record("ProgramTier", {
        "tier_code": body["tier_code"],
        "member_share_bps": body["member_share_bps"],
        "gpo_retention_bps": body["gpo_retention_bps"],
        "admin_fee_bps_low": body["admin_fee_bps_low"],
        "admin_fee_bps_high": body["admin_fee_bps_high"],
        "compliance_min_ratio_bps": body["compliance_min_ratio_bps"],
        "markup_cap_bps": body["markup_cap_bps"],
        "dispute_window_days": body["dispute_window_days"],
        "reversal_posture_limit": 2 if limit is None else limit,
    })
    db.program_tiers[rec["id"]] = rec
    return created(dump(rec))


@bp.get("/program-tiers/<tier_id>")
@endpoint(*ALL_ROLES)
def get_program_tier(caller, tier_id):
    return ok(dump(resolve("tier", tier_id)))


@bp.get("/program-tiers")
@endpoint(*ALL_ROLES)
def list_program_tiers(caller):
    return paged(_filtered(db.program_tiers.values(),
                           [("tier_code", "tier_code")]))


# --------------------------------------------------------------------------
# distributors
# --------------------------------------------------------------------------

@bp.post("/distributors")
@endpoint("GpoAdmin")
def create_distributor(caller):
    body = parse_body([
        Str("name", 1, 200),
        Str("dba_code", 3, 20, UPPER_CODE_RE),
        Int("contracted_markup_bps", 0, BPS_DENOMINATOR),
    ])
    # priority 30 - dba_code unused across all distributors
    for dist in db.distributors.values():
        if dist["dba_code"] == body["dba_code"]:
            raise ApiError("ERR_DUPLICATE_DBA_CODE")

    rec = new_record("Distributor", {
        "name": body["name"],
        "dba_code": body["dba_code"],
        "contracted_markup_bps": body["contracted_markup_bps"],
        "status": "ACTIVE",
        "active_letter_count": 0,
        "overbilled_recovered_cents": 0,
    })
    db.distributors[rec["id"]] = rec
    return created(dump(rec))


@bp.get("/distributors/<distributor_id>")
@endpoint(*ALL_ROLES)
def get_distributor(caller, distributor_id):
    return ok(dump(resolve("distributor", distributor_id)))


@bp.get("/distributors")
@endpoint(*ALL_ROLES)
def list_distributors(caller):
    return paged(_filtered(db.distributors.values(),
                           [("status", "status"), ("dba_code", "dba_code")]))


# --------------------------------------------------------------------------
# members
# --------------------------------------------------------------------------

@bp.post("/members")
@endpoint("GpoAdmin")
def create_member(caller):
    body = parse_body([
        Str("legal_name", 1, 200),
        Str("tier_id"),
        Int("committed_annual_spend_cents", 1, None),
    ])
    resolve("tier", body["tier_id"])  # priority 9

    rec = new_record("Member", {
        "legal_name": body["legal_name"],
        "tier_id": body["tier_id"],
        "committed_annual_spend_cents": body["committed_annual_spend_cents"],
        "enrollment_status": "PENDING",
        "reconciliation_posture": "CLEAR",
        "payout_hold": False,
        "active_letter_count": 0,
        "accrued_member_share_cents": 0,
        "attributed_gpo_retention_cents": 0,
        "attributed_admin_fee_cents": 0,
        "ytd_net_snapshot_cents": 0,
        "dispute_reversal_count": 0,
        "recovery_credit_cents": 0,
    })
    db.members[rec["id"]] = rec
    return created(dump(rec))


@bp.get("/members/<member_id>")
@endpoint("GpoAdmin", "RebateAnalyst", "DisputeArbiter", "MemberOperator")
def get_member(caller, member_id):
    return ok(dump(resolve("member", member_id)))


@bp.get("/members")
@endpoint("GpoAdmin", "RebateAnalyst", "DisputeArbiter")
def list_members(caller):
    records = _filtered(db.members.values(),
                        [("tier_id", "tier_id"),
                         ("enrollment_status", "enrollment_status"),
                         ("reconciliation_posture", "reconciliation_posture")])
    return paged(records)


@bp.post("/members/<member_id>/activate")
@endpoint("GpoAdmin")
def activate_member(caller, member_id):
    member = resolve("member", member_id)
    # priority 11 - PENDING activates, SUSPENDED reinstates; ACTIVE/TERMINATED refused
    if member["enrollment_status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    # priority 35 - at least one ACTIVE authorization letter
    if member["active_letter_count"] < 1:
        raise ApiError("ERR_MEMBER_HAS_NO_ACTIVE_LOA")

    was_suspended = member["enrollment_status"] == "SUSPENDED"
    member["enrollment_status"] = "ACTIVE"
    if was_suspended:
        # Reinstatement clears the payout hold but never the posture: RESTRICTED
        # is one-way and survives every subsequent reinstatement.
        member["payout_hold"] = False
    touch(member)
    return ok(dump(member))


@bp.post("/members/<member_id>/terminate")
@endpoint("GpoAdmin")
def terminate_member(caller, member_id):
    member = resolve("member", member_id)
    if member["enrollment_status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE")

    member["enrollment_status"] = "TERMINATED"
    member["payout_hold"] = True
    touch(member)

    # hop 1 - every ACTIVE letter of the member moves ACTIVE -> REVOKED
    affected_distributors = {}
    for letter in active_letters(member_id=member["id"]):
        letter["status"] = "REVOKED"
        touch(letter)
        dist = db.distributors.get(letter["distributor_id"])
        if dist is not None:
            affected_distributors[dist["id"]] = dist

    # hop 2 - recompute both sides' active_letter_count from current facts
    recompute_member_letter_count(member)
    for dist in affected_distributors.values():
        recompute_distributor_letter_count(dist)

    return ok(dump(member))


# --------------------------------------------------------------------------
# authorization letters
# --------------------------------------------------------------------------

LETTER_SCOPES = ("PURCHASE_DATA_ONLY", "PURCHASE_DATA_AND_PRICING")


def _canonical_instant(text):
    """Store letter effectivity as an ISO 8601 UTC instant with 3 fractional digits."""
    from store import iso_instant
    return iso_instant(parse_instant(text))


@bp.post("/authorization-letters")
@endpoint("MemberOperator", "GpoAdmin")
def create_authorization_letter(caller):
    # priority 5 - a MemberOperator may only submit for itself; the PRD orders the
    # scope check ahead of body-shape validation, so the raw body is read here.
    require_member_scope(caller, raw_body().get("member_id"))

    body = parse_body([
        Str("member_id"),
        Str("distributor_id"),
        Instant("effective_from"),
        Instant("effective_to"),
        Str("signatory_name", 1, 120),
        Enum("scope", LETTER_SCOPES),
    ])
    resolve("member", body["member_id"])            # priority 9, declared order
    resolve("distributor", body["distributor_id"])

    new_from = parse_instant(body["effective_from"])
    new_to = parse_instant(body["effective_to"])

    # priority 19 - half-open overlap against SUBMITTED or ACTIVE letters for the
    # same pairing.  Windows that merely touch do not overlap.
    for letter in db.letters.values():
        if letter["member_id"] != body["member_id"]:
            continue
        if letter["distributor_id"] != body["distributor_id"]:
            continue
        if letter["status"] not in ("SUBMITTED", "ACTIVE"):
            continue
        old_from = parse_instant(letter["effective_from"])
        old_to = parse_instant(letter["effective_to"])
        if new_from < old_to and old_from < new_to:
            raise ApiError("ERR_LOA_PERIOD_OVERLAP")

    # priority 22 - effective_to strictly after effective_from
    if new_to <= new_from:
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")

    rec = new_record("AuthorizationLetter", {
        "member_id": body["member_id"],
        "distributor_id": body["distributor_id"],
        "effective_from": _canonical_instant(body["effective_from"]),
        "effective_to": _canonical_instant(body["effective_to"]),
        "signatory_name": body["signatory_name"],
        "scope": body["scope"],
        "status": "SUBMITTED",
        "countersigned_at": None,
    })
    db.letters[rec["id"]] = rec
    return created(dump(rec))


@bp.get("/authorization-letters/<letter_id>")
@endpoint("GpoAdmin", "RebateAnalyst", "MemberOperator", "DistributorFeed")
def get_authorization_letter(caller, letter_id):
    return ok(dump(resolve("letter", letter_id)))


@bp.get("/authorization-letters")
@endpoint("GpoAdmin", "RebateAnalyst", "MemberOperator", "DistributorFeed")
def list_authorization_letters(caller):
    records = _filtered(db.letters.values(),
                        [("member_id", "member_id"),
                         ("distributor_id", "distributor_id"),
                         ("status", "status"),
                         ("scope", "scope")])
    return paged(records)


@bp.post("/authorization-letters/<letter_id>/countersign")
@endpoint("DistributorFeed")
def countersign_authorization_letter(caller, letter_id):
    letter = resolve("letter", letter_id)                      # priority 4
    require_distributor_scope(caller, letter["distributor_id"])  # priority 6
    body = parse_body([Enum("decision", ("ACCEPT", "DECLINE"))])

    if letter["status"] != "SUBMITTED":                        # priority 11
        raise ApiError("ERR_INVALID_STATE")
    distributor = db.distributors.get(letter["distributor_id"])
    if distributor is None or distributor["status"] != "ACTIVE":  # priority 13
        raise ApiError("ERR_DISTRIBUTOR_SUSPENDED")

    if body["decision"] == "ACCEPT":
        letter["status"] = "ACTIVE"
        letter["countersigned_at"] = db.now_iso()
        touch(letter)
        member = db.members.get(letter["member_id"])
        if member is not None:
            member["active_letter_count"] += 1
            touch(member)
        distributor["active_letter_count"] += 1
        touch(distributor)
    else:
        # DECLINE leaves countersigned_at null and moves no counter.
        letter["status"] = "DECLINED"
        touch(letter)
    return ok(dump(letter))


@bp.post("/authorization-letters/<letter_id>/revoke")
@endpoint("MemberOperator", "GpoAdmin")
def revoke_authorization_letter(caller, letter_id):
    letter = resolve("letter", letter_id)              # priority 4
    require_member_scope(caller, letter["member_id"])  # priority 5
    if letter["status"] != "ACTIVE":                   # priority 11
        raise ApiError("ERR_INVALID_STATE")

    letter["status"] = "REVOKED"
    touch(letter)
    member = db.members.get(letter["member_id"])
    if member is not None:
        member["active_letter_count"] -= 1
        touch(member)
    distributor = db.distributors.get(letter["distributor_id"])
    if distributor is not None:
        distributor["active_letter_count"] -= 1
        touch(distributor)
    return ok(dump(letter))
