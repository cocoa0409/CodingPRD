"""The rejection-precedence ladder of PRD Section 2.5, rung by rung.

Each helper implements exactly one rung. Route handlers call them in strictly
ascending rung order, so when several rules are violated at once the lowest rung
number wins. The rung number for each helper is stated in its name/docstring.
"""

import calc
from common import ApiError
from derive import (
    dam_hazard_class, engineer_license_status, owner_is_delinquent,
)
from store import db

# ---------------------------------------------------------------------------
# Rung 1 + 2: identity headers, then role authorisation (before body parsing)
# ---------------------------------------------------------------------------

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate(request, allowed_roles):
    """Rung 1 (ERR_UNAUTHENTICATED) then rung 2 (ERR_FORBIDDEN_ROLE)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "both %s and %s are required" % (HEADER_USER_ID, HEADER_USER_ROLE))
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role '%s' may not perform this operation" % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Rungs 4 + 5: path existence, then body-reference existence
# ---------------------------------------------------------------------------

def get_owner(owner_id):
    row = db.owners.get(owner_id)
    if row is None:
        raise ApiError("ERR_OWNER_NOT_FOUND", "owner '%s' does not exist" % owner_id)
    return row


def get_engineer(engineer_id):
    row = db.engineers.get(engineer_id)
    if row is None:
        raise ApiError("ERR_ENGINEER_NOT_FOUND", "engineer '%s' does not exist" % engineer_id)
    return row


def get_reach(reach_id):
    row = db.reaches.get(reach_id)
    if row is None:
        raise ApiError("ERR_REACH_NOT_FOUND", "river reach '%s' does not exist" % reach_id)
    return row


def get_dam(dam_id):
    row = db.dams.get(dam_id)
    if row is None:
        raise ApiError("ERR_DAM_NOT_FOUND", "dam '%s' does not exist" % dam_id)
    return row


def get_assessment(assessment_id):
    row = db.assessments.get(assessment_id)
    if row is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND", "consequence assessment '%s' does not exist" % assessment_id)
    return row


def get_inspection(inspection_id):
    row = db.inspections.get(inspection_id)
    if row is None:
        raise ApiError("ERR_INSPECTION_NOT_FOUND", "inspection '%s' does not exist" % inspection_id)
    return row


def get_deficiency(deficiency_id):
    row = db.deficiencies.get(deficiency_id)
    if row is None:
        raise ApiError("ERR_DEFICIENCY_NOT_FOUND", "deficiency '%s' does not exist" % deficiency_id)
    return row


def get_order(order_id):
    row = db.orders.get(order_id)
    if row is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "remediation order '%s' does not exist" % order_id)
    return row


def get_plan(plan_id):
    row = db.plans.get(plan_id)
    if row is None:
        raise ApiError("ERR_EAP_NOT_FOUND", "emergency action plan '%s' does not exist" % plan_id)
    return row


def get_permit(permit_id):
    row = db.permits.get(permit_id)
    if row is None:
        raise ApiError("ERR_PERMIT_NOT_FOUND", "permit '%s' does not exist" % permit_id)
    return row


def get_event(event_id):
    row = db.events.get(event_id)
    if row is None:
        raise ApiError("ERR_EVENT_NOT_FOUND", "high-water event '%s' does not exist" % event_id)
    return row


def get_drawdown(drawdown_id):
    row = db.drawdowns.get(drawdown_id)
    if row is None:
        raise ApiError("ERR_DRAWDOWN_NOT_FOUND", "drawdown order '%s' does not exist" % drawdown_id)
    return row


# ---------------------------------------------------------------------------
# Rung 6: backing-entity identity for Engineer / DamOwner
# ---------------------------------------------------------------------------

def check_identity(user_id, role):
    """Rung 6 (ERR_IDENTITY_UNKNOWN). ProgramAdmin and EmergencyCoordinator
    identities are opaque and are never resolved against a stored row."""
    if role == "Engineer":
        if user_id not in db.engineers:
            raise ApiError("ERR_IDENTITY_UNKNOWN", "X-User-ID does not name a registered engineer")
        return db.engineers[user_id]
    if role == "DamOwner":
        if user_id not in db.owners:
            raise ApiError("ERR_IDENTITY_UNKNOWN", "X-User-ID does not name a registered owner")
        return db.owners[user_id]
    return None


# ---------------------------------------------------------------------------
# Rung 7: owner ownership
# ---------------------------------------------------------------------------

def check_resource_owner(user_id, role, owner_id):
    """Rung 7 (ERR_NOT_RESOURCE_OWNER)."""
    if role == "DamOwner" and user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "acting owner does not own this resource")


# ---------------------------------------------------------------------------
# Rung 8: engineer assignment
# ---------------------------------------------------------------------------

def check_assigned_engineer(user_id, assigned_engineer_id):
    """Rung 8 (ERR_NOT_ASSIGNED_ENGINEER)."""
    if user_id != assigned_engineer_id:
        raise ApiError("ERR_NOT_ASSIGNED_ENGINEER", "acting engineer is not the engineer of record")


# ---------------------------------------------------------------------------
# Rungs 9-16: state guards, one per entity family
# ---------------------------------------------------------------------------

def check_state(row, allowed, error_id, label):
    if row["status"] not in allowed:
        raise ApiError(error_id, "%s is %s; expected one of %s" % (label, row["status"], list(allowed)))


def check_assessment_state(row, allowed):
    check_state(row, allowed, "ERR_ASSESSMENT_INVALID_STATE", "consequence assessment")


def check_inspection_state(row, allowed):
    check_state(row, allowed, "ERR_INSPECTION_INVALID_STATE", "inspection")


def check_deficiency_state(row, allowed):
    check_state(row, allowed, "ERR_DEFICIENCY_INVALID_STATE", "deficiency")


def check_order_state(row, allowed):
    check_state(row, allowed, "ERR_ORDER_INVALID_STATE", "remediation order")


def check_plan_state(row, allowed):
    check_state(row, allowed, "ERR_EAP_INVALID_STATE", "emergency action plan")


def check_permit_state(row, allowed):
    check_state(row, allowed, "ERR_PERMIT_INVALID_STATE", "permit")


def check_event_state(row, allowed):
    check_state(row, allowed, "ERR_EVENT_INVALID_STATE", "high-water event")


def check_drawdown_state(row, allowed):
    check_state(row, allowed, "ERR_DRAWDOWN_INVALID_STATE", "drawdown order")


# ---------------------------------------------------------------------------
# Rung 17: dam operability
# ---------------------------------------------------------------------------

def check_dam_operable(dam, block_removal_permitted=False):
    """Rung 17 (ERR_DAM_NOT_OPERABLE). A BREACHED dam is out of the programme
    entirely; a REMOVAL_PERMITTED dam still accepts inspections and high-water
    events but no new consequence assessments and no new permits."""
    if dam["regulatory_status"] == "BREACHED":
        raise ApiError("ERR_DAM_NOT_OPERABLE", "dam is BREACHED")
    if block_removal_permitted and dam["regulatory_status"] == "REMOVAL_PERMITTED":
        raise ApiError("ERR_DAM_NOT_OPERABLE", "dam is REMOVAL_PERMITTED")


# ---------------------------------------------------------------------------
# Rungs 18 + 19: optimistic concurrency on the parent's version
# ---------------------------------------------------------------------------

def check_dam_version(dam, expected):
    """Rung 18 (ERR_STALE_DAM_VERSION). Omitted expectation skips the check."""
    if expected is None:
        return
    if int(expected) != dam["version"]:
        raise ApiError("ERR_STALE_DAM_VERSION",
                       "expected dam version %s but stored version is %s" % (expected, dam["version"]))


def check_reach_version(reach, expected):
    """Rung 19 (ERR_STALE_REACH_VERSION). Omitted expectation skips the check."""
    if expected is None:
        return
    if int(expected) != reach["version"]:
        raise ApiError("ERR_STALE_REACH_VERSION",
                       "expected reach version %s but stored version is %s" % (expected, reach["version"]))


# ---------------------------------------------------------------------------
# Rungs 20 + 21: engineer licence currency and hazard-class certification
# ---------------------------------------------------------------------------

def check_license_active(engineer):
    """Rung 20 (ERR_ENGINEER_LICENSE_EXPIRED)."""
    if engineer_license_status(engineer) != "ACTIVE":
        raise ApiError("ERR_ENGINEER_LICENSE_EXPIRED", "engineer licence has expired")


def check_certified_for(engineer, hazard_class):
    """Rung 21 (ERR_ENGINEER_NOT_CERTIFIED). UNCLASSIFIED reads as LOW."""
    effective = "LOW" if hazard_class == "UNCLASSIFIED" else hazard_class
    if effective not in engineer["certified_hazard_classes"]:
        raise ApiError("ERR_ENGINEER_NOT_CERTIFIED",
                       "engineer is not certified for hazard class %s" % effective)


# ---------------------------------------------------------------------------
# Rung 25: dam classified
# ---------------------------------------------------------------------------

def check_dam_classified(dam):
    """Rung 25 (ERR_DAM_UNCLASSIFIED)."""
    if dam_hazard_class(dam) == "UNCLASSIFIED":
        raise ApiError("ERR_DAM_UNCLASSIFIED", "dam has no certified consequence assessment")


# ---------------------------------------------------------------------------
# Rungs 35 + 36: fiscal gates
# ---------------------------------------------------------------------------

def check_owner_not_delinquent(owner_id):
    """Rung 35 (ERR_OWNER_DELINQUENT)."""
    if owner_is_delinquent(owner_id):
        raise ApiError("ERR_OWNER_DELINQUENT", "owner fee balance is delinquent")


def check_financial_assurance(owner, hazard_class):
    """Rung 36 (ERR_INSUFFICIENT_FINANCIAL_ASSURANCE)."""
    floor = calc.FINANCIAL_ASSURANCE_FLOOR_CENTS[hazard_class]
    if floor and owner["financial_assurance_bond_cents"] < floor:
        raise ApiError("ERR_INSUFFICIENT_FINANCIAL_ASSURANCE",
                       "financial assurance bond is below the %s-hazard floor" % hazard_class)
