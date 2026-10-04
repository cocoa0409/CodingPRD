"""Authentication and role authorization.

PRD.md 2.1 fixes the header scheme verbatim:
  * `X-User-ID` identifies the acting user or organization.
  * `X-User-Role` names the capacity in which that identity is acting.
  * A missing header, a malformed value, or a role outside the six declared
    spellings is rejected with ERR_UNAUTHENTICATED at 401, before any business
    rule is consulted.
  * Six roles are recognized, spelled exactly:
    EditorialStaff, EditorialPanelChair, CommitteeReviewer, LicensingOfficer,
    Licensee, ChangeApplicant.

Identity semantics (PRD.md 2.1 / SCAFFOLD.yaml `roles[].identity`):
  EditorialStaff, EditorialPanelChair, LicensingOfficer -> opaque operator id
  CommitteeReviewer -> id of the acting AdvisoryCommitteeReview
  Licensee          -> id of the acting LicensingAgreement
  ChangeApplicant   -> id of the acting ChangeApplicant
"""

from errors import (
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ApiError,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

EDITORIAL_STAFF = "EditorialStaff"
EDITORIAL_PANEL_CHAIR = "EditorialPanelChair"
COMMITTEE_REVIEWER = "CommitteeReviewer"
LICENSING_OFFICER = "LicensingOfficer"
LICENSEE = "Licensee"
CHANGE_APPLICANT = "ChangeApplicant"

ROLES = (
    EDITORIAL_STAFF,
    EDITORIAL_PANEL_CHAIR,
    COMMITTEE_REVIEWER,
    LICENSING_OFFICER,
    LICENSEE,
    CHANGE_APPLICANT,
)

# Roles whose X-User-ID is an opaque operator identity, not a persisted row.
OPAQUE_ROLES = (EDITORIAL_STAFF, EDITORIAL_PANEL_CHAIR, LICENSING_OFFICER)

# Roles backed by a persisted entity, and the table that backs them.
ENTITY_BACKED_ROLES = {
    COMMITTEE_REVIEWER: "committee_reviews",
    LICENSEE: "licenses",
    CHANGE_APPLICANT: "applicants",
}


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):
        return "Actor(%r, %r)" % (self.user_id, self.role)


def authenticate(headers):
    """Gate one: presence, well-formedness and declared-role check."""
    user_id = headers.get(USER_ID_HEADER)
    role = headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role are required")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role must be non-empty")
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "undeclared role: %s" % role)
    return Actor(user_id, role)


def authorize(actor, allowed_roles):
    """Gate two: role authorization (PRD.md 2.1, ERR_UNAUTHORIZED at 403)."""
    if actor.role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED, "role %s is not permitted here" % actor.role)


def require_actor_for(actor, table, row_id, field="id"):
    """Ownership comparison for entity-backed roles.

    The opaque operator roles are never matched against a persisted row; the
    entity-backed roles compare the header value against the resource's own id
    (for the acting entity) or against a foreign key (for owned resources).
    """
    record = table.get(row_id)
    if record is None:
        return False
    return record.get(field) == actor.user_id