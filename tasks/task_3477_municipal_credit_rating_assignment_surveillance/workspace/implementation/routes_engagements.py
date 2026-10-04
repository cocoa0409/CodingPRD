"""Rating engagement lifecycle (PRD §3.1, §3.2): open, accept terms, submit
documents, withdraw. Validation checks follow the PRD §2.10 priority order."""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

from auth import auth, authenticate
from constants import (
    CREDIT_TYPES,
    DOCUMENT_REGISTRY,
    EVENT_ENGAGEMENT_WITHDRAWN,
    FEE_BY_CREDIT_TYPE,
    FEE_UNSOLICITED_CENTS,
    ROLE_ISSUER,
    ROLE_LEAD_ANALYST,
    ROLE_UNDERWRITER,
    SOLICITATIONS,
    SOLICITED_REQUIRED_DOCS_BY_CREDIT_TYPE,
    UNSOLICITED_REQUIRED_DOCS,
    WITHDRAWAL_REFUND_RATIO,
)
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_DOCUMENT_CODE_UNKNOWN,
    ERR_DUPLICATE_DOCUMENT,
    ERR_ENGAGEMENT_STATE_INVALID,
    ERR_FEE_PAYMENT_MISMATCH,
    ERR_INSUFFICIENT_ISSUER_CREDIT,
    ERR_ISSUER_DELINQUENT,
    ERR_NOT_RESOURCE_OWNER,
    ERR_UNAUTHORIZED_ROLE,
    ERR_WITHDRAWAL_NOT_PERMITTED,
    raise_err,
)
from store import db, new_entity, notify, touch
from validators import (
    body,
    get_engagement,
    get_issuer,
    get_underwriter,
    optional_int,
    present,
    require_enum,
    require_fields,
    require_int,
)

bp = Blueprint("engagements", __name__)

_WHOLE_CENT = Decimal("1")


@bp.route("/muni/engagements", methods=["POST"])
def create_engagement():
    user_id, role = auth([ROLE_ISSUER, ROLE_UNDERWRITER, ROLE_LEAD_ANALYST])
    payload = body()

    # Priority 2 (solicitation-role rule): evaluated when solicitation carries
    # a declared value; a missing/invalid value falls through to priority 4.
    solicitation = payload.get("solicitation")
    if solicitation == "UNSOLICITED" and role != ROLE_LEAD_ANALYST:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only a LeadAnalyst may open an unsolicited engagement")
    if solicitation == "SOLICITED" and role not in (ROLE_ISSUER, ROLE_UNDERWRITER):
        raise_err(ERR_UNAUTHORIZED_ROLE, "only an Issuer or Underwriter may open a solicited engagement")

    # Priority 3: body-supplied FK references must exist (issuer, underwriter).
    issuer = None
    if present(payload, "issuer_id"):
        issuer = get_issuer(payload["issuer_id"])
    underwriter = None
    if present(payload, "underwriter_id"):
        underwriter = get_underwriter(payload["underwriter_id"])

    # Priority 4: well-formedness.
    require_fields(payload, ["issuer_id", "solicitation", "credit_type", "jurisdiction_code"])
    require_enum(payload, "solicitation", SOLICITATIONS)
    require_enum(payload, "credit_type", CREDIT_TYPES)

    # Priority 5: ownership — an Issuer opens its own engagement; an
    # Underwriter must name itself in underwriter_id.
    if role == ROLE_ISSUER and payload["issuer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "issuer may only open its own engagements")
    if role == ROLE_UNDERWRITER and payload.get("underwriter_id") != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "underwriter must name itself in underwriter_id")

    # Priority 10(m): a delinquent issuer may not open new SOLICITED engagements.
    if solicitation == "SOLICITED" and issuer["delinquent_flag"]:
        raise_err(ERR_ISSUER_DELINQUENT, "issuer has a delinquent disclosure flag")

    solicited = solicitation == "SOLICITED"
    ent = new_entity()
    ent.update(
        issuer_id=payload["issuer_id"],
        underwriter_id=payload.get("underwriter_id"),
        solicitation=solicitation,
        credit_type=payload["credit_type"],
        jurisdiction_code=payload["jurisdiction_code"],
        fee_cents=FEE_BY_CREDIT_TYPE[payload["credit_type"]] if solicited else FEE_UNSOLICITED_CENTS,
        fee_paid=False if solicited else True,  # unsolicited fee waived
        refund_cents=0,
        required_document_codes=(
            list(SOLICITED_REQUIRED_DOCS_BY_CREDIT_TYPE[payload["credit_type"]])
            if solicited
            else list(UNSOLICITED_REQUIRED_DOCS)
        ),
        received_document_codes=[],
        assigned_analyst_id=None,
        status="REQUESTED" if solicited else "INFORMATION_GATHERING",
    )
    db.engagements[ent["id"]] = ent
    return success_object(ent, status=201)


@bp.route("/muni/engagements", methods=["GET"])
def list_engagements():
    authenticate()
    items = list(db.engagements.values())
    for field in ("issuer_id", "underwriter_id", "status", "credit_type"):
        value = request.args.get(field)
        if value is not None:
            items = [e for e in items if e.get(field) == value]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/engagements/<engagement_id>", methods=["GET"])
def get_one_engagement(engagement_id):
    authenticate()
    return success_object(get_engagement(engagement_id))


@bp.route("/muni/engagements/<engagement_id>/accept-terms", methods=["POST"])
def accept_terms(engagement_id):
    user_id, role = auth([ROLE_ISSUER])
    engagement = get_engagement(engagement_id)
    payload = body()
    require_fields(payload, ["fee_payment_cents"])
    fee_payment_cents = require_int(payload, "fee_payment_cents")
    apply_credit_cents = optional_int(payload, "apply_credit_cents", 0)

    # Priority 5: ownership.
    if engagement["issuer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the engagement's issuer may accept terms")

    # Priority 6: state — only REQUESTED (i.e. a SOLICITED engagement) accepts.
    if engagement["status"] != "REQUESTED":
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement is not in REQUESTED")

    # Priority 11: fee settlement.
    issuer = get_issuer(engagement["issuer_id"])
    if fee_payment_cents + apply_credit_cents != engagement["fee_cents"]:
        raise_err(ERR_FEE_PAYMENT_MISMATCH, "fee_payment_cents + apply_credit_cents must equal fee_cents")
    if apply_credit_cents > issuer["credit_balance_cents"]:
        raise_err(ERR_INSUFFICIENT_ISSUER_CREDIT, "apply_credit_cents exceeds the issuer credit balance")

    engagement["status"] = "ENGAGED"
    engagement["fee_paid"] = True
    touch(engagement)
    if apply_credit_cents:
        issuer["credit_balance_cents"] -= apply_credit_cents
        touch(issuer)
    return success_object(engagement)


@bp.route("/muni/engagements/<engagement_id>/documents", methods=["POST"])
def submit_document(engagement_id):
    user_id, role = auth([ROLE_ISSUER, ROLE_LEAD_ANALYST])
    engagement = get_engagement(engagement_id)
    payload = body()
    require_fields(payload, ["document_code"])
    document_code = payload["document_code"]

    # Solicitation-role refinement (RBAC table): Issuer submits on SOLICITED
    # engagements, LeadAnalyst on UNSOLICITED ones.
    if engagement["solicitation"] == "SOLICITED" and role != ROLE_ISSUER:
        raise_err(ERR_UNAUTHORIZED_ROLE, "solicited engagement documents are submitted by the issuer")
    if engagement["solicitation"] == "UNSOLICITED" and role != ROLE_LEAD_ANALYST:
        raise_err(ERR_UNAUTHORIZED_ROLE, "unsolicited engagement documents are submitted by the lead analyst")

    # Priority 5: ownership for the issuer-submitted (SOLICITED) path.
    if role == ROLE_ISSUER and engagement["issuer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the engagement's issuer may submit documents")

    # Priority 6: documents are accepted only while ENGAGED / INFORMATION_GATHERING.
    if engagement["status"] not in ("ENGAGED", "INFORMATION_GATHERING"):
        raise_err(ERR_ENGAGEMENT_STATE_INVALID, "engagement is not accepting documents")

    # Priority 10(e): registry membership, then duplicate.
    if document_code not in DOCUMENT_REGISTRY:
        raise_err(ERR_DOCUMENT_CODE_UNKNOWN, "unknown document code: %s" % document_code)
    if document_code in engagement["received_document_codes"]:
        raise_err(ERR_DUPLICATE_DOCUMENT, "document already received: %s" % document_code)

    engagement["received_document_codes"].append(document_code)
    if set(engagement["required_document_codes"]) <= set(engagement["received_document_codes"]):
        engagement["status"] = "ANALYSIS"
    elif engagement["status"] == "ENGAGED":
        engagement["status"] = "INFORMATION_GATHERING"
    touch(engagement)
    return success_object(engagement)


@bp.route("/muni/engagements/<engagement_id>/withdraw", methods=["POST"])
def withdraw_engagement(engagement_id):
    user_id, role = auth([ROLE_ISSUER])
    engagement = get_engagement(engagement_id)

    # Priority 5: ownership.
    if engagement["issuer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "only the engagement's issuer may withdraw it")

    # Priority 6: withdrawal is never available on unsolicited engagements,
    # nor once the engagement has reached RATING_ASSIGNED.
    if engagement["solicitation"] != "SOLICITED" or engagement["status"] not in (
        "REQUESTED",
        "ENGAGED",
        "INFORMATION_GATHERING",
        "ANALYSIS",
        "COMMITTEE_READY",
    ):
        raise_err(ERR_WITHDRAWAL_NOT_PERMITTED, "engagement may not be withdrawn in its current state")

    refund_cents = 0
    if engagement["fee_paid"]:
        refund = (Decimal(engagement["fee_cents"]) * WITHDRAWAL_REFUND_RATIO).quantize(
            _WHOLE_CENT, rounding=ROUND_HALF_UP
        )
        refund_cents = int(refund)
    engagement["refund_cents"] = refund_cents
    engagement["status"] = "WITHDRAWN"
    touch(engagement)
    if refund_cents:
        issuer = get_issuer(engagement["issuer_id"])
        issuer["credit_balance_cents"] += refund_cents
        touch(issuer)
    notify(
        engagement["issuer_id"],
        EVENT_ENGAGEMENT_WITHDRAWN,
        engagement["id"],
        "Engagement %s withdrawn; refund of %d cents credited."
        % (engagement["id"], refund_cents),
    )
    return success_object(engagement)
