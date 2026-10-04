"""Admin endpoints: talent lifecycle, moderation, tax review, dispute
resolution, sweeps, payout lifecycle, logical clock."""
from datetime import timedelta
from flask import Blueprint

import db
import services as svc
from errors import err, parse_pagination, paginate
from middleware import authenticate, require_role, get_json_body, req_str, req_iso
from response import envelope, envelope_list
from routes.talents import talent_public, taxdoc_public, payout_public
from routes.orders import video_public, dispute_public, order_public

bp = Blueprint("admin", __name__)

ADMIN = ["PlatformAdmin"]


def _admin():
    _uid, role = authenticate()
    require_role(role, ADMIN)


def _get_talent(tid):
    t = db.talents.get(tid)
    if t is None:
        raise err("ERR_NOT_FOUND", "talent %s not found" % tid)
    return t


def _has_verified_taxdoc(talent_id):
    return any(d["talent_id"] == talent_id and d["status"] == "VERIFIED"
               for d in db.tax_documents.values())


# ---------------------------------------------------------------------------
# Talent admin
# ---------------------------------------------------------------------------
@bp.post("/marketplace/admin/talents/<tid>/activate")
def activate_talent(tid):
    _admin()
    talent = _get_talent(tid)
    get_json_body(required=False)
    if talent["status"] != "ID_VERIFIED":
        raise err("ERR_INVALID_STATE", "activate requires ID_VERIFIED status")
    # rate bounds check (ERR_RATE_OUT_OF_BOUNDS) before tax gate? No: PRD §3.1
    # lists the three preconditions together; scaffold validation priority puts
    # ERR_RATE_OUT_OF_BOUNDS (21) before ERR_TAX_DOC_MISSING (24).
    svc.validate_rates(talent, talent["personal_rate_cents"],
                       talent["business_rate_cents"],
                       talent["advertising_rate_cents"])
    if not _has_verified_taxdoc(tid):
        raise err("ERR_TAX_DOC_MISSING",
                  "talent holds no VERIFIED tax document")
    talent["status"] = "ACTIVE"
    svc.touch(talent)
    return envelope(talent_public(talent), "object", 200)


@bp.post("/marketplace/admin/talents/<tid>/reject-identity")
def reject_identity(tid):
    _admin()
    talent = _get_talent(tid)
    get_json_body(required=False)
    if talent["status"] != "ID_VERIFIED":
        raise err("ERR_INVALID_STATE", "reject-identity requires ID_VERIFIED status")
    talent["status"] = "PENDING_VERIFICATION"
    talent["identity_document_ref"] = None
    talent["identity_submitted_at"] = None
    svc.touch(talent)
    return envelope(talent_public(talent), "object", 200)


@bp.post("/marketplace/admin/talents/<tid>/suspend")
def suspend_talent(tid):
    _admin()
    talent = _get_talent(tid)
    get_json_body(required=False)
    if talent["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "suspend requires ACTIVE or PAUSED status")
    talent["status"] = "SUSPENDED"
    svc.touch(talent)
    # Cascade: refund in-flight orders.
    for order in db.orders.values():
        if order["talent_id"] != tid:
            continue
        if order["status"] == "AWAITING_ACCEPTANCE":
            order["status"] = "EXPIRED"
            svc.refund_to_wallet(order)
            svc.touch(order)
        elif order["status"] in ("ACCEPTED", "RE_RECORD_REQUESTED"):
            order["status"] = "CANCELLED"
            svc.refund_to_wallet(order)
            svc.close_open_rerecords(order["id"])
            svc.touch(order)
    return envelope(talent_public(talent), "object", 200)


@bp.post("/marketplace/admin/talents/<tid>/pricing-suggestion")
def force_pricing_suggestion(tid):
    _admin()
    talent = _get_talent(tid)
    get_json_body(required=False)
    if talent["personal_rate_cents"] is None:
        raise err("ERR_INVALID_STATE",
                  "pricing suggestion requires a personal rate to be set")
    svc.compute_suggestion(talent)
    return envelope(talent_public(talent), "object", 200)


# ---------------------------------------------------------------------------
# Video moderation
# ---------------------------------------------------------------------------
@bp.post("/marketplace/admin/videos/<vid>/moderate")
def moderate_video(vid):
    _uid, role = authenticate()
    require_role(role, ["PlatformAdmin", "Moderator"])
    video = db.videos.get(vid)
    if video is None:
        raise err("ERR_NOT_FOUND", "video %s not found" % vid)
    body = get_json_body()
    decision = body.get("decision")
    if decision not in ("CLEAR", "FLAG"):
        raise err("ERR_INVALID_REQUEST", "decision must be CLEAR or FLAG")
    if video["moderation_status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", "video is not PENDING_REVIEW")
    if decision == "FLAG":
        reason = body.get("flagged_reason")
        if not isinstance(reason, str) or not reason:
            raise err("ERR_INVALID_REQUEST",
                      "flagged_reason is required when decision == FLAG")
        video["moderation_status"] = "FLAGGED"
        video["flagged_reason"] = reason
        svc.touch(video)
        order = db.orders.get(video["order_id"])
        if order is not None and order["status"] == "DELIVERED":
            order["status"] = "RE_RECORD_REQUESTED"
            order["re_record_count"] += 1
            svc.make_record(db.rerecord_requests, {
                "order_id": order["id"],
                "notes": reason,
                "status": "OPEN",
            })
            svc.touch(order)
    else:
        video["moderation_status"] = "CLEARED"
        svc.touch(video)
    return envelope(video_public(video), "object", 200)


# ---------------------------------------------------------------------------
# Tax document review
# ---------------------------------------------------------------------------
@bp.post("/marketplace/admin/tax-documents/<doc_id>/review")
def review_taxdoc(doc_id):
    _admin()
    doc = db.tax_documents.get(doc_id)
    if doc is None:
        raise err("ERR_NOT_FOUND", "tax document %s not found" % doc_id)
    body = get_json_body()
    decision = body.get("decision")
    if decision not in ("VERIFY", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be VERIFY or REJECT")
    if doc["status"] == "REJECTED":
        # PRD §3.1: "A rejected document is immutable" — only REJECTED is
        # terminal; a VERIFIED document may still be rejected later.
        raise err("ERR_INVALID_STATE", "a REJECTED tax document is immutable")
    doc["status"] = "VERIFIED" if decision == "VERIFY" else "REJECTED"
    svc.touch(doc)
    return envelope(taxdoc_public(doc), "object", 200)


# ---------------------------------------------------------------------------
# Dispute resolution
# ---------------------------------------------------------------------------
OUTCOMES = {"FULL_REFUND", "PARTIAL_REFUND", "NO_REFUND",
            "BUYER_MISMATCH_PLATFORM_ABSORB"}


@bp.post("/marketplace/admin/disputes/<did>/resolve")
def resolve_dispute(did):
    _admin()
    dispute = db.disputes.get(did)
    if dispute is None:
        raise err("ERR_NOT_FOUND", "dispute %s not found" % did)
    body = get_json_body()
    outcome = body.get("outcome")
    if outcome not in OUTCOMES:
        raise err("ERR_INVALID_REQUEST",
                  "outcome must be one of %s" % sorted(OUTCOMES))
    notes = body.get("resolution_notes")
    if notes is not None and not isinstance(notes, str):
        raise err("ERR_INVALID_REQUEST", "resolution_notes must be a string")
    if dispute["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "dispute is not OPEN")
    order = db.orders.get(dispute["order_id"])
    if order is None or order["status"] != "REFUND_PENDING":
        raise err("ERR_INVALID_STATE", "order is not REFUND_PENDING")

    talent = db.talents[order["talent_id"]]
    buyer = db.buyers[order["buyer_id"]]
    gross = order["gross_amount_cents"]

    if outcome == "FULL_REFUND":
        clawback = order["talent_net_cents"]
        # Solvency check before anything is written.
        if talent["pending_balance_cents"] < clawback:
            raise err("ERR_PENDING_BALANCE_INSUFFICIENT",
                      "clawback would drive pending_balance_cents negative")
        dispute["status"] = "RESOLVED_REFUND"
        dispute["refund_to_buyer_cents"] = gross
        dispute["resolution_notes"] = notes
        svc.touch(dispute)

        order["status"] = "REFUNDED"
        order["refund_amount_cents"] = gross
        order["clawback_cents"] = clawback
        svc.touch(order)

        buyer["wallet_credit_cents"] += gross
        svc.touch(buyer)

        svc.make_record(db.payout_lines, {
            "talent_id": talent["id"],
            "order_id": order["id"],
            "kind": "CLAWBACK",
            "amount_cents": -clawback,
            "settlement_status": "UNSETTLED",
            "payout_id": None,
        })
        talent["pending_balance_cents"] -= clawback
        svc.adjust_gmv(talent, -gross)  # recomputes tier and touches talent

    elif outcome == "PARTIAL_REFUND":
        refund = svc.round_half_up(svc.Decimal(gross) * svc.Decimal("0.5"))
        if talent["pending_balance_cents"] < refund:
            raise err("ERR_PENDING_BALANCE_INSUFFICIENT",
                      "clawback would drive pending_balance_cents negative")
        dispute["status"] = "RESOLVED_PARTIAL"
        dispute["refund_to_buyer_cents"] = refund
        dispute["resolution_notes"] = notes
        svc.touch(dispute)

        order["status"] = "REFUNDED"
        order["refund_amount_cents"] = refund
        order["clawback_cents"] = refund
        svc.touch(order)

        buyer["wallet_credit_cents"] += refund
        svc.touch(buyer)

        svc.make_record(db.payout_lines, {
            "talent_id": talent["id"],
            "order_id": order["id"],
            "kind": "CLAWBACK",
            "amount_cents": -refund,
            "settlement_status": "UNSETTLED",
            "payout_id": None,
        })
        talent["pending_balance_cents"] -= refund
        svc.adjust_gmv(talent, -refund)

    elif outcome == "NO_REFUND":
        dispute["status"] = "RESOLVED_NO_REFUND"
        dispute["refund_to_buyer_cents"] = 0
        dispute["resolution_notes"] = notes
        svc.touch(dispute)
        # Order returns to CONFIRMED and payout_computation runs as a normal
        # confirmation.  A dispute may be opened from CONFIRMED (PRD §3.6);
        # in that case the payout computation already ran at confirmation and
        # must not run again.
        order["status"] = "CONFIRMED"
        if order["platform_commission_cents"] is None:
            svc.run_confirm_cascade(order)
        svc.touch(order)

    else:  # BUYER_MISMATCH_PLATFORM_ABSORB
        dispute["status"] = "RESOLVED_BUYER_MISMATCH"
        dispute["refund_to_buyer_cents"] = gross
        dispute["resolution_notes"] = notes
        svc.touch(dispute)

        order["status"] = "REFUNDED"
        order["refund_amount_cents"] = gross
        order["platform_absorbed_cents"] = gross
        order["clawback_cents"] = 0
        svc.touch(order)

        buyer["wallet_credit_cents"] += gross
        svc.touch(buyer)
        # No CLAWBACK line; pending balance and trailing GMV untouched.

    return envelope(dispute_public(dispute), "object", 200)


# ---------------------------------------------------------------------------
# Deadline sweep
# ---------------------------------------------------------------------------
@bp.post("/marketplace/admin/deadline-sweep")
def deadline_sweep():
    _admin()
    body = get_json_body()
    to_dt = req_iso(body, "to_iso8601")
    expired_count = 0
    cancelled_count = 0
    auto_confirmed_count = 0
    licenses_expired_count = 0

    for order in list(db.orders.values()):
        if order["status"] == "AWAITING_ACCEPTANCE":
            deadline = db.parse_iso(order["acceptance_deadline"])
            if deadline is not None and to_dt >= deadline:
                order["status"] = "EXPIRED"
                svc.refund_to_wallet(order)
                svc.touch(order)
                expired_count += 1

    for order in list(db.orders.values()):
        if order["status"] in ("ACCEPTED", "RE_RECORD_REQUESTED"):
            deadline = db.parse_iso(order["delivery_deadline"])
            if deadline is not None and to_dt >= deadline:
                order["status"] = "CANCELLED"
                svc.refund_to_wallet(order)
                svc.close_open_rerecords(order["id"])
                svc.touch(order)
                cancelled_count += 1

    for order in list(db.orders.values()):
        if order["status"] == "DELIVERED":
            auto = db.parse_iso(order["auto_confirm_at"])
            if auto is None or to_dt < auto:
                continue
            latest = [v for v in db.videos.values() if v["order_id"] == order["id"]]
            if not latest:
                continue
            latest = max(latest, key=lambda v: v["version_no"])
            if latest["moderation_status"] != "CLEARED":
                continue
            if any(d["order_id"] == order["id"] and d["status"] == "OPEN"
                   for d in db.disputes.values()):
                continue
            order["status"] = "CONFIRMED"
            svc.run_confirm_cascade(order)
            svc.touch(order)
            auto_confirmed_count += 1

    for grant in list(db.license_grants.values()):
        if grant["status"] == "ACTIVE":
            ends = db.parse_iso(grant["ends_at"])
            if ends is not None and ends <= to_dt:
                grant["status"] = "EXPIRED"
                svc.touch(grant)
                licenses_expired_count += 1

    return envelope({
        "expired_count": expired_count,
        "cancelled_count": cancelled_count,
        "auto_confirmed_count": auto_confirmed_count,
        "licenses_expired_count": licenses_expired_count,
    }, "object", 200)


# ---------------------------------------------------------------------------
# Verification sweep
# ---------------------------------------------------------------------------
@bp.post("/marketplace/admin/verification-sweep")
def verification_sweep():
    _admin()
    body = get_json_body()
    to_dt = req_iso(body, "to_iso8601")
    auto_rejected = 0
    threshold = timedelta(hours=svc.IDENTITY_AUTO_REJECT_HOURS)
    for talent in list(db.talents.values()):
        if talent["status"] != "PENDING_VERIFICATION":
            continue
        submitted = db.parse_iso(talent.get("identity_submitted_at"))
        if submitted is None:
            continue
        if to_dt >= submitted + threshold:
            talent["identity_document_ref"] = None
            talent["identity_submitted_at"] = None
            svc.touch(talent)
            auto_rejected += 1
    return envelope({"auto_rejected_count": auto_rejected}, "object", 200)


# ---------------------------------------------------------------------------
# Payout sweep
# ---------------------------------------------------------------------------
@bp.post("/marketplace/admin/payout-sweep")
def payout_sweep():
    _admin()
    body = get_json_body()
    period_start = req_iso(body, "period_start")
    period_end = req_iso(body, "period_end")

    created = []
    talents_sorted = sorted(
        (t for t in db.talents.values() if t["status"] in ("ACTIVE", "PAUSED")),
        key=lambda t: (t["created_at"], t["id"]))
    for talent in talents_sorted:
        lines = []
        for l in db.payout_lines.values():
            if l["talent_id"] != talent["id"] or l["settlement_status"] != "UNSETTLED":
                continue
            created_dt = db.parse_iso(l["created_at"])
            if created_dt is not None and created_dt < period_end:
                lines.append(l)
        # Earnings positive, clawbacks negative (PRD §3.8): a clawback only
        # cancels unsettled earnings, so the swept net never drops below the
        # amount still owed to the talent after clawbacks.
        earned = sum(l["amount_cents"] for l in lines if l["amount_cents"] > 0)
        clawed = sum(-l["amount_cents"] for l in lines if l["amount_cents"] < 0)
        if clawed > earned:
            clawed = earned
        total = earned - clawed
        if total < svc.MIN_PAYOUT_CENTS:
            continue
        payout = svc.make_record(db.payouts, {
            "talent_id": talent["id"],
            "status": "SCHEDULED",
            "total_cents": total,
            "period_start": db.iso(period_start),
            "period_end": db.iso(period_end),
            "paid_at": None,
        })
        for l in lines:
            l["payout_id"] = payout["id"]
            svc.touch(l)
        created.append(payout)

    if not created:
        raise err("ERR_PAYOUT_BELOW_MINIMUM",
                  "no talent's swept total met the 2500-cent minimum")

    # Paginated list of the created payouts (body may carry limit/offset).
    limit = body.get("limit", 10)
    offset = body.get("offset", 0)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be an integer >= 0")
    total = len(created)
    page = created[offset:offset + limit]
    has_more = offset + len(page) < total
    return envelope_list([payout_public(p) for p in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Payout lifecycle
# ---------------------------------------------------------------------------
@bp.post("/marketplace/admin/payouts/<pid>/initiate")
def initiate_payout(pid):
    _admin()
    payout = db.payouts.get(pid)
    if payout is None:
        raise err("ERR_NOT_FOUND", "payout %s not found" % pid)
    get_json_body(required=False)
    if payout["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "initiate requires SCHEDULED status")
    if not _has_verified_taxdoc(payout["talent_id"]):
        raise err("ERR_TAX_DOC_MISSING",
                  "talent holds no VERIFIED tax document")
    payout["status"] = "PROCESSING"
    svc.touch(payout)
    return envelope(payout_public(payout), "object", 200)


@bp.post("/marketplace/admin/payouts/<pid>/complete")
def complete_payout(pid):
    _admin()
    payout = db.payouts.get(pid)
    if payout is None:
        raise err("ERR_NOT_FOUND", "payout %s not found" % pid)
    get_json_body(required=False)
    if payout["status"] != "PROCESSING":
        raise err("ERR_INVALID_STATE", "complete requires PROCESSING status")
    payout["status"] = "PAID"
    payout["paid_at"] = db.iso(db.clock_now())
    svc.touch(payout)
    for l in db.payout_lines.values():
        if l["payout_id"] == pid and l["settlement_status"] == "UNSETTLED":
            l["settlement_status"] = "SETTLED"
            svc.touch(l)
    talent = db.talents[payout["talent_id"]]
    talent["pending_balance_cents"] -= payout["total_cents"]
    talent["paid_out_balance_cents"] += payout["total_cents"]
    svc.touch(talent)
    return envelope(payout_public(payout), "object", 200)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/marketplace/_clock/set_current_utc")
def set_clock():
    _admin()
    body = get_json_body()
    to_dt = req_iso(body, "to_iso8601")
    if to_dt < db.clock_now():
        raise err("ERR_INVALID_REQUEST",
                  "logical clock is monotonic; cannot move it backward")
    db.set_clock(to_dt)
    return envelope({"current_utc": db.iso(db.clock_now())}, "object", 200)
