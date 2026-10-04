"""SubjectCompany registration and retrieval."""
from flask import Blueprint

import envelope
import errors
import requtil
import rules
import store

bp = Blueprint("companies", __name__)


@bp.route("/enforcement/subject-companies", methods=["POST"])
def register_company():
    _user_id, role = requtil.context()
    requtil.require_role(role, ["PlatformAdmin"])
    body = requtil.json_body()
    legal_name = requtil.need_str(body, "legal_name")
    complaint_count = body.get("complaint_count_90d", 0)
    if (
        isinstance(complaint_count, bool)
        or not isinstance(complaint_count, int)
        or complaint_count < 0
    ):
        errors.fail(
            "ERR_INVALID_REQUEST",
            "complaint_count_90d must be a non-negative integer",
        )
    with store.db.lock:
        company = store.stamp_new(
            {
                "legal_name": legal_name,
                "complaint_count_90d": complaint_count,
                "risk_tier": rules.risk_tier(complaint_count),
            }
        )
        store.db.subject_companies[company["id"]] = company
    return envelope.success(store.public(company), 201)


@bp.route("/enforcement/subject-companies/<companyId>", methods=["GET"])
def get_company(companyId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    company = requtil.get_or_404(
        store.db.subject_companies,
        companyId,
        "ERR_SUBJECT_COMPANY_NOT_FOUND",
        "SubjectCompany",
    )
    return envelope.success(store.public(company), 200)
