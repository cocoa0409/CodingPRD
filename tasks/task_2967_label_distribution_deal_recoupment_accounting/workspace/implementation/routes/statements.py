"""Artist statements, the deduction waterfall, objections and audit rights
(PRD sections 3.8 and 3.9)."""

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (ARTIST, BUSINESS_AFFAIRS, LABEL_ADMIN,
                           ROYALTY_ANALYST, find_agreement, find_statement,
                           require_owner, require_separation)
from services import calculations, lookups

bp = Blueprint("statements", __name__)

BASIS_VARIANTS = ("PROVISIONAL", "FINAL")
STATEMENTABLE = ("ACTIVE", "AMENDMENT_PENDING", "POST_TERM")
OBJECTION_CODES = ("RATE_DISPUTE", "MISSING_REVENUE", "COST_DISPUTE",
                   "RESERVE_DISPUTE")
READERS = [LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS, ARTIST]


def _accountable_span(deal):
    start = db.parse_date(deal["term_start_date"])
    if deal.get("post_term_collection_end_date"):
        end = db.parse_date(deal["post_term_collection_end_date"])
    else:
        end = db.parse_date(deal["term_end_date"])
    return start, end


def _context(statement):
    """The agreement, release and deal a statement accounts against."""
    agreement = lookups.agreement_of_statement(statement)
    release = lookups.release_of_agreement(agreement) if agreement else None
    deal = lookups.deal_of_release(release) if release else None
    return agreement, release, deal


@bp.route("/artist-statements", methods=["POST"])
def create_statement():
    authenticate([ROYALTY_ANALYST])
    body = parse_body()
    agreement_id = v.identifier(body, "artist_agreement_id", required=True)
    period_start = v.date_field(body, "period_start", required=True)
    period_end = v.date_field(body, "period_end", required=True)
    if period_end < period_start:
        v.bad("period_end", "may not fall before period_start.")
    basis_variant = v.enum(body, "basis_variant", BASIS_VARIANTS, required=True)

    agreement = find_agreement(agreement_id)
    if agreement["status"] not in STATEMENTABLE:
        raise ApiError("ERR_AGREEMENT_NOT_STATEMENTABLE")

    record = db.base_record()
    record.update({
        "artist_agreement_id": agreement_id,
        "period_start": db.date_str(period_start),
        "period_end": db.date_str(period_end),
        "basis_variant": basis_variant,
        "status": "DRAFT",
        "audit_status": "NONE",
        "prepared_by_user_id": None,
        "issued_by_user_id": None,
        "issued_at": None,
        "objection_deadline": None,
        "finalized_at": None,
        "applied_royalty_rate_pct": None,
        "digital_royalty_base_cents": 0,
        "physical_royalty_base_cents": 0,
        "gross_royalty_cents": 0,
        "marketing_cap_cents": 0,
        "advance_applied_cents": 0,
        "recording_applied_cents": 0,
        "marketing_applied_cents": 0,
        "reserve_withheld_cents": 0,
        "net_payable_cents": 0,
        "objection_reason_code": None,
        "objection_disputed_amount_cents": None,
        "objection_narrative": None,
        "objection_filed_at": None,
        "objection_resolution": None,
        "objection_adjustment_cents": None,
        "audit_scope_period_start": None,
        "audit_scope_period_end": None,
        "auditor_name": None,
        "audit_findings_adjustment_cents": None,
        "audit_cost_bearer": None,
        "revision_count": 0,
    })
    db.store.statements[record["id"]] = record
    return response.created(serializers.statement(record))


@bp.route("/artist-statements/<record_id>", methods=["GET"])
def get_statement(record_id):
    caller = authenticate(READERS)
    statement = find_statement(record_id)
    agreement = lookups.agreement_of_statement(statement)
    require_owner(caller, agreement["artist_id"] if agreement else None)
    return response.ok(serializers.statement(statement))


@bp.route("/artist-statements", methods=["GET"])
def list_statements():
    authenticate(READERS)
    limit, offset = pagination()
    records = db.ordered(list(db.store.statements.values()))
    for key in ("artist_agreement_id", "basis_variant", "status", "audit_status"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.statement(r) for r in page], limit, offset, total)


def _final_siblings(statement, agreement):
    """The agreement's other non-VOIDED FINAL statements (PRD section 3.8)."""
    return [
        s for s in lookups.statements_of_agreement(agreement["id"])
        if s["id"] != statement["id"]
        and s["basis_variant"] == "FINAL"
        and s["status"] != "VOIDED"
    ]


@bp.route("/artist-statements/<record_id>/prepare", methods=["POST"])
def prepare_statement(record_id):
    caller = authenticate([ROYALTY_ANALYST])
    statement = find_statement(record_id)
    parse_body()
    if statement["status"] not in ("DRAFT", "REVISED"):
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    agreement, release, deal = _context(statement)
    if agreement is None or agreement["status"] not in STATEMENTABLE:
        raise ApiError("ERR_AGREEMENT_NOT_STATEMENTABLE")

    period_start = db.parse_date(statement["period_start"])
    period_end = db.parse_date(statement["period_end"])
    from_draft = statement["status"] == "DRAFT"

    if from_draft:
        # Rank 10: the period must lie inside the deal's accountable span.
        if deal is not None:
            span_start, span_end = _accountable_span(deal)
            if period_start < span_start or period_end > span_end:
                raise ApiError("ERR_PERIOD_OUTSIDE_TERM")
        # Rank 11: FINAL statements tile the agreement's history exactly once.
        if statement["basis_variant"] == "FINAL":
            siblings = _final_siblings(statement, agreement)
            for sibling in siblings:
                other_start = db.parse_date(sibling["period_start"])
                other_end = db.parse_date(sibling["period_end"])
                if period_start <= other_end and other_start <= period_end:
                    raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP")
            if siblings:
                latest_end = max(db.parse_date(s["period_end"]) for s in siblings)
                if period_start != db.add_days(latest_end, 1):
                    raise ApiError("ERR_STATEMENT_PERIOD_NOT_CONTIGUOUS")

    if release is None:
        raise ApiError("ERR_RELEASE_NOT_FOUND")

    figures = calculations.statement_figures(statement, agreement, release, deal)
    statement.update(figures)
    statement["prepared_by_user_id"] = caller.user_id
    statement["status"] = "PREPARED"
    if not from_draft:
        # The granted objection adjustment is added back after the floor.
        statement["net_payable_cents"] += \
            statement.get("objection_adjustment_cents") or 0
        statement["revision_count"] = (statement.get("revision_count") or 0) + 1
    db.touch(statement)
    return response.ok(serializers.statement(statement))


@bp.route("/artist-statements/<record_id>/issue", methods=["POST"])
def issue_statement(record_id):
    caller = authenticate([BUSINESS_AFFAIRS])
    statement = find_statement(record_id)
    parse_body()
    if statement["status"] not in ("PREPARED", "OBJECTED"):
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    require_separation(caller, statement.get("prepared_by_user_id"))
    if statement["basis_variant"] != "FINAL":
        raise ApiError("ERR_PROVISIONAL_NOT_ISSUABLE")
    agreement, release, deal = _context(statement)
    issued_at = db.store.now()
    statement["status"] = "ISSUED"
    statement["issued_at"] = db.iso_instant(issued_at)
    statement["issued_by_user_id"] = caller.user_id
    window_days = (deal or {}).get("objection_window_days") or 0
    statement["objection_deadline"] = db.iso_instant(
        db.add_days(issued_at, window_days))
    db.touch(statement)
    return response.ok(serializers.statement(statement))


@bp.route("/artist-statements/<record_id>/object", methods=["POST"])
def object_to_statement(record_id):
    caller = authenticate([ARTIST])
    statement = find_statement(record_id)
    agreement = lookups.agreement_of_statement(statement)
    require_owner(caller, agreement["artist_id"] if agreement else None)
    body = parse_body()
    reason_code = v.enum(body, "objection_reason_code", OBJECTION_CODES,
                         required=True)
    disputed = v.integer(body, "objection_disputed_amount_cents", required=True,
                         minimum=0)
    narrative = v.text(body, "objection_narrative", required=True, min_len=1,
                       max_len=None)
    if statement["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    deadline = db.parse_instant(statement.get("objection_deadline"))
    if deadline is not None and db.store.now() > deadline:
        raise ApiError("ERR_OBJECTION_WINDOW_CLOSED")
    ceiling = (statement.get("net_payable_cents") or 0) \
        + (statement.get("marketing_applied_cents") or 0) \
        + (statement.get("reserve_withheld_cents") or 0)
    if disputed > ceiling:
        raise ApiError("ERR_DISPUTED_AMOUNT_EXCEEDS_NET")
    statement["status"] = "OBJECTED"
    statement["objection_reason_code"] = reason_code
    statement["objection_disputed_amount_cents"] = disputed
    statement["objection_narrative"] = narrative
    statement["objection_filed_at"] = db.iso_instant(db.store.now())
    db.touch(statement)
    return response.ok(serializers.statement(statement))


@bp.route("/artist-statements/<record_id>/resolve-objection", methods=["POST"])
def resolve_objection(record_id):
    caller = authenticate([BUSINESS_AFFAIRS])
    statement = find_statement(record_id)
    body = parse_body()
    resolution = v.enum(body, "resolution", ("UPHELD", "DENIED"), required=True)
    adjustment = v.integer(body, "objection_adjustment_cents", required=False,
                           minimum=0)
    if statement["status"] != "OBJECTED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    require_separation(caller, statement.get("prepared_by_user_id"))
    statement["objection_resolution"] = resolution
    if resolution == "DENIED":
        # The window does not reopen: objection_deadline is left exactly as it was.
        statement["status"] = "ISSUED"
        statement["objection_adjustment_cents"] = None
    else:
        statement["status"] = "REVISED"
        statement["objection_adjustment_cents"] = adjustment
        statement["issued_at"] = None
        statement["issued_by_user_id"] = None
        statement["objection_deadline"] = None
    db.touch(statement)
    return response.ok(serializers.statement(statement))


AUDIT_WINDOW_DAYS = 365


@bp.route("/artist-statements/<record_id>/finalize", methods=["POST"])
def finalize_statement(record_id):
    caller = authenticate([BUSINESS_AFFAIRS])
    statement = find_statement(record_id)
    parse_body()
    if statement["status"] not in ("ISSUED", "PREPARED"):
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    agreement, release, deal = _context(statement)
    from_issued = statement["status"] == "ISSUED"

    if from_issued:
        # The audit axis gates the accounting axis.
        if statement["audit_status"] == "AUDIT_REQUESTED":
            raise ApiError("ERR_INVALID_STATEMENT_STATE")
    else:
        # The post-term collection path.
        if agreement is None or agreement["status"] != "POST_TERM":
            raise ApiError("ERR_INVALID_AGREEMENT_STATE")

    require_separation(caller, statement.get("prepared_by_user_id"))

    if from_issued:
        deadline = db.parse_instant(statement.get("objection_deadline"))
        if deadline is not None and db.store.now() <= deadline:
            raise ApiError("ERR_OBJECTION_WINDOW_OPEN")
    elif statement["basis_variant"] != "FINAL":
        raise ApiError("ERR_PROVISIONAL_NOT_ISSUABLE")

    # The debits: the only place the artist-side ledgers move.
    if agreement is not None:
        agreement["unrecouped_artist_advance_cents"] = \
            (agreement.get("unrecouped_artist_advance_cents") or 0) \
            - (statement.get("advance_applied_cents") or 0)
        agreement["unrecouped_recording_cents"] = \
            (agreement.get("unrecouped_recording_cents") or 0) \
            - (statement.get("recording_applied_cents") or 0)
        db.touch(agreement)
    if release is not None:
        release["recoupable_marketing_applied_cents"] = \
            (release.get("recoupable_marketing_applied_cents") or 0) \
            + (statement.get("marketing_applied_cents") or 0)
        db.touch(release)

    statement["status"] = "FINALIZED"
    statement["finalized_at"] = db.iso_instant(db.store.now())
    db.touch(statement)
    return response.ok(serializers.statement(statement))


@bp.route("/artist-statements/<record_id>/request-audit", methods=["POST"])
def request_audit(record_id):
    caller = authenticate([ARTIST])
    statement = find_statement(record_id)
    agreement = lookups.agreement_of_statement(statement)
    require_owner(caller, agreement["artist_id"] if agreement else None)
    body = parse_body()
    scope_start = v.date_field(body, "audit_scope_period_start", required=True)
    scope_end = v.date_field(body, "audit_scope_period_end", required=True)
    if scope_end < scope_start:
        v.bad("audit_scope_period_end",
              "may not fall before audit_scope_period_start.")
    auditor_name = v.text(body, "auditor_name", required=True, min_len=1,
                          max_len=None)
    if statement["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    if statement["audit_status"] != "NONE":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    finalized_at = db.parse_instant(statement.get("finalized_at"))
    if finalized_at is not None and \
            db.store.now() > db.add_days(finalized_at, AUDIT_WINDOW_DAYS):
        raise ApiError("ERR_AUDIT_WINDOW_EXPIRED")
    statement["audit_status"] = "AUDIT_REQUESTED"
    statement["audit_scope_period_start"] = db.date_str(scope_start)
    statement["audit_scope_period_end"] = db.date_str(scope_end)
    statement["auditor_name"] = auditor_name
    db.touch(statement)
    return response.ok(serializers.statement(statement))


@bp.route("/artist-statements/<record_id>/conclude-audit", methods=["POST"])
def conclude_audit(record_id):
    caller = authenticate([BUSINESS_AFFAIRS])
    statement = find_statement(record_id)
    body = parse_body()
    findings = v.integer(body, "findings_adjustment_cents", required=True)
    if statement["audit_status"] != "AUDIT_REQUESTED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    require_separation(caller, statement.get("prepared_by_user_id"))

    agreement, release, deal = _context(statement)
    scope_start = db.parse_date(statement.get("audit_scope_period_start"))
    scope_end = db.parse_date(statement.get("audit_scope_period_end"))
    period_start = db.parse_date(statement["period_start"])
    period_end = db.parse_date(statement["period_end"])
    contained = (scope_start is not None and scope_end is not None
                 and scope_start >= period_start and scope_end <= period_end)

    if not contained:
        statement["audit_status"] = "AUDIT_DENIED"
        statement["audit_findings_adjustment_cents"] = None
        statement["audit_cost_bearer"] = "ARTIST"
        db.touch(statement)
        return response.ok(serializers.statement(statement))

    statement["audit_status"] = "AUDIT_COMPLETED"
    statement["audit_findings_adjustment_cents"] = findings
    threshold = calculations.materiality_threshold(
        statement.get("net_payable_cents") or 0)
    material = abs(findings) >= threshold
    statement["audit_cost_bearer"] = "LABEL" if material else "ARTIST"

    if material and statement["status"] == "FINALIZED":
        # Compensating action: the exact inverse of the finalize debit.
        if agreement is not None:
            agreement["unrecouped_artist_advance_cents"] = \
                (agreement.get("unrecouped_artist_advance_cents") or 0) \
                + (statement.get("advance_applied_cents") or 0)
            agreement["unrecouped_recording_cents"] = \
                (agreement.get("unrecouped_recording_cents") or 0) \
                + (statement.get("recording_applied_cents") or 0)
            db.touch(agreement)
        if release is not None:
            release["recoupable_marketing_applied_cents"] = \
                (release.get("recoupable_marketing_applied_cents") or 0) \
                - (statement.get("marketing_applied_cents") or 0)
            db.touch(release)
        statement["status"] = "REVISED"
        statement["issued_at"] = None
        statement["objection_deadline"] = None
        statement["finalized_at"] = None

    db.touch(statement)
    return response.ok(serializers.statement(statement))
