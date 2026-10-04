"""Claims: submission across provider entities, adjudication waterfall, payment."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_bool,
    f_enum,
    f_int,
    new_row,
    paginate,
    respond_object,
    sort_created,
    touch,
)
from core import scope_employer
from domain import (
    CLAIM_TYPES,
    SUBMITTING_ENTITIES,
    dump_episode,
    episode_template,
    get_or_404,
    pool_remaining,
)

bp = Blueprint("claims", __name__)


def _episode_employer_id(ep):
    contract = db.contracts.get(ep["contract_id"])
    return contract["employer_id"] if contract else None


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------
@bp.route("/coe/episodes/<ep_id>/claims", methods=["POST"])
@endpoint("ClaimsAdmin")
def create_claim(ep_id):
    ep = get_or_404("episodes", ep_id)
    data = body()
    claim_type = f_enum(data, "claim_type", CLAIM_TYPES)
    submitting_entity = f_enum(data, "submitting_entity", SUBMITTING_ENTITIES)
    service_date_seq = f_int(data, "service_date_seq", minimum=0)
    billed = f_int(data, "billed_cents", minimum=0)
    expected = f_int(data, "expected_episode_version", minimum=0)
    is_readmit_related = f_bool(data, "is_readmit_related", required=False, default=None)
    if ep["status"] in ("CLOSED", "AVOIDED", "CANCELLED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Claims cannot be submitted on a terminal episode."
        )
    if expected != ep["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_episode_version is stale.")
    row = new_row(
        "claim",
        episode_id=ep["id"],
        claim_type=claim_type,
        submitting_entity=submitting_entity,
        service_date_seq=service_date_seq,
        billed_cents=billed,
        status="PENDING",
        adjudicated_payable_cents=None,
        adjudication_reason=None,
        is_readmit_related=is_readmit_related,
    )
    db.claims[row["id"]] = row
    touch(ep)
    return respond_object(dump(row), status=201)


@bp.route("/coe/episodes/<ep_id>/claims", methods=["GET"])
@endpoint("ProgramAdmin", "ClaimsAdmin", "EmployerRep")
def list_claims(ep_id):
    ep = get_or_404("episodes", ep_id)
    scope_employer(_episode_employer_id(ep))
    rows = [c for c in db.claims.values() if c["episode_id"] == ep["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/claims/<claim_id>", methods=["GET"])
@endpoint("ProgramAdmin", "ClaimsAdmin", "EmployerRep")
def get_claim(claim_id):
    row = get_or_404("claims", claim_id)
    ep = db.episodes.get(row["episode_id"])
    if ep is not None:
        scope_employer(_episode_employer_id(ep))
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Adjudication waterfall (PRD S3.7)
# ---------------------------------------------------------------------------
def _deny(claim, reason):
    claim["status"] = "DENIED"
    claim["adjudicated_payable_cents"] = 0
    claim["adjudication_reason"] = reason
    touch(claim)
    return respond_object(dump(claim))


def _approve(claim, payable):
    claim["status"] = "APPROVED"
    claim["adjudicated_payable_cents"] = payable
    claim["adjudication_reason"] = "APPROVED"
    touch(claim)
    return respond_object(dump(claim))


def _adjudicate_bundle_case(claim, ep, contract):
    if ep["surgery_done_seq"] == 0 or claim["service_date_seq"] < ep["surgery_done_seq"]:
        return _deny(claim, "SERVICE_BEFORE_SURGERY")
    for other in db.claims.values():
        if (
            other["id"] != claim["id"]
            and other["episode_id"] == ep["id"]
            and other["claim_type"] == "BUNDLE_CASE"
            and other["status"] in ("APPROVED", "PAID", "ABSORBED")
        ):
            return _deny(claim, "DUPLICATE_BUNDLE_CASE")
    excess = max(0, claim["billed_cents"] - contract["outlier_threshold_cents"])
    outlier_payable = (excess * contract["outlier_share_pct"]) // 100
    payable = (ep["applied_bundle_price_cents"] or 0) + outlier_payable
    return _approve(claim, payable)


def _adjudicate_related_care(claim, ep, contract):
    if ep["status"] not in ("POST_OP_TRACKING", "CLOSED"):
        return _deny(claim, "OUTSIDE_WARRANTY_WINDOW")
    if not (ep["discharge_seq"] <= claim["service_date_seq"] < ep["warranty_end_seq"]):
        return _deny(claim, "OUTSIDE_WARRANTY_WINDOW")
    allocated = sum(
        c["adjudicated_payable_cents"] or 0
        for c in db.claims.values()
        if c["episode_id"] == ep["id"]
        and c["claim_type"] in ("BUNDLE_CASE", "RELATED_CARE")
        and c["status"] in ("APPROVED", "PAID")
    )
    payable = min(claim["billed_cents"], max(0, (ep["applied_bundle_price_cents"] or 0) - allocated))
    return _approve(claim, payable)


def _adjudicate_benefit_claim(claim, ep, contract):
    if ep["applied_bundle_price_cents"] is None:
        return _deny(claim, "EPISODE_NOT_APPROVED")
    remaining = pool_remaining(ep, claim["claim_type"])
    if remaining == 0:
        return _deny(claim, "BENEFIT_POOL_EXHAUSTED")
    payable = min(claim["billed_cents"], remaining)
    return _approve(claim, payable)


def _adjudicate_readmission(claim, ep, contract):
    match = None
    for r in sort_created(db.readmissions.values()):
        if r["episode_id"] != ep["id"]:
            continue
        if ep["discharge_seq"] <= r["recorded_seq"] < ep["warranty_end_seq"]:
            match = r
            break
    if match is None:
        return _deny(claim, "READMISSION_OUT_OF_WINDOW")
    template = episode_template(ep)
    if template["readmit_policy"] == "RELATED_ONLY" and claim["is_readmit_related"] is False:
        return _deny(claim, "UNRELATED_READMISSION")
    payable = max(0, claim["billed_cents"] - match["absorbed_cents"])
    return _approve(claim, payable)


@bp.route("/coe/claims/<claim_id>/adjudicate", methods=["POST"])
@endpoint("ClaimsAdmin")
def adjudicate_claim(claim_id):
    claim = get_or_404("claims", claim_id)
    if claim["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Claim is not PENDING.")
    ep = db.episodes.get(claim["episode_id"])
    contract = db.contracts.get(ep["contract_id"]) if ep else None
    if claim["claim_type"] == "BUNDLE_CASE":
        return _adjudicate_bundle_case(claim, ep, contract)
    if claim["claim_type"] == "RELATED_CARE":
        return _adjudicate_related_care(claim, ep, contract)
    if claim["claim_type"] in ("TRAVEL", "LODGING"):
        return _adjudicate_benefit_claim(claim, ep, contract)
    return _adjudicate_readmission(claim, ep, contract)


@bp.route("/coe/claims/<claim_id>/pay", methods=["POST"])
@endpoint("ClaimsAdmin")
def pay_claim(claim_id):
    claim = get_or_404("claims", claim_id)
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not APPROVED.")
    claim["status"] = "PAID"
    touch(claim)
    return respond_object(dump(claim))
