"""Claim filing, listing, review transitions, and RefundCheck issuance/listing."""
from flask import Blueprint, request

import envelope
import errors
import requtil
import rules
import store
from timeutil import parse_iso, fmt_iso, seconds, add_days

bp = Blueprint("claims", __name__)

CLAIM_STATES = {"FILED", "UNDER_REVIEW", "APPROVED", "PAYMENT_PENDING", "PAID", "DENIED"}
# PAYMENT_PENDING and PAID are system-only (check issuance / cashing cascades).
CLAIM_TRANSITIONS = {
    "UNDER_REVIEW": {"FILED"},
    "APPROVED": {"UNDER_REVIEW"},
    "DENIED": {"UNDER_REVIEW"},
}


@bp.route("/enforcement/claims", methods=["POST"])
def file_claim():
    user_id, role = requtil.context()
    requtil.require_role(role, ["Claimant"])
    body = requtil.json_body()
    claimant_id = requtil.need_str(body, "claimant_id")
    redress_fund_id = requtil.need_str(body, "redress_fund_id")
    documented_loss_cents = requtil.need_int(body, "documented_loss_cents", minimum=1)
    claimant = requtil.get_or_404(
        store.db.claimants, claimant_id, "ERR_CLAIMANT_NOT_FOUND", "Claimant"
    )
    fund = requtil.get_or_404(
        store.db.redress_funds, redress_fund_id, "ERR_REDRESS_FUND_NOT_FOUND", "RedressFund"
    )
    # Tier 5: filing window — fund OPEN_FOR_CLAIMS; claimant NOTIFIED. A CLAIMED
    # claimant falls through to the tier-11 one-claim-per-claimant rule so a
    # second filing surfaces ERR_CLAIM_ALREADY_FILED, as PRD §3.6 pins.
    if fund["status"] != "OPEN_FOR_CLAIMS":
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Claims may be filed only while the fund is OPEN_FOR_CLAIMS",
        )
    if claimant["status"] == "IDENTIFIED":
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "The claimant has not been NOTIFIED",
        )
    # Tier 11: at most one claim per claimant.
    for existing in store.db.claims.values():
        if existing["claimant_id"] == claimant["id"]:
            errors.fail(
                "ERR_CLAIM_ALREADY_FILED",
                "The claimant already has a claim on this fund",
            )
    # Tier 12: cross-entity referential integrity.
    if redress_fund_id != claimant["redress_fund_id"]:
        errors.fail(
            "ERR_CLAIM_FUND_MISMATCH",
            "redress_fund_id does not equal the claimant's fund",
        )
    # Tier 13: filing ownership — X-User-ID must equal claimant_id.
    if user_id != claimant_id:
        errors.fail(
            "ERR_CLAIMANT_IDENTITY_MISMATCH",
            "X-User-ID must equal claimant_id",
        )
    with store.db.lock:
        claim = store.stamp_new(
            {
                "claimant_id": claimant["id"],
                "redress_fund_id": fund["id"],
                "documented_loss_cents": documented_loss_cents,
                "eligible_loss_cents": None,
                "provisional_award_cents": None,
                "final_award_cents": None,
                "approved_by_user_id": None,
                "denial_reason": None,
                "status": "FILED",
            }
        )
        store.db.claims[claim["id"]] = claim
        # Filing advances the claimant NOTIFIED -> CLAIMED.
        claimant["status"] = "CLAIMED"
        store.touch(claimant)
    return envelope.success(store.public(claim), 201)


@bp.route("/enforcement/claims", methods=["GET"])
def list_claims():
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    limit, offset = requtil.page_params()
    items = list(store.db.claims.values())
    claimant_filter = request.args.get("claimant_id")
    if claimant_filter is not None:
        items = [c for c in items if c["claimant_id"] == claimant_filter]
    fund_filter = request.args.get("redress_fund_id")
    if fund_filter is not None:
        items = [c for c in items if c["redress_fund_id"] == fund_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda e: (parse_iso(e["created_at"]), e["_seq"]))
    total = len(items)
    page = [store.public(c) for c in items[offset:offset + limit]]
    return envelope.success_list(page, limit, offset, total)


@bp.route("/enforcement/claims/<claimId>", methods=["GET"])
def get_claim(claimId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    claim = requtil.get_or_404(store.db.claims, claimId, "ERR_CLAIM_NOT_FOUND", "Claim")
    return envelope.success(store.public(claim), 200)


@bp.route("/enforcement/claims/<claimId>/transition", methods=["POST"])
def transition_claim(claimId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["FundAdministrator"])
    claim = requtil.get_or_404(store.db.claims, claimId, "ERR_CLAIM_NOT_FOUND", "Claim")
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", CLAIM_STATES)
    denial_reason = None
    if target == "DENIED":
        denial_reason = requtil.need_str(body, "denial_reason")
    if target not in CLAIM_TRANSITIONS or claim["status"] not in CLAIM_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Claim cannot transition from {} to {}".format(claim["status"], target),
        )
    fund = store.db.redress_funds.get(claim["redress_fund_id"])
    if target == "APPROVED" and (fund is None or fund["status"] != "OPEN_FOR_CLAIMS"):
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Claims may be approved only while the fund is OPEN_FOR_CLAIMS",
        )
    with store.db.lock:
        claim["status"] = target
        if target == "DENIED":
            claim["denial_reason"] = denial_reason
            store.touch(claim)
        elif target == "APPROVED":
            claim["approved_by_user_id"] = user_id
            claim["eligible_loss_cents"] = min(
                claim["documented_loss_cents"], rules.LOSS_CAP_CENTS
            )
            # Provisional waterfall recomputed for EVERY APPROVED claim of the fund.
            approved = [
                c
                for c in store.db.claims.values()
                if c["redress_fund_id"] == fund["id"] and c["status"] == "APPROVED"
            ]
            _reserve, _pool, awards = rules.waterfall(
                approved, fund["total_collected_cents"]
            )
            for other in approved:
                if other["id"] == claim["id"]:
                    continue
                if other.get("provisional_award_cents") != awards[other["id"]]:
                    other["provisional_award_cents"] = awards[other["id"]]
                    store.touch(other)
            claim["provisional_award_cents"] = awards[claim["id"]]
            store.touch(claim)
            # Derived-field reconciliation advances the fund version.
            store.touch(fund)
        else:
            store.touch(claim)
    return envelope.success(store.public(claim), 200)


@bp.route("/enforcement/claims/<claimId>/checks", methods=["POST"])
def issue_check(claimId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["DisbursementOfficer"])
    claim = requtil.get_or_404(store.db.claims, claimId, "ERR_CLAIM_NOT_FOUND", "Claim")
    # Tier 5: the claim must stand APPROVED; the fund must be DISBURSING.
    if claim["status"] != "APPROVED":
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A refund check may be issued only for an APPROVED claim",
        )
    fund = store.db.redress_funds.get(claim["redress_fund_id"])
    if fund is None or fund["status"] != "DISBURSING":
        errors.fail(
            "ERR_FUND_NOT_DISBURSING",
            "The fund is not DISBURSING",
        )
    # Tier 7: segregation of duties — the issuer is never the claim approver.
    if claim["approved_by_user_id"] is not None and user_id == claim["approved_by_user_id"]:
        errors.fail(
            "ERR_SOD_CHECK_ISSUE",
            "The issuing officer must differ from the claim approver",
        )
    prior = sorted(
        (k for k in store.db.refund_checks.values() if k["claim_id"] == claim["id"]),
        key=lambda k: k["_seq"],
    )
    latest = prior[-1] if prior else None
    # Tier 9: reissue only strictly before the reissue_deadline of the ORIGINAL
    # check in the chain — walk original_check_id back to the root issuance.
    if latest is not None and latest["status"] == "VOIDED":
        root = latest
        while root["original_check_id"] is not None:
            parent = store.db.refund_checks.get(root["original_check_id"])
            if parent is None:
                break
            root = parent
        if seconds(store.db.clock_dt) >= seconds(parse_iso(root["reissue_deadline"])):
            errors.fail(
                "ERR_REISSUE_WINDOW_EXPIRED",
                "The reissue deadline of the original check has been reached or passed",
            )
    # Tier 11: at most one non-VOIDED check per claim.
    if any(k["status"] in ("ISSUED", "STALE", "CASHED") for k in prior):
        errors.fail(
            "ERR_CHECK_ALREADY_OUTSTANDING",
            "The claim already has a non-voided check",
        )
    with store.db.lock:
        now = store.now_dt()
        check = store.stamp_new(
            {
                "claim_id": claim["id"],
                "redress_fund_id": claim["redress_fund_id"],
                "amount_cents": claim["final_award_cents"],
                "issued_at": store.now_str(),
                "stale_after": fmt_iso(add_days(now, rules.CHECK_STALE_DAYS)),
                "reissue_deadline": fmt_iso(add_days(now, rules.CHECK_REISSUE_WINDOW_DAYS)),
                "original_check_id": (
                    latest["id"]
                    if latest is not None and latest["status"] == "VOIDED"
                    else None
                ),
                "fraud_warning_text": rules.FRAUD_WARNING_TEXT,
                "cashed_at": None,
                "voided_reason": None,
                "status": "ISSUED",
            }
        )
        store.db.refund_checks[check["id"]] = check
        # Issuance moves the claim APPROVED -> PAYMENT_PENDING.
        claim["status"] = "PAYMENT_PENDING"
        store.touch(claim)
    return envelope.success(store.public(check), 201)


@bp.route("/enforcement/claims/<claimId>/checks", methods=["GET"])
def list_checks(claimId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    claim = requtil.get_or_404(store.db.claims, claimId, "ERR_CLAIM_NOT_FOUND", "Claim")
    limit, offset = requtil.page_params()
    items = [k for k in store.db.refund_checks.values() if k["claim_id"] == claim["id"]]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [k for k in items if k["status"] == status_filter]
    items.sort(key=lambda e: (parse_iso(e["created_at"]), e["_seq"]))
    total = len(items)
    page = [store.public(k) for k in items[offset:offset + limit]]
    return envelope.success_list(page, limit, offset, total)
