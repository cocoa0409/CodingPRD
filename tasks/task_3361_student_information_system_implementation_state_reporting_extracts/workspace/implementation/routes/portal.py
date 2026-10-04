"""PortalAccount endpoints: provision, list, get (DistrictAdmin or the owning
PortalUser), activate, revoke, update-access."""
from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.serializers import portal_out
from validators import body, opt_enum, req_enum, req_str

bp = Blueprint("portal_accounts", __name__)

ACCOUNT_TYPES = {"PARENT", "STUDENT"}
ACCESS_LEVELS = {"FULL", "GRADES_ONLY", "ATTENDANCE_ONLY"}
GRADE_VISIBILITIES = {"ALL_GRADES", "CURRENT_TERM_ONLY", "HIDDEN"}


def _get_account_or_404(pid):
    p = store["portal_accounts"].get(pid)
    if not p:
        raise ApiError("ERR_PORTAL_ACCOUNT_NOT_FOUND", 404,
                       "No portal account with the given id")
    return p


@bp.post("/sis/portal-accounts")
def create_account():
    _uid, role = auth_context()
    data = body()
    student_id = req_str(data, "student_id")
    account_type = req_enum(data, "account_type", ACCOUNT_TYPES)
    access_level = req_enum(data, "access_level", ACCESS_LEVELS)
    grade_visibility = opt_enum(data, "grade_visibility", GRADE_VISIBILITIES,
                                "CURRENT_TERM_ONLY")
    require_role(role, {"DistrictAdmin"})
    student = store["students"].get(student_id)
    if not student:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "student_id does not reference an existing student")
    p = {"id": new_id(), "student_id": student_id,
         "account_type": account_type, "access_level": access_level,
         "grade_visibility": grade_visibility, "status": "INVITED"}
    stamp_new(p)
    store["portal_accounts"][p["id"]] = p
    return ok_obj(portal_out(p), 201)


@bp.get("/sis/portal-accounts")
def list_accounts():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    items = [p for p in store["portal_accounts"].values()
             if (student_id is None or p["student_id"] == student_id)
             and (status is None or p["status"] == status)]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([portal_out(p) for p in page], total, limit, offset)


@bp.get("/sis/portal-accounts/<pid>")
def get_account(pid):
    uid, role = auth_context()
    # A PortalUser may read only the account whose id equals their X-User-ID;
    # the ownership check is an authorization failure (403), decided before
    # path existence.
    if role == "PortalUser":
        if uid != pid:
            raise ApiError("ERR_FORBIDDEN", 403,
                           "PortalUser may only read the portal account whose id equals X-User-ID")
    elif role != "DistrictAdmin":
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role not permitted for this endpoint")
    return ok_obj(portal_out(_get_account_or_404(pid)))


@bp.post("/sis/portal-accounts/<pid>/activate")
def activate_account(pid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    p = _get_account_or_404(pid)
    if p["status"] != "INVITED":
        raise ApiError("ERR_PORTAL_ACCOUNT_NOT_INVITED", 409,
                       "Activate requires account INVITED")
    p["status"] = "ACTIVE"
    touch(p)
    return ok_obj(portal_out(p))


@bp.post("/sis/portal-accounts/<pid>/revoke")
def revoke_account(pid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    p = _get_account_or_404(pid)
    if p["status"] not in ("INVITED", "ACTIVE"):
        raise ApiError("ERR_PORTAL_ACCOUNT_REVOKED", 409,
                       "Account already REVOKED; no further transitions")
    p["status"] = "REVOKED"
    touch(p)
    return ok_obj(portal_out(p))


@bp.post("/sis/portal-accounts/<pid>/update-access")
def update_access(pid):
    _uid, role = auth_context()
    data = body()
    access_level = opt_enum(data, "access_level", ACCESS_LEVELS, None)
    grade_visibility = opt_enum(data, "grade_visibility", GRADE_VISIBILITIES,
                                None)
    require_role(role, {"DistrictAdmin"})
    p = _get_account_or_404(pid)
    if p["status"] == "REVOKED":
        raise ApiError("ERR_PORTAL_ACCOUNT_REVOKED", 409,
                       "Account already REVOKED; no further transitions or updates")
    if access_level is not None:
        p["access_level"] = access_level
    if grade_visibility is not None:
        p["grade_visibility"] = grade_visibility
    touch(p)
    return ok_obj(portal_out(p))
