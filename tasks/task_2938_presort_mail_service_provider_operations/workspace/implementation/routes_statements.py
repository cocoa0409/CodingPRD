"""Postage statements: preparation, filing, findings, verification and revision."""

from flask import Blueprint

import calc
import cascades
import domain
import enums
import serialize
import shape
from envelope import listed, single
from errors import ApiError
from routes_jobs import _require_fee_current
from store import db, touch
from util import round_half_up_div

bp = Blueprint("statements", __name__)

STATEMENT_READ_ROLES = (
    "BureauAdmin",
    "PostageManager",
    "AcceptanceClerk",
    "ClientContact",
)


@bp.post("/postage-statements")
def prepare_statement():
    user, _role = shape.authenticate(("PostageManager",))
    body = shape.validate_body(
        {
            "commingle_batch_id": {"type": "string"},
            "permit_account_id": {"type": "string"},
            "expected_batch_version": {"type": "integer"},
        }
    )
    # rung 5 — permit_account_id resolves before commingle_batch_id (§2.6)
    permit = domain.get_permit(body["permit_account_id"])
    batch = domain.get_batch(body["commingle_batch_id"])
    # rung 12
    if batch["status"] != "SORTED":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    # rung 17
    if body["expected_batch_version"] != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION")

    for predecessor in domain.batch_statements(batch["id"]):
        if predecessor["status"] == "DRAFT":
            cascades.void_statement(predecessor, calc.SUPERSEDED_VOID_REASON)

    record = db.insert(
        "postage_statements",
        {
            "commingle_batch_id": batch["id"],
            "permit_account_id": permit["id"],
            "prepared_by_user_id": user,
            "submitted_by_user_id": None,
            "verified_by_user_id": None,
            "statement_piece_count": batch["total_piece_count"],
            "rate_mills_per_piece": batch["rate_mills_per_piece"],
            "declared_postage_cents": batch["batch_postage_cents"],
            "adjustment_cents": 0,
            "verified_postage_cents": 0,
            "verification_error_count": 0,
            "revision_index": 0,
            "status": "DRAFT",
            "void_reason": None,
        },
    )
    touch(batch)
    return single(serialize.postage_statement(record), 201)


@bp.get("/postage-statements/<statement_id>")
def read_statement(statement_id):
    shape.authenticate(STATEMENT_READ_ROLES)
    return single(serialize.postage_statement(domain.get_statement(statement_id)))


@bp.post("/postage-statements/<statement_id>/submit")
def submit_statement(statement_id):
    user, _role = shape.authenticate(("PostageManager",))
    shape.validate_body({})
    statement = domain.get_statement(statement_id)
    # rung 13
    if statement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    batch = db.commingle_batches[statement["commingle_batch_id"]]
    if batch["status"] != "SORTED":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    permit = db.permit_accounts[statement["permit_account_id"]]
    # rung 19
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
    # rung 22
    _require_fee_current(permit)
    # rung 46
    if permit["balance_cents"] < statement["declared_postage_cents"]:
        raise ApiError("ERR_INSUFFICIENT_POSTAGE_BALANCE")

    statement["status"] = "SUBMITTED"
    statement["submitted_by_user_id"] = user
    permit["balance_cents"] -= statement["declared_postage_cents"]
    permit["reserved_cents"] += statement["declared_postage_cents"]
    touch(permit)
    batch["status"] = "DOCUMENTED"
    touch(batch)
    touch(statement)
    return single(serialize.postage_statement(statement))


@bp.post("/postage-statements/<statement_id>/findings")
def record_finding(statement_id):
    user, _role = shape.authenticate(("AcceptanceClerk",))
    body = shape.validate_body(
        {
            "finding_type": {"type": "enum", "values": enums.FINDING_TYPES},
            "affected_piece_count": {"type": "integer"},
        }
    )
    statement = domain.get_statement(statement_id)
    # rung 9
    if statement["submitted_by_user_id"] == user:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # rung 13
    if statement["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    affected = body["affected_piece_count"]
    # rung 31
    if affected < 1 or affected > statement["statement_piece_count"]:
        raise ApiError("ERR_INVALID_PIECE_COUNT")

    episode = domain.episode_findings(statement)
    cumulative = sum(f["affected_piece_count"] for f in episode) + affected
    if cumulative * 10000 >= (
        statement["statement_piece_count"] * calc.MAJOR_THRESHOLD_BP
    ):
        severity = "MAJOR"
    else:
        severity = "MINOR"
    surcharge = round_half_up_div(
        affected * statement["rate_mills_per_piece"]
        * calc.SEVERITY_SURCHARGE_BP[severity],
        10000000,
    )
    finding = db.insert(
        "verification_findings",
        {
            "postage_statement_id": statement["id"],
            "finding_type": body["finding_type"],
            "affected_piece_count": affected,
            "assessed_by_user_id": user,
            "severity": severity,
            "surcharge_cents": surcharge,
            "_episode": statement["revision_index"],
        },
        versioned=False,
    )
    statement["adjustment_cents"] = (
        sum(f["surcharge_cents"] for f in episode) + surcharge
    )
    statement["verification_error_count"] = len(episode) + 1
    touch(statement)
    return single(serialize.verification_finding(finding), 201)


@bp.get("/postage-statements/<statement_id>/findings")
def list_findings(statement_id):
    shape.authenticate(("BureauAdmin", "PostageManager", "AcceptanceClerk"))
    domain.get_statement(statement_id)
    return listed(
        domain.statement_findings(statement_id), serialize.verification_finding
    )


@bp.post("/postage-statements/<statement_id>/verify")
def verify_statement(statement_id):
    user, _role = shape.authenticate(("AcceptanceClerk",))
    body = shape.validate_body(
        {"outcome": {"type": "enum", "values": enums.VERIFY_OUTCOMES}}
    )
    statement = domain.get_statement(statement_id)
    # rung 9
    if statement["submitted_by_user_id"] == user:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # rung 13
    if statement["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    batch = db.commingle_batches[statement["commingle_batch_id"]]
    permit = db.permit_accounts[statement["permit_account_id"]]

    if body["outcome"] == "RETURN":
        # rung 42
        if statement["verification_error_count"] < 1:
            raise ApiError("ERR_NO_VERIFICATION_FINDINGS")
        cascades.return_for_correction(statement, batch, permit, user)
        return single(serialize.postage_statement(statement))

    adjustment = statement["adjustment_cents"]
    if adjustment == 0:
        cascades.accept_clean(statement, batch, permit, user)
        return single(serialize.postage_statement(statement))

    # rung 46
    if permit["balance_cents"] < adjustment:
        raise ApiError("ERR_INSUFFICIENT_POSTAGE_BALANCE")
    cascades.accept_with_adjustment(statement, batch, permit, user)
    return single(serialize.postage_statement(statement))


@bp.post("/postage-statements/<statement_id>/void")
def void_statement(statement_id):
    shape.authenticate(("PostageManager",))
    body = shape.validate_body({"reason": {"type": "string"}})
    statement = domain.get_statement(statement_id)
    # rung 13
    if statement["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    cascades.void_statement(statement, body["reason"])
    return single(serialize.postage_statement(statement))


@bp.post("/postage-statements/<statement_id>/revise")
def revise_statement(statement_id):
    shape.authenticate(("PostageManager",))
    shape.validate_body({})
    statement = domain.get_statement(statement_id)
    # rung 13
    if statement["status"] != "RETURNED_FOR_CORRECTION":
        raise ApiError("ERR_INVALID_STATEMENT_STATE")
    batch = db.commingle_batches[statement["commingle_batch_id"]]
    if batch["status"] != "REWORK":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    cascades.revise(statement, batch)
    return single(serialize.postage_statement(statement))
