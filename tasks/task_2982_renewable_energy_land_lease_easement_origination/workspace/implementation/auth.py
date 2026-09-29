"""Identity and role-based access control (PRD section 2.1).

Every request, reads included, must carry X-User-ID and X-User-Role.
"""

import functools

from flask import g, request

from errors import ERR_MISSING_USER_ID, ERR_UNAUTHORIZED, fail

LAND_AGENT = "LandAgent"
TITLE_COUNSEL = "TitleCounsel"
PORTFOLIO_MANAGER = "PortfolioManager"
PAYMENT_ADMINISTRATOR = "PaymentAdministrator"
LANDOWNER = "Landowner"

ALL_ROLES = (
    LAND_AGENT,
    TITLE_COUNSEL,
    PORTFOLIO_MANAGER,
    PAYMENT_ADMINISTRATOR,
    LANDOWNER,
)

OPERATOR_ROLES = (
    LAND_AGENT,
    TITLE_COUNSEL,
    PORTFOLIO_MANAGER,
    PAYMENT_ADMINISTRATOR,
)


def _identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail(ERR_MISSING_USER_ID)
    if user_id.strip() == "" or role.strip() == "":
        fail(ERR_MISSING_USER_ID)
    return user_id, role


def require(*roles):
    """Rung 1 then rung 2 of the ladder, before any resource is looked up."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = _identity()
            if role not in ALL_ROLES or role not in roles:
                fail(ERR_UNAUTHORIZED)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return g.get("user_id")


def acting_role():
    return g.get("role")


def is_landowner_actor():
    return g.get("role") == LANDOWNER


def scope_landowner(landowner_id):
    """A Landowner may only reach rows that reference their own id."""
    if is_landowner_actor() and landowner_id != acting_user_id():
        fail(ERR_UNAUTHORIZED)
