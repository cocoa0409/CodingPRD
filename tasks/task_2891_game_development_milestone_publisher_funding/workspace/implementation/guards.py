"""Authentication, authorization and lookup guards -- precedence rules 1-20.

The whole of PRD 2.10 rules 1..6 is implemented by begin(); rules 7..18 by the
find_* helpers a route calls after begin(); rule 19 by the resolve_* helpers used
on creation payloads; rule 20 by require_party().
"""

from flask import request

from errors import ApiError
from store import db
from validation import parse_json_body

# PRD 2.1: "Every request to the API must carry two headers: X-User-ID ... and
# X-User-Role".
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# PRD 2.1: "The system recognizes exactly four roles, and the comparison against
# X-User-Role is case-sensitive".
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_DEVELOPER = "Developer"
ROLE_PUBLISHER_REVIEWER = "PublisherReviewer"
ROLE_PUBLISHER_FINANCE = "PublisherFinance"

KNOWN_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_DEVELOPER,
    ROLE_PUBLISHER_REVIEWER,
    ROLE_PUBLISHER_FINANCE,
)

ALL_ROLES = list(KNOWN_ROLES)

# PRD 2.1: acting as PublisherReviewer requires function REVIEW or DUAL; acting
# as PublisherFinance requires FINANCE or DUAL.
FUNCTIONS_FOR_ROLE = {
    ROLE_PUBLISHER_REVIEWER: ("REVIEW", "DUAL"),
    ROLE_PUBLISHER_FINANCE: ("FINANCE", "DUAL"),
}

PUBLISHER_SIDE_ROLES = (ROLE_PUBLISHER_REVIEWER, ROLE_PUBLISHER_FINANCE)


class Actor:
    def __init__(self, role, user_id, studio=None, publisher_user=None):
        self.role = role
        self.user_id = user_id
        self.studio = studio
        self.publisher_user = publisher_user

    @property
    def publisher_id(self):
        if self.publisher_user is None:
            return None
        return self.publisher_user["publisher_id"]


def begin(roles, exempt_actor=False):
    """Run precedence rules 1 through 5 and return the acting principal."""
    raw_id = request.headers.get(HEADER_USER_ID)
    raw_role = request.headers.get(HEADER_USER_ROLE)

    # Rule 1 -- "If either header is absent, empty, or contains only whitespace".
    if raw_id is None or raw_id.strip() == "" or raw_role is None or raw_role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")

    user_id = raw_id.strip()
    role = raw_role

    # Rule 2 -- case-sensitive membership of the four known roles.
    if role not in KNOWN_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")

    studio = None
    publisher_user = None

    # Rule 3 -- actor resolution, skipped on the four bootstrap operations.
    if not exempt_actor:
        if role == ROLE_DEVELOPER:
            studio = db.studios.get(user_id)
            if studio is None:
                raise ApiError("ERR_ACTOR_NOT_FOUND")
        elif role in PUBLISHER_SIDE_ROLES:
            publisher_user = db.publisher_users.get(user_id)
            if publisher_user is None:
                raise ApiError("ERR_ACTOR_NOT_FOUND")
        # PlatformAdmin: "an opaque operator identifier ... always resolves".
    elif role in PUBLISHER_SIDE_ROLES:
        # Even on an exempt endpoint the licence gate of rule 5 needs the row if
        # one happens to exist; a missing row simply leaves it unresolved.
        publisher_user = db.publisher_users.get(user_id)

    # Rule 4 -- endpoint authorization.
    if role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    # Rule 5 -- publisher-side licence gate, on every endpoint whose authorized
    # roles include either publisher-side role.
    if role in PUBLISHER_SIDE_ROLES and any(r in roles for r in PUBLISHER_SIDE_ROLES):
        allowed = FUNCTIONS_FOR_ROLE[role]
        function = publisher_user.get("function") if publisher_user else None
        if function not in allowed:
            raise ApiError("ERR_ROLE_FUNCTION_MISMATCH")

    return Actor(role, user_id, studio, publisher_user)


def body(fields=()):
    """Rule 6 -- structural validation of the request body."""
    from validation import validate

    raw = parse_json_body(request.get_data(cache=False, as_text=True))
    return raw, validate(raw, fields)


def _find(table, key, error_id):
    row = table.get(key) if isinstance(key, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


# --- rules 7..18: identifiers arriving in the path -------------------------

def find_studio(key):
    return _find(db.studios, key, "ERR_STUDIO_NOT_FOUND")


def find_publisher(key):
    return _find(db.publishers, key, "ERR_PUBLISHER_NOT_FOUND")


def find_publisher_user(key):
    return _find(db.publisher_users, key, "ERR_PUBLISHER_USER_NOT_FOUND")


def find_agreement(key):
    return _find(db.agreements, key, "ERR_AGREEMENT_NOT_FOUND")


def find_milestone(key):
    return _find(db.milestones, key, "ERR_MILESTONE_NOT_FOUND")


def find_build(key):
    return _find(db.builds, key, "ERR_BUILD_NOT_FOUND")


def find_review(key):
    return _find(db.reviews, key, "ERR_REVIEW_NOT_FOUND")


def find_payment(key):
    return _find(db.payments, key, "ERR_PAYMENT_NOT_FOUND")


def find_change_order(key):
    return _find(db.change_orders, key, "ERR_CHANGE_ORDER_NOT_FOUND")


def find_engagement(key):
    return _find(db.engagements, key, "ERR_ENGAGEMENT_NOT_FOUND")


def find_invoice(key):
    return _find(db.invoices, key, "ERR_INVOICE_NOT_FOUND")


def find_statement(key):
    return _find(db.statements, key, "ERR_STATEMENT_NOT_FOUND")


# --- transitive walk to the agreement a request reaches (PRD 2.1) ---------

def agreement_of_milestone(milestone):
    return db.agreements.get(milestone["agreement_id"])


def agreement_of_build(build):
    milestone = db.milestones.get(build["milestone_id"])
    return agreement_of_milestone(milestone) if milestone else None


def agreement_of_review(review):
    build = db.builds.get(review["build_id"])
    return agreement_of_build(build) if build else None


def agreement_of_payment(payment):
    milestone = db.milestones.get(payment["milestone_id"])
    return agreement_of_milestone(milestone) if milestone else None


def agreement_of_engagement(engagement):
    milestone = db.milestones.get(engagement["milestone_id"])
    return agreement_of_milestone(milestone) if milestone else None


def agreement_of_invoice(invoice):
    engagement = db.engagements.get(invoice["engagement_id"])
    return agreement_of_engagement(engagement) if engagement else None


def agreement_of_statement(statement):
    return db.agreements.get(statement["agreement_id"])


def agreement_of_change_order(order):
    return db.agreements.get(order["agreement_id"])


# --- rule 20: the acting principal is a party to that agreement -----------

def is_party(actor, agreement):
    if agreement is None:
        return True
    if actor.role == ROLE_PLATFORM_ADMIN:
        return True
    if actor.role == ROLE_DEVELOPER:
        return agreement["studio_id"] == actor.user_id
    return agreement["publisher_id"] == actor.publisher_id


def require_party(actor, agreement):
    if not is_party(actor, agreement):
        raise ApiError("ERR_NOT_AGREEMENT_PARTY")
    return agreement


def visible(actor, rows, resolver):
    """PRD 2.3: a list returns "everything the caller is entitled to see"."""
    if actor.role == ROLE_PLATFORM_ADMIN:
        return list(rows)
    return [row for row in rows if is_party(actor, resolver(row))]
