"""Medical clearances: filing, officer determination, resubmission.

max_tier_gap is measured against the ACCEPTED invitation's
pinned_country_medical_tier — never the live program tier (PRD 2.6, 3.5).
"""
from flask import Blueprint, request

from authz import auth, require_owner, require_roles
from cascade import accepted_invitation_of, denial_cascade
from db import MAX_MEDICAL_DEFERRALS, ROLES, STORE, new_record, touch
from errors import err, ok_object, paginate
from routes_applications import get_application_or_404
from validate import as_enum, as_int, as_list, as_str, body

bp = Blueprint("medical", __name__)

DETERMINATIONS = ("CLEARED", "CLEARED_WITH_ACCOMMODATION", "DENIED", "DEFERRED")
DENTAL_STATUSES = ("CLEAR", "NEEDS_TREATMENT")


def get_clearance_or_404(mid):
    mc = STORE["medical_clearances"].get(mid)
    if mc is None:
        err("ERR_MEDICAL_CLEARANCE_NOT_FOUND", 404, "Medical clearance not found")
    return mc


def validate_conditions(data):
    """conditions: array of {condition_code: str, severity: int 1..3,
    required_support_tier: int 1..3}; empty array means no conditions."""
    conditions = as_list(data, "conditions")
    for cond in conditions:
        if not isinstance(cond, dict):
            err("ERR_VALIDATION", 400, "Each condition must be an object")
        as_str(cond, "condition_code")
        as_int(cond, "severity", minimum=1, maximum=3)
        as_int(cond, "required_support_tier", minimum=1, maximum=3)
    return conditions


def compute_max_tier_gap(conditions, pinned_tier):
    """Largest amount any condition's required tier exceeds the pinned tier,
    or 0 when no conditions are declared or none exceeds the pinned tier."""
    gap = 0
    for cond in conditions:
        gap = max(gap, cond["required_support_tier"] - pinned_tier)
    return gap


@bp.post("/volunteer-portal/medical-clearances")
def create_clearance():
    user_id, role = auth()
    require_roles(role, ("Applicant",))
    data = body()
    application = None
    if data.get("application_id") is not None:
        application = STORE["applications"].get(data["application_id"])
        if application is None:
            err("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    if application is not None:
        # Ownership (priority 3)
        require_owner(user_id, application["applicant_id"])
        # State guard (priority 6)
        if application["status"] != "ACCEPTED":
            err("ERR_INVALID_APPLICATION_STATE", 409,
                "medical clearance creation requires ACCEPTED, found %s"
                % application["status"])
        # Business constraint (priority 8): no second active clearance
        for mc in STORE["medical_clearances"].values():
            if (mc["application_id"] == application["id"]
                    and mc["status"] in ("SUBMITTED", "DEFERRED")):
                err("ERR_DUPLICATE_ACTIVE_CLEARANCE", 409,
                    "An active medical clearance already exists for this application")
    # Field shape (priority 10)
    application_id = as_str(data, "application_id")
    conditions = validate_conditions(data)
    dental_status = as_enum(data, "dental_status", DENTAL_STATUSES)
    if application is None:
        application = STORE["applications"][application_id]
    invitation = accepted_invitation_of(application_id)
    pinned_tier = (invitation["pinned_country_medical_tier"]
                   if invitation is not None else 0)
    rec = new_record()
    rec.update({
        "application_id": application_id,
        "conditions": conditions,
        "dental_status": dental_status,
        "deferral_count": 0,
        "max_tier_gap": compute_max_tier_gap(conditions, pinned_tier),
        "reviewed_by": None,
        "status": "SUBMITTED",
    })
    STORE["medical_clearances"][rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/applications/<aid>/medical-clearances")
def list_clearances(aid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    get_application_or_404(aid)
    records = sorted(
        (mc for mc in STORE["medical_clearances"].values()
         if mc["application_id"] == aid),
        key=lambda r: r["created_at"])
    return paginate(records)


@bp.post("/volunteer-portal/medical-clearances/<mid>/determine")
def determine_clearance(mid):
    user_id, role = auth()
    require_roles(role, ("MedicalOfficer",))
    mc = get_clearance_or_404(mid)
    # State guard (priority 6)
    if mc["status"] != "SUBMITTED":
        err("ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE", 409,
            "determine requires SUBMITTED, found %s" % mc["status"])
    data = body()
    determination = data.get("determination")
    gap = mc["max_tier_gap"]
    # Compliance gates (priority 7): gap admissibility, then grant flag,
    # then dental — evaluated only for valid determination enum members.
    if determination in DETERMINATIONS:
        admissible = True
        if determination == "CLEARED":
            admissible = gap <= 0
        elif determination == "CLEARED_WITH_ACCOMMODATION":
            admissible = gap == 1
        if not admissible:
            err("ERR_ACCOMMODATION_DETERMINATION_INVALID", 422,
                "Determination %s is inadmissible for max_tier_gap %d"
                % (determination, gap))
        if (determination == "CLEARED_WITH_ACCOMMODATION"
                and data.get("accommodation_granted") is not True):
            err("ERR_ACCOMMODATION_DETERMINATION_INVALID", 422,
                "CLEARED_WITH_ACCOMMODATION requires accommodation_granted=true")
        if (determination in ("CLEARED", "CLEARED_WITH_ACCOMMODATION")
                and mc["dental_status"] == "NEEDS_TREATMENT"):
            err("ERR_DENTAL_TREATMENT_PENDING", 422,
                "Dental treatment must complete before a cleared determination")
    # Business constraint (priority 8): deferral ration
    if determination == "DEFERRED" and mc["deferral_count"] >= MAX_MEDICAL_DEFERRALS:
        err("ERR_MAX_DEFERRALS_REACHED", 422,
            "deferral_count has reached the maximum of %d" % MAX_MEDICAL_DEFERRALS)
    # Field shape (priority 10)
    determination = as_enum(data, "determination", DETERMINATIONS)
    if "accommodation_granted" in data and data["accommodation_granted"] is not None:
        if not isinstance(data["accommodation_granted"], bool):
            err("ERR_VALIDATION", 400, "accommodation_granted must be a boolean")
    mc["status"] = determination
    mc["reviewed_by"] = user_id
    touch(mc)
    if determination == "DENIED":
        denial_cascade(mc["application_id"])
    return ok_object(mc)


@bp.post("/volunteer-portal/medical-clearances/<mid>/resubmit")
def resubmit_clearance(mid):
    user_id, role = auth()
    require_roles(role, ("Applicant",))
    mc = get_clearance_or_404(mid)
    app = STORE["applications"].get(mc["application_id"])
    if app is not None:
        require_owner(user_id, app["applicant_id"])
    # State guards (priority 6): clearance DEFERRED, application ACCEPTED.
    if mc["status"] != "DEFERRED":
        err("ERR_INVALID_STATE", 409,
            "resubmit requires DEFERRED, found %s" % mc["status"])
    if app is not None and app["status"] != "ACCEPTED":
        err("ERR_INVALID_APPLICATION_STATE", 409,
            "resubmit requires the application to remain ACCEPTED, found %s"
            % app["status"])
    data = body()
    conditions = validate_conditions(data)
    dental_status = as_enum(data, "dental_status", DENTAL_STATUSES)
    invitation = accepted_invitation_of(mc["application_id"])
    pinned_tier = (invitation["pinned_country_medical_tier"]
                   if invitation is not None else 0)
    mc["conditions"] = conditions
    mc["dental_status"] = dental_status
    mc["deferral_count"] += 1
    mc["max_tier_gap"] = compute_max_tier_gap(conditions, pinned_tier)
    mc["status"] = "SUBMITTED"
    touch(mc)
    return ok_object(mc)
