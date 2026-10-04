"""RedressFund retrieval, OCC-guarded lifecycle, and Claimant identification."""
from flask import Blueprint, request

import envelope
import errors
import requtil
import rules
import store
from timeutil import parse_iso

bp = Blueprint("funds", __name__)

FUND_STATES = {
    "ACCUMULATING",
    "OPEN_FOR_CLAIMS",
    "CLAIMS_CLOSED",
    "DISBURSING",
    "RESIDUAL_DISPOSITION",
    "CLOSED",
}
# ACCUMULATING -> OPEN_FOR_CLAIMS is system-only (judgment payment cascade);
# a manual request for it is rejected with ERR_INVALID_STATE_TRANSITION.
FUND_TRANSITIONS = {
    "CLAIMS_CLOSED": {"OPEN_FOR_CLAIMS"},
    "DISBURSING": {"CLAIMS_CLOSED"},
    "RESIDUAL_DISPOSITION": {"DISBURSING"},
    "CLOSED": {"RESIDUAL_DISPOSITION"},
}
IDENTIFIED_FROM = {"COMPANY_RECORDS", "CLAIMS_PROCESS"}


def _approved_claims(fund_id):
    return [
        c
        for c in store.db.claims.values()
        if c["redress_fund_id"] == fund_id and c["status"] == "APPROVED"
    ]


@bp.route("/enforcement/redress-funds/<fundId>", methods=["GET"])
def get_fund(fundId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    fund = requtil.get_or_404(
        store.db.redress_funds, fundId, "ERR_REDRESS_FUND_NOT_FOUND", "RedressFund"
    )
    return envelope.success(store.public(fund), 200)


@bp.route("/enforcement/redress-funds/<fundId>/transition", methods=["POST"])
def transition_fund(fundId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["FundAdministrator"])
    fund = requtil.get_or_404(
        store.db.redress_funds, fundId, "ERR_REDRESS_FUND_NOT_FOUND", "RedressFund"
    )
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", FUND_STATES)
    expected = requtil.need_int(body, "expected_redress_fund_version")
    residual_recipient_name = None
    if target == "RESIDUAL_DISPOSITION":
        residual_recipient_name = requtil.need_str(body, "residual_recipient_name")
    # Tier 5: state legality.
    if target not in FUND_TRANSITIONS or fund["status"] not in FUND_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "RedressFund cannot transition from {} to {}".format(
                fund["status"], target
            ),
        )
    # Tier 6: optimistic concurrency.
    if expected != fund["version"]:
        errors.fail(
            "ERR_STALE_FUND_VERSION",
            "expected_redress_fund_version {} does not match current version {}".format(
                expected, fund["version"]
            ),
        )
    # Tier 13: aggregate gates.
    if target == "CLAIMS_CLOSED":
        unresolved = [
            c
            for c in store.db.claims.values()
            if c["redress_fund_id"] == fund["id"]
            and c["status"] in ("FILED", "UNDER_REVIEW")
        ]
        if unresolved:
            errors.fail(
                "ERR_UNRESOLVED_CLAIMS_EXIST",
                "Claims remain in FILED or UNDER_REVIEW",
            )
    if target == "RESIDUAL_DISPOSITION":
        claim_ids = {
            c["id"]
            for c in store.db.claims.values()
            if c["redress_fund_id"] == fund["id"]
        }
        outstanding = [
            k
            for k in store.db.refund_checks.values()
            if k["claim_id"] in claim_ids and k["status"] in ("ISSUED", "STALE")
        ]
        if outstanding:
            errors.fail(
                "ERR_CHECKS_OUTSTANDING",
                "Every refund check of the fund's claims must be CASHED or VOIDED",
            )
    with store.db.lock:
        if target == "CLAIMS_CLOSED":
            # Waterfall steps 1-3 re-run against the now-final claim set.
            reserve, pool, _awards = rules.waterfall(
                _approved_claims(fund["id"]), fund["total_collected_cents"]
            )
            fund["admin_reserve_cents"] = reserve
            fund["distributable_pool_cents"] = pool
            fund["available_cents"] = (
                pool - fund["allocated_cents"] - fund["disbursed_cents"]
            )
            fund["status"] = "CLAIMS_CLOSED"
            store.touch(fund)
        elif target == "DISBURSING":
            # Final waterfall variant: computed once, frozen into final_award_cents.
            approved = _approved_claims(fund["id"])
            _reserve, _pool, awards = rules.waterfall(
                approved, fund["total_collected_cents"]
            )
            for claim in approved:
                final_award = awards[claim["id"]]
                if claim.get("final_award_cents") != final_award:
                    claim["final_award_cents"] = final_award
                    store.touch(claim)
            fund["allocated_cents"] = sum(awards.values())
            fund["available_cents"] = (
                fund["distributable_pool_cents"]
                - fund["allocated_cents"]
                - fund["disbursed_cents"]
            )
            fund["status"] = "DISBURSING"
            store.touch(fund)
        elif target == "RESIDUAL_DISPOSITION":
            identified_count = len(
                [
                    c
                    for c in store.db.claimants.values()
                    if c["redress_fund_id"] == fund["id"]
                ]
            )
            approved_count = len(
                [
                    c
                    for c in store.db.claims.values()
                    if c["redress_fund_id"] == fund["id"]
                    and c["status"] in ("APPROVED", "PAID")
                ]
            )
            fund["residual_disposition"] = (
                "CY_PRES"
                if rules.cy_pres_eligible(approved_count, identified_count)
                else "TREASURY_ESCHEAT"
            )
            fund["residual_cents"] = fund["available_cents"]
            fund["available_cents"] = 0
            fund["residual_recipient_name"] = residual_recipient_name
            fund["status"] = "RESIDUAL_DISPOSITION"
            store.touch(fund)
        elif target == "CLOSED":
            fund["status"] = "CLOSED"
            store.touch(fund)
    return envelope.success(store.public(fund), 200)


@bp.route("/enforcement/redress-funds/<fundId>/claimants", methods=["POST"])
def identify_claimant(fundId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["FundAdministrator"])
    fund = requtil.get_or_404(
        store.db.redress_funds, fundId, "ERR_REDRESS_FUND_NOT_FOUND", "RedressFund"
    )
    body = requtil.json_body()
    full_name = requtil.need_str(body, "full_name")
    email = requtil.need_str(body, "email")
    identified_from = requtil.need_enum(body, "identified_from", IDENTIFIED_FROM)
    if fund["status"] not in ("ACCUMULATING", "OPEN_FOR_CLAIMS"):
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Claimants may be identified only while the fund is ACCUMULATING or OPEN_FOR_CLAIMS",
        )
    with store.db.lock:
        claimant = store.stamp_new(
            {
                "redress_fund_id": fund["id"],
                "full_name": full_name,
                "email": email,
                "identified_from": identified_from,
                "notified_at": None,
                "status": "IDENTIFIED",
            }
        )
        store.db.claimants[claimant["id"]] = claimant
        # Immediate notification when the fund is already open for claims.
        if fund["status"] == "OPEN_FOR_CLAIMS":
            claimant["status"] = "NOTIFIED"
            claimant["notified_at"] = store.now_str()
    return envelope.success(store.public(claimant), 201)


@bp.route("/enforcement/redress-funds/<fundId>/claimants", methods=["GET"])
def list_claimants(fundId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    fund = requtil.get_or_404(
        store.db.redress_funds, fundId, "ERR_REDRESS_FUND_NOT_FOUND", "RedressFund"
    )
    limit, offset = requtil.page_params()
    items = [
        c for c in store.db.claimants.values() if c["redress_fund_id"] == fund["id"]
    ]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda e: (parse_iso(e["created_at"]), e["_seq"]))
    total = len(items)
    page = [store.public(c) for c in items[offset:offset + limit]]
    return envelope.success_list(page, limit, offset, total)
