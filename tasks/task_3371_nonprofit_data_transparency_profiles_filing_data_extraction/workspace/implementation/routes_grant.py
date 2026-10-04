"""Grant records, recipient matching and funder prospect research (PRD 3.9)."""

from flask import Blueprint, request

import auth
import calc
import response
import store
import svc
import webutil
from errors import ApiError, ERR_FORBIDDEN_ROLE, ERR_GRANT_NOT_FOUND, ERR_INVALID_REQUEST

bp = Blueprint("grants", __name__)

GRANT_FIELDS = (
    "funder_organization_id", "funder_name_raw", "recipient_name_raw",
    "amount_cents", "fiscal_year", "recipient_ein", "subject_code",
)


def _recompute_funder_counts(*organizations):
    for org in organizations:
        if org is not None:
            svc.recompute_counters(org)


@bp.route("/nonprofits/organizations/<org_id>/grants", methods=["POST"])
def create_grant(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_DATA_CONSUMER, auth.ROLE_PLATFORM_ADMIN))
    recipient_org = svc.get_organization(org_id)

    data = webutil.body()
    webutil.reject_unknown(data, GRANT_FIELDS)

    declared_funder = data.get("funder_organization_id")
    if (acting.role == auth.ROLE_DATA_CONSUMER and isinstance(declared_funder, str)
            and declared_funder not in (acting.user_id, org_id)):
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "A DataConsumer may record grants only as itself.",
        )

    funder_organization_id = webutil.as_string(data, "funder_organization_id")
    funder_name_raw = webutil.as_string(data, "funder_name_raw")
    recipient_name_raw = webutil.as_string(data, "recipient_name_raw")
    amount_cents = webutil.as_int(data, "amount_cents")
    fiscal_year = webutil.as_int(data, "fiscal_year")
    recipient_ein = webutil.as_string(data, "recipient_ein", required=False)
    subject_code = webutil.as_string(data, "subject_code", required=False)

    funder_org = svc.get_organization(funder_organization_id)

    grant = store.new_row(
        recipient_organization_id=org_id,
        funder_organization_id=funder_organization_id,
        funder_name_raw=funder_name_raw,
        recipient_name_raw=recipient_name_raw,
        recipient_ein=recipient_ein,
        amount_cents=amount_cents,
        fiscal_year=fiscal_year,
        subject_code=subject_code,
        taxonomy_source="FUNDER_SUPPLIED" if subject_code is not None else "UNCODED",
        match_score=0,
        recipient_match_status="UNMATCHED",
        status="RECORDED",
    )
    grant["match_score"] = calc.grant_match_score(grant, recipient_org)
    grant["recipient_match_status"] = calc.grant_match_status(grant["match_score"])
    store.insert("grants", grant)

    _recompute_funder_counts(recipient_org, funder_org)
    return response.ok(svc.ser_grant(grant), status=201)


@bp.route("/nonprofits/grants/<grant_id>/match-recipient", methods=["POST"])
def match_recipient(grant_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_DATA_CONSUMER, auth.ROLE_PLATFORM_ADMIN))
    grant = svc.get_grant(grant_id)
    auth.require_owner(acting, grant.get("funder_organization_id"), "grants")

    data = webutil.body()
    webutil.reject_unknown(data, ("recipient_ein", "subject_code"))
    recipient_ein = webutil.as_string(data, "recipient_ein", required=False)
    subject_code = webutil.as_string(data, "subject_code", required=False)

    recipient_org = store.find("organizations", grant.get("recipient_organization_id"))
    if recipient_org is None:
        raise ApiError(ERR_INVALID_REQUEST, "The grant's recipient organization no longer exists.")

    if recipient_ein is not None:
        grant["recipient_ein"] = recipient_ein
    if subject_code is not None:
        grant["subject_code"] = subject_code
        grant["taxonomy_source"] = "FUNDER_SUPPLIED"

    score = calc.grant_match_score(grant, recipient_org)
    status = calc.grant_match_status(score)
    if (subject_code is None and status == "MATCHED"
            and recipient_org.get("ntee_code") is not None):
        grant["subject_code"] = recipient_org.get("ntee_code")
        grant["taxonomy_source"] = "AUTO_CODED"
        score = calc.grant_match_score(grant, recipient_org)
        status = calc.grant_match_status(score)
    grant["match_score"] = score
    grant["recipient_match_status"] = status
    store.touch(grant)
    return response.ok(svc.ser_grant(grant))


@bp.route("/nonprofits/funder-research/prospects", methods=["GET"])
def funder_research_prospects():
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER, auth.ROLE_DATA_CONSUMER,
    ))

    funder_organization_id = request.args.get("funder_organization_id")
    if not funder_organization_id:
        raise ApiError(ERR_INVALID_REQUEST, "funder_organization_id is required.")
    funder = svc.get_organization(funder_organization_id)

    subject_code = request.args.get("subject_code") or None
    min_score_raw = request.args.get("min_score")
    min_score = None
    if min_score_raw not in (None, ""):
        try:
            min_score = int(min_score_raw)
        except ValueError:
            min_score = None

    excluded = set()
    for case in store.rows("identity_cases"):
        if case.get("status") != "OPEN":
            continue
        if funder_organization_id not in (
            case.get("subject_organization_id"), case.get("surviving_organization_id")
        ):
            continue
        excluded.add(case.get("subject_organization_id"))
        excluded.add(case.get("surviving_organization_id"))

    funder_grants = [
        g for g in store.rows("grants")
        if g.get("funder_organization_id") == funder_organization_id
        and g.get("status") == "RECORDED"
    ]
    mean_amount = calc.mean_grant_amount_cents(funder_grants)

    prospects = []
    for candidate in store.rows("organizations"):
        if candidate.get("profile_status") != "ACTIVE":
            continue
        if candidate["id"] == funder_organization_id:
            continue
        if candidate["id"] in excluded:
            continue
        to_candidate = [g for g in funder_grants
                        if g.get("recipient_organization_id") == candidate["id"]]
        score = calc.prospect_score(candidate, funder, mean_amount, to_candidate, subject_code)
        if min_score is not None and score < min_score:
            continue
        payload = svc.ser_organization(candidate)
        payload["match_score"] = score
        payload["historical_giving_cents"] = calc.historical_giving_cents(to_candidate)
        prospects.append(payload)

    prospects.sort(key=lambda item: (
        -item["match_score"],
        -item["historical_giving_cents"],
        item["created_at"],
    ))

    limit, offset = response.read_pagination(request.args)
    total = len(prospects)
    page = prospects[offset:offset + limit]
    payload = {
        "funder_organization_id": funder_organization_id,
        "mean_grant_amount_cents": calc.to_int(mean_amount),
        "prospects": page,
    }
    return response.ok(payload, pagination={
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
