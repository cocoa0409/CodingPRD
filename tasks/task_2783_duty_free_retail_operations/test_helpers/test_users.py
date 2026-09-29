"""Role headers for the five roles of PRD 2.1.

Four roles are opaque operator identities; ``Passenger`` is entity-backed, so its
``X-User-ID`` is the id of the acting ``PassengerItinerary`` and headers must be
built per itinerary with :func:`make_passenger_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_TERMINAL_ADMIN = "TerminalAdmin"
ROLE_SALES_ASSOCIATE = "SalesAssociate"
ROLE_STOCK_CONTROLLER = "StockController"
ROLE_CUSTOMS_AUDITOR = "CustomsAuditor"
ROLE_PASSENGER = "Passenger"

ALL_ROLES = (
    ROLE_TERMINAL_ADMIN,
    ROLE_SALES_ASSOCIATE,
    ROLE_STOCK_CONTROLLER,
    ROLE_CUSTOMS_AUDITOR,
    ROLE_PASSENGER,
)

# Operator identifiers. The audit workflow compares these against each other, so
# the preparer and the adjudicator are deliberately distinct users.
USER_ADMIN = "user-admin-01"
USER_SALES = "user-sales-01"
USER_STOCK = "user-stock-01"
USER_STOCK_ALT = "user-stock-02"
USER_AUDITOR = "user-audit-01"
USER_AUDITOR_ALT = "user-audit-02"

TERMINAL_ADMIN_HEADERS = build_user_headers(USER_ADMIN, ROLE_TERMINAL_ADMIN)
SALES_ASSOCIATE_HEADERS = build_user_headers(USER_SALES, ROLE_SALES_ASSOCIATE)
STOCK_CONTROLLER_HEADERS = build_user_headers(USER_STOCK, ROLE_STOCK_CONTROLLER)
CUSTOMS_AUDITOR_HEADERS = build_user_headers(USER_AUDITOR, ROLE_CUSTOMS_AUDITOR)

# A request with neither header, used to exercise ERR_UNAUTHENTICATED.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
# A syntactically complete request naming a role outside the recognised set.
UNKNOWN_ROLE_HEADERS = build_user_headers(USER_ADMIN, "TerminalSuperuser")


def make_passenger_headers(itinerary_id: str) -> Dict[str, str]:
    """Headers for the Passenger whose own itinerary is ``itinerary_id``."""
    return build_user_headers(itinerary_id, ROLE_PASSENGER)


def stock_controller_headers(user_id: str) -> Dict[str, str]:
    """StockController headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_STOCK_CONTROLLER)


def customs_auditor_headers(user_id: str) -> Dict[str, str]:
    """CustomsAuditor headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_CUSTOMS_AUDITOR)


def terminal_admin_headers(user_id: str) -> Dict[str, str]:
    """TerminalAdmin headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_TERMINAL_ADMIN)


def sales_associate_headers(user_id: str) -> Dict[str, str]:
    """SalesAssociate headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_SALES_ASSOCIATE)
