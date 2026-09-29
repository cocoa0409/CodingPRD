"""Distribution deals: formation, the wind-down diamond and the recoupment
projection (PRD sections 3.1, 3.6 and 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (BUSINESS_AFFAIRS, DISTRIBUTION_PARTNER, LABEL_ADMIN,
                           ROYALTY_ANALYST, find_deal, find_distributor)
from services import ledger, lookups

bp = Blueprint("deals", __name__)

DEAL_TYPES = ("DISTRIBUTION_FEE", "PROFIT_SHARE", "LABEL_SERVICES")
VARIANTS = ("CROSS_COLLATERALIZED", "SILOED")
ATTRIBUTABLE = ("PLANNED", "RELEASED", "REVERSION_PENDING")


@bp.route("/distribution-deals", methods=["POST"])
def create_deal():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    distributor_id = v.identifier(body, "distributor_id", required=True)
    deal_type = v.enum(body, "deal_type", DEAL_TYPES, required=True)

    distribution_fee_pct = None
    profit_share_label_pct = None
    services_fee_pct = None
    services_monthly_fee_cents = None
    if deal_type == "DISTRIBUTION_FEE":
        distribution_fee_pct = v.percentage(
            body, "distribution_fee_pct", required=True,
            minimum=Decimal("0.0100"), maximum=Decimal("0.3000"))
        v.must_be_null(body, "profit_share_label_pct")
        v.must_be_null(body, "services_fee_pct")
        v.must_be_null(body, "services_monthly_fee_cents")
    elif deal_type == "PROFIT_SHARE":
        profit_share_label_pct = v.percentage(
            body, "profit_share_label_pct", required=True,
            minimum=Decimal("0.3000"), maximum=Decimal("0.9000"))
        v.must_be_null(body, "distribution_fee_pct")
        v.must_be_null(body, "services_fee_pct")
        v.must_be_null(body, "services_monthly_fee_cents")
    else:
        services_fee_pct = v.percentage(
            body, "services_fee_pct", required=True,
            minimum=Decimal("0.0100"), maximum=Decimal("0.2500"))
        services_monthly_fee_cents = v.integer(
            body, "services_monthly_fee_cents", required=True, minimum=0)
        v.must_be_null(body, "distribution_fee_pct")
        v.must_be_null(body, "profit_share_label_pct")

    term_start_date = v.date_field(body, "term_start_date", required=True)
    term_end_date = v.date_field(body, "term_end_date", required=True)
    if not term_end_date > term_start_date:
        v.bad("term_end_date", "must be strictly after term_start_date.")
    territory_codes = v.territory_list(body, "territory_codes", required=True)
    cross_collateralized = v.boolean(body, "cross_collateralized", required=True)
    advance_amount_cents = v.integer(body, "advance_amount_cents", required=True,
                                     minimum=0)
    marketing_budget_cents = v.integer(body, "marketing_budget_cents", required=True,
                                       minimum=0)
    objection_window_days = v.integer(body, "objection_window_days", required=False,
                                      minimum=1, maximum=180, default=30)
    post_term_collection_days = v.integer(
        body, "post_term_collection_days", required=False, minimum=0,
        maximum=1095, default=180)

    find_distributor(distributor_id)

    record = db.base_record()
    record.update({
        "distributor_id": distributor_id,
        "deal_type": deal_type,
        "distribution_fee_pct": distribution_fee_pct,
        "profit_share_label_pct": profit_share_label_pct,
        "services_fee_pct": services_fee_pct,
        "services_monthly_fee_cents": services_monthly_fee_cents,
        "term_start_date": db.date_str(term_start_date),
        "term_end_date": db.date_str(term_end_date),
        "territory_codes": territory_codes,
        "cross_collateralized": cross_collateralized,
        "advance_amount_cents": advance_amount_cents,
        "marketing_budget_cents": marketing_budget_cents,
        "objection_window_days": objection_window_days,
        "post_term_collection_days": post_term_collection_days,
        "status": "DRAFT",
        "advance_payment_reference": None,
        "executed_at": None,
        "termination_effective_date": None,
        "post_term_collection_end_date": None,
        "advance_recouped_cents": 0,
        "unrecouped_advance_cents": 0,
        "net_receipts_to_date_cents": 0,
        "post_recoupment_net_receipts_cents": 0,
        "recoupment_status": "UNRECOUPED",
        "marketing_committed_cents": 0,
    })
    db.store.deals[record["id"]] = record
    return response.created(serializers.deal(record))


@bp.route("/distribution-deals/<record_id>", methods=["GET"])
def get_deal(record_id):
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS,
                  DISTRIBUTION_PARTNER])
    return response.ok(serializers.deal(find_deal(record_id)))


@bp.route("/distribution-deals", methods=["GET"])
def list_deals():
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS,
                  DISTRIBUTION_PARTNER])
    limit, offset = pagination()
    records = db.ordered(list(db.store.deals.values()))
    for key in ("distributor_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.deal(r) for r in page], limit, offset, total)


@bp.route("/distribution-deals/<record_id>/execute", methods=["POST"])
def execute_deal(record_id):
    authenticate([LABEL_ADMIN])
    deal = find_deal(record_id)
    body = parse_body()
    reference = v.text(body, "advance_payment_reference", required=True,
                       min_len=1, max_len=200)
    if deal["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    catalog = [r for r in lookups.releases_of_deal(deal["id"])
               if r["status"] in ("PLANNED", "RELEASED")]
    if not catalog:
        raise ApiError("ERR_INVALID_DEAL_STATE",
                       "The deal carries no release ready for execution.")
    deal["status"] = "EXECUTED"
    deal["advance_payment_reference"] = reference
    deal["executed_at"] = db.iso_instant(db.store.now())
    deal["advance_recouped_cents"] = 0
    deal["unrecouped_advance_cents"] = deal["advance_amount_cents"]
    deal["recoupment_status"] = "RECOUPED" if deal["advance_amount_cents"] == 0 \
        else "UNRECOUPED"
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/distribution-deals/<record_id>/terminate", methods=["POST"])
def terminate_deal(record_id):
    authenticate([LABEL_ADMIN])
    deal = find_deal(record_id)
    parse_body()
    if deal["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    effective_date = db.store.today()
    collection_end = effective_date + \
        db.timedelta(days=deal["post_term_collection_days"])
    deal["status"] = "TERMINATION_NOTICE"
    deal["termination_effective_date"] = db.date_str(effective_date)
    deal["post_term_collection_end_date"] = db.date_str(collection_end)

    touched_releases = []
    for release in lookups.releases_of_deal(deal["id"]):
        if release["status"] == "RELEASED":
            release["status"] = "REVERSION_PENDING"
            release["reversion_eligible_date"] = deal["post_term_collection_end_date"]
            db.touch(release)
            touched_releases.append(release)
        elif release["status"] == "PLANNED":
            release["status"] = "REVERTED"
            db.touch(release)
            touched_releases.append(release)
    for release in touched_releases:
        for agreement in lookups.agreements_of_release(release["id"]):
            if agreement["status"] not in ("ACTIVE", "AMENDMENT_PENDING"):
                continue
            agreement["status"] = "POST_TERM"
            agreement["post_term_collection_end_date"] = \
                deal["post_term_collection_end_date"]
            db.touch(agreement)
            for statement in lookups.statements_of_agreement(agreement["id"]):
                if statement["status"] in ("DRAFT", "PREPARED"):
                    statement["status"] = "VOIDED"
                    db.touch(statement)
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/distribution-deals/<record_id>/expire", methods=["POST"])
def expire_deal(record_id):
    authenticate([LABEL_ADMIN])
    deal = find_deal(record_id)
    parse_body()
    if deal["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    term_end = db.parse_date(deal["term_end_date"])
    if not db.store.today() > term_end:
        raise ApiError("ERR_TERM_NOT_ENDED")
    collection_end = term_end + db.timedelta(days=deal["post_term_collection_days"])
    deal["status"] = "EXPIRED"
    deal["post_term_collection_end_date"] = db.date_str(collection_end)
    for release in lookups.releases_of_deal(deal["id"]):
        if release["status"] in ("PLANNED", "RELEASED"):
            release["reversion_eligible_date"] = deal["post_term_collection_end_date"]
            db.touch(release)
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/distribution-deals/<record_id>/enter-post-term-collection",
          methods=["POST"])
def enter_post_term_collection(record_id):
    authenticate([LABEL_ADMIN])
    deal = find_deal(record_id)
    parse_body()
    if deal["status"] not in ("TERMINATION_NOTICE", "EXPIRED"):
        raise ApiError("ERR_INVALID_DEAL_STATE")
    deal["status"] = "POST_TERM_COLLECTION"
    for spend in lookups.spends_of_deal(deal["id"]):
        if spend["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
            spend["status"] = "VOIDED"
            db.touch(spend)
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/distribution-deals/<record_id>/close", methods=["POST"])
def close_deal(record_id):
    authenticate([LABEL_ADMIN])
    deal = find_deal(record_id)
    parse_body()
    if deal["status"] != "POST_TERM_COLLECTION":
        raise ApiError("ERR_INVALID_DEAL_STATE")
    collection_end = db.parse_date(deal["post_term_collection_end_date"])
    if collection_end is None or not db.store.today() > collection_end:
        raise ApiError("ERR_POST_TERM_COLLECTION_ACTIVE")
    for statement in lookups.statements_of_deal(deal["id"]):
        if statement["status"] == "OBJECTED" \
                and statement.get("objection_resolution") is None:
            raise ApiError("ERR_OPEN_OBJECTIONS_BLOCK_CLOSE")

    deal["status"] = "CLOSED"
    reverted = []
    for release in lookups.releases_of_deal(deal["id"]):
        if release["status"] in ATTRIBUTABLE:
            release["status"] = "REVERTED"
            db.touch(release)
            reverted.append(release)
    for release in reverted:
        for agreement in lookups.agreements_of_release(release["id"]):
            if agreement["status"] in ("ACTIVE", "AMENDMENT_PENDING", "POST_TERM"):
                agreement["status"] = "TERMINATED"
                db.touch(agreement)
        for spend in lookups.spends_of_release(release["id"]):
            if spend["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED",
                                   "APPROVED"):
                spend["status"] = "VOIDED"
                db.touch(spend)
    ledger.recompute_marketing_committed(deal)
    db.touch(deal)
    return response.ok(serializers.deal(deal))


@bp.route("/distribution-deals/<record_id>/recoupment-summary", methods=["GET"])
def recoupment_summary(record_id):
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS])
    deal = find_deal(record_id)
    requested = request.args.get("variant")
    if requested is not None:
        if requested not in VARIANTS:
            raise ApiError("ERR_INVALID_REQUEST",
                           "variant must be CROSS_COLLATERALIZED or SILOED.")
        variant = requested
    else:
        variant = "CROSS_COLLATERALIZED" if deal["cross_collateralized"] \
            else "SILOED"

    accepted_reports = [r for r in lookups.reports_of_deal(deal["id"])
                        if r["status"] == "ACCEPTED"]
    accepted_ids = set(r["id"] for r in accepted_reports)
    pool = sum(r.get("net_receipts_cents") or 0 for r in accepted_reports)

    releases = [r for r in lookups.releases_of_deal(deal["id"])
                if r["status"] in ATTRIBUTABLE]
    release_pools = {}
    for release in releases:
        release_pools[release["id"]] = sum(
            (line.get("net_receipts_cents") or 0)
            for line in lookups.lines_of_release(release["id"])
            if line["report_id"] in accepted_ids
        )

    advance_amount = deal["advance_amount_cents"] or 0
    applied = {}
    if variant == "CROSS_COLLATERALIZED":
        applied_total = min(pool, advance_amount)
        weights = [release_pools[r["id"]] for r in releases]
        tiebreaks = [r["_seq"] for r in releases]
        split = db.largest_remainder(applied_total, weights, tiebreaks)
        for index, release in enumerate(releases):
            applied[release["id"]] = split[index]
    else:
        applied_total = 0
        for release in releases:
            share = release.get("advance_share_cents") or 0
            amount = min(release_pools[release["id"]], share)
            applied[release["id"]] = amount
            applied_total += amount

    unrecouped = advance_amount - applied_total
    breakdown = []
    for release in releases:
        share = release.get("advance_share_cents") or 0
        amount = applied[release["id"]]
        breakdown.append({
            "release_id": release["id"],
            "advance_share_cents": share,
            "pool_net_receipts_cents": release_pools[release["id"]],
            "advance_applied_cents": amount,
            "unrecouped_advance_share_cents": max(0, share - amount),
            "post_recoupment_net_receipts_cents":
                release_pools[release["id"]] - amount,
        })

    return response.ok({
        "variant": variant,
        "pool_net_receipts_cents": pool,
        "advance_amount_cents": advance_amount,
        "advance_applied_cents": applied_total,
        "unrecouped_advance_cents": unrecouped,
        "post_recoupment_net_receipts_cents": pool - applied_total,
        "recoupment_status": "RECOUPED" if unrecouped == 0 else "UNRECOUPED",
        "release_breakdown": breakdown,
    })
