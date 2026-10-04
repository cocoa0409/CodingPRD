"""RoyaltyAccrual read endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_accrual
from response import ok_list, ok_object

bp = Blueprint("accruals", __name__)

READ = ("MLCAdministrator", "ServiceProviderUser", "MemberUser", "PublicSearcher")


def accrual_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


@bp.route("/mlc/accruals", methods=["GET"])
@require_roles(*READ)
def list_accruals(_user_id, _role):
    items = sorted(db.accruals.values(), key=lambda a: a["created_at"])
    for field in ("status", "service_provider_id", "usage_line_id",
                  "reporting_month", "matched_work_id"):
        v = request.args.get(field)
        if v:
            items = [a for a in items if a.get(field) == v]
    return ok_list([accrual_view(a) for a in items])


@bp.route("/mlc/accruals/<accrual_id>", methods=["GET"])
@require_roles(*READ)
def get_one_accrual(accrual_id, _user_id, _role):
    return ok_object(accrual_view(get_accrual(accrual_id)))


@bp.route("/mlc/accruals/<accrual_id>/claims", methods=["GET"])
@require_roles("MLCAdministrator", "MemberUser", "PublicSearcher")
def list_accrual_claims(accrual_id, _user_id, _role):
    get_accrual(accrual_id)
    items = sorted(
        (c for c in db.claims.values() if c["accrual_id"] == accrual_id),
        key=lambda c: c["created_at"])
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    from routes.claims import claim_view
    return ok_list([claim_view(c) for c in items])
