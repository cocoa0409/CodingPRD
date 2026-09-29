"""DSP revenue reports: pricing, acceptance and compensating disputes
(PRD sections 3.5 and 3.6)."""

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (BUSINESS_AFFAIRS, DISTRIBUTION_PARTNER, LABEL_ADMIN,
                           ROYALTY_ANALYST, check_deal_version, find_deal,
                           find_release, find_report, require_owner)
from services import calculations, lookups

bp = Blueprint("reports", __name__)

TIERS = ("PREMIUM", "AD_SUPPORTED", "FREE_TRIAL")
COLLECTING = ("EXECUTED", "TERMINATION_NOTICE", "POST_TERM_COLLECTION")
READERS = [LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS, DISTRIBUTION_PARTNER]


@bp.route("/dsp-revenue-reports", methods=["POST"])
def create_report():
    authenticate([DISTRIBUTION_PARTNER])
    body = parse_body()
    deal_id = v.identifier(body, "deal_id", required=True)
    dsp_code = v.dsp_code(body, "dsp_code", required=True)
    period_start = v.date_field(body, "period_start", required=True)
    period_end = v.date_field(body, "period_end", required=True)
    if period_end < period_start:
        v.bad("period_end", "may not fall before period_start.")
    find_deal(deal_id)
    record = db.base_record()
    record.update({
        "deal_id": deal_id,
        "dsp_code": dsp_code,
        "period_start": db.date_str(period_start),
        "period_end": db.date_str(period_end),
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "gross_receipts_cents": 0,
        "distributor_share_cents": 0,
        "net_receipts_cents": 0,
        "advance_applied_cents": 0,
        "accepted_at": None,
        "dispute_reason": None,
        "_release_applied": {},
    })
    db.store.reports[record["id"]] = record
    return response.created(serializers.report(record))


@bp.route("/dsp-revenue-reports/<record_id>", methods=["GET"])
def get_report(record_id):
    authenticate(READERS)
    return response.ok(serializers.report(find_report(record_id)))


@bp.route("/dsp-revenue-reports", methods=["GET"])
def list_reports():
    authenticate(READERS)
    limit, offset = pagination()
    records = db.ordered(list(db.store.reports.values()))
    for key in ("deal_id", "dsp_code", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.report(r) for r in page], limit, offset, total)


def _owning_distributor_id(report):
    deal = db.store.deals.get(report["deal_id"])
    return deal["distributor_id"] if deal else None


@bp.route("/dsp-revenue-reports/<record_id>/lines", methods=["POST"])
def append_line(record_id):
    caller = authenticate([DISTRIBUTION_PARTNER])
    report = find_report(record_id)
    require_owner(caller, _owning_distributor_id(report))
    body = parse_body()
    release_id = v.identifier(body, "release_id", required=True)
    territory_code = v.territory(body, "territory_code", required=True)
    tier = v.enum(body, "tier", TIERS, required=True)
    stream_count = v.integer(body, "stream_count", required=True, minimum=0)
    find_release(release_id)
    if report["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_REPORT_STATE")
    deal = db.store.deals.get(report["deal_id"])
    if deal is None or territory_code not in (deal["territory_codes"] or []):
        v.bad("territory_code", "is not licensed under the deal.")
    record = db.base_record(mutable=False)
    record.update({
        "report_id": report["id"],
        "release_id": release_id,
        "territory_code": territory_code,
        "tier": tier,
        "stream_count": stream_count,
        "applied_rate_micros_per_stream": None,
        "resolved_revenue_cents": None,
        "net_receipts_cents": None,
    })
    db.store.lines[record["id"]] = record
    return response.created(serializers.line(record))


@bp.route("/dsp-revenue-reports/<record_id>/lines", methods=["GET"])
def list_report_lines(record_id):
    authenticate(READERS)
    report = find_report(record_id)
    limit, offset = pagination()
    records = lookups.lines_of_report(report["id"])
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.line(r) for r in page], limit, offset, total)


@bp.route("/dsp-revenue-reports/<record_id>/submit", methods=["POST"])
def submit_report(record_id):
    caller = authenticate([DISTRIBUTION_PARTNER])
    report = find_report(record_id)
    require_owner(caller, _owning_distributor_id(report))
    parse_body()
    if report["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_REPORT_STATE")
    lines = lookups.lines_of_report(report["id"])
    if not lines:
        raise ApiError("ERR_INVALID_REPORT_STATE",
                       "The report carries no revenue lines.")
    deal = db.store.deals.get(report["deal_id"])
    priced, gross = calculations.price_report_lines(report, lines)
    distributor_share, net_receipts = calculations.deal_net_receipts(
        deal, report, gross)
    for item in priced:
        item["line"]["applied_rate_micros_per_stream"] = item["rate"]
        item["line"]["resolved_revenue_cents"] = item["revenue"]
        item["line"]["net_receipts_cents"] = None
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = caller.user_id
    report["dispute_reason"] = None
    report["gross_receipts_cents"] = gross
    report["distributor_share_cents"] = distributor_share
    report["net_receipts_cents"] = net_receipts
    report["advance_applied_cents"] = 0
    report["_release_applied"] = {}
    db.touch(report)
    return response.ok(serializers.report(report))


def _accountable_span(deal):
    start = db.parse_date(deal["term_start_date"])
    if deal.get("post_term_collection_end_date"):
        end = db.parse_date(deal["post_term_collection_end_date"])
    else:
        end = db.parse_date(deal["term_end_date"])
    return start, end


@bp.route("/dsp-revenue-reports/<record_id>/accept", methods=["POST"])
def accept_report(record_id):
    authenticate([ROYALTY_ANALYST])
    report = find_report(record_id)
    body = parse_body()
    expected = v.integer(body, "expected_deal_version", required=True)
    deal = find_deal(report["deal_id"])
    check_deal_version(deal, expected)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REPORT_STATE")
    if deal["status"] not in COLLECTING:
        raise ApiError("ERR_DEAL_NOT_COLLECTING")
    span_start, span_end = _accountable_span(deal)
    period_start = db.parse_date(report["period_start"])
    period_end = db.parse_date(report["period_end"])
    if period_start < span_start or period_end > span_end:
        raise ApiError("ERR_PERIOD_OUTSIDE_TERM")

    lines = lookups.lines_of_report(report["id"])
    report["status"] = "ACCEPTED"
    report["accepted_at"] = db.iso_instant(db.store.now())

    # Hop 1: largest-remainder split of the distributor's share across lines.
    priced = [{"line": line, "revenue": line.get("resolved_revenue_cents") or 0}
              for line in lines]
    allocation = calculations.allocate_distributor_share(
        report["distributor_share_cents"] or 0, priced)
    release_pools = {}
    for index, item in enumerate(priced):
        line = item["line"]
        line["net_receipts_cents"] = item["revenue"] - allocation[index]
        release_pools[line["release_id"]] = \
            release_pools.get(line["release_id"], 0) + line["net_receipts_cents"]

    # Hop 2: roll the line figures up to releases and to the deal.
    touched_releases = []
    for release_id, amount in release_pools.items():
        release = db.store.releases.get(release_id)
        if release is None:
            continue
        release["net_receipts_to_date_cents"] = \
            (release.get("net_receipts_to_date_cents") or 0) + amount
        touched_releases.append(release)
    deal["net_receipts_to_date_cents"] = \
        (deal.get("net_receipts_to_date_cents") or 0) + \
        (report["net_receipts_cents"] or 0)

    # Hop 3: the advance recoupment waterfall.
    pool = report["net_receipts_cents"] or 0
    applied_total, applied = calculations.advance_waterfall(
        deal, pool, release_pools)
    report["advance_applied_cents"] = applied_total
    report["_release_applied"] = dict(applied)
    deal["advance_recouped_cents"] = \
        (deal.get("advance_recouped_cents") or 0) + applied_total
    deal["unrecouped_advance_cents"] = \
        (deal["advance_amount_cents"] or 0) - deal["advance_recouped_cents"]
    deal["post_recoupment_net_receipts_cents"] = \
        (deal.get("post_recoupment_net_receipts_cents") or 0) + \
        (pool - applied_total)
    for release_id, amount in applied.items():
        release = db.store.releases.get(release_id)
        if release is None:
            continue
        release["release_advance_recouped_cents"] = \
            (release.get("release_advance_recouped_cents") or 0) + amount
        release["unrecouped_advance_share_cents"] = max(
            0, (release.get("advance_share_cents") or 0)
            - release["release_advance_recouped_cents"])
        if release not in touched_releases:
            touched_releases.append(release)

    # Hop 4 and hop 5: the escalation trigger and the re-rating it causes.
    if deal["unrecouped_advance_cents"] == 0 \
            and deal["recoupment_status"] == "UNRECOUPED":
        deal["recoupment_status"] = "RECOUPED"
        calculations.reselect_rates_for_deal(deal)

    for release in touched_releases:
        db.touch(release)
    db.touch(report)
    db.touch(deal)
    return response.ok(serializers.report(report))


def _finalized_statement_reads_report(report, lines):
    release_ids = set(line["release_id"] for line in lines)
    period_start = db.parse_date(report["period_start"])
    period_end = db.parse_date(report["period_end"])
    for statement in db.store.statements.values():
        if statement["status"] != "FINALIZED":
            continue
        agreement = db.store.agreements.get(statement["artist_agreement_id"])
        if agreement is None or agreement["release_id"] not in release_ids:
            continue
        statement_start = db.parse_date(statement["period_start"])
        statement_end = db.parse_date(statement["period_end"])
        if period_start >= statement_start and period_end <= statement_end:
            return True
    return False


@bp.route("/dsp-revenue-reports/<record_id>/dispute", methods=["POST"])
def dispute_report(record_id):
    authenticate([ROYALTY_ANALYST])
    report = find_report(record_id)
    body = parse_body()
    expected = v.integer(body, "expected_deal_version", required=True)
    reason = v.text(body, "dispute_reason", required=True, min_len=1)
    deal = find_deal(report["deal_id"])
    check_deal_version(deal, expected)
    if report["status"] not in ("SUBMITTED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_REPORT_STATE")

    lines = lookups.lines_of_report(report["id"])
    if report["status"] == "ACCEPTED":
        if _finalized_statement_reads_report(report, lines):
            raise ApiError("ERR_INVALID_STATEMENT_STATE")

        touched_releases = []
        release_pools = {}
        for line in lines:
            release_pools[line["release_id"]] = \
                release_pools.get(line["release_id"], 0) + \
                (line.get("net_receipts_cents") or 0)
        # Hop 1: clear the line allocations.
        for line in lines:
            line["net_receipts_cents"] = None
        # Hop 2: unwind the roll-up.
        for release_id, amount in release_pools.items():
            release = db.store.releases.get(release_id)
            if release is None:
                continue
            release["net_receipts_to_date_cents"] = \
                (release.get("net_receipts_to_date_cents") or 0) - amount
            touched_releases.append(release)
        deal["net_receipts_to_date_cents"] = \
            (deal.get("net_receipts_to_date_cents") or 0) - \
            (report["net_receipts_cents"] or 0)
        # Hop 3: unwind the advance attribution, exactly as it was applied.
        applied_total = report.get("advance_applied_cents") or 0
        applied = report.get("_release_applied") or {}
        deal["advance_recouped_cents"] = \
            (deal.get("advance_recouped_cents") or 0) - applied_total
        deal["unrecouped_advance_cents"] = \
            (deal["advance_amount_cents"] or 0) - deal["advance_recouped_cents"]
        deal["post_recoupment_net_receipts_cents"] = \
            (deal.get("post_recoupment_net_receipts_cents") or 0) - \
            ((report["net_receipts_cents"] or 0) - applied_total)
        for release_id, amount in applied.items():
            release = db.store.releases.get(release_id)
            if release is None:
                continue
            release["release_advance_recouped_cents"] = \
                (release.get("release_advance_recouped_cents") or 0) - amount
            release["unrecouped_advance_share_cents"] = max(
                0, (release.get("advance_share_cents") or 0)
                - release["release_advance_recouped_cents"])
            if release not in touched_releases:
                touched_releases.append(release)
        report["advance_applied_cents"] = 0
        report["_release_applied"] = {}
        # Hop 4: the mirror of the escalation trigger.
        if deal["unrecouped_advance_cents"] > 0 \
                and deal["recoupment_status"] == "RECOUPED":
            deal["recoupment_status"] = "UNRECOUPED"
            calculations.reselect_rates_for_deal(deal)
        for release in touched_releases:
            db.touch(release)

    report["status"] = "DISPUTED"
    report["dispute_reason"] = reason
    db.touch(report)
    db.touch(deal)
    return response.ok(serializers.report(report))
