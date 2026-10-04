"""Auth + RBAC middleware driven by the route table."""
import re
from flask import request

from errors import ApiError, ERR_MISSING_AUTH_HEADERS, ERR_UNAUTHORIZED

ROLES = {
    "PlatformAdmin", "ContractsManager", "ComplianceOfficer",
    "ResellerOps", "Integrator", "FinanceOps", "Auditor",
}

ALL_GET = sorted(ROLES)

# (method, path-template, allowed roles, body entity-type template or None)
ROUTES = [
    ("POST", "/_clock/set_current_utc", ["PlatformAdmin"], None),

    ("POST", "/manufacturers", ["PlatformAdmin"], None),
    ("GET", "/manufacturers", ALL_GET, None),
    ("GET", "/manufacturers/{id}", ALL_GET, None),
    ("POST", "/manufacturers/{id}/suspend", ["PlatformAdmin"], None),

    ("POST", "/agreements", ["ContractsManager"], "manufacturer"),
    ("GET", "/agreements", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("GET", "/agreements/{id}", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("PATCH", "/agreements/{id}", ["ContractsManager"], None),
    ("POST", "/agreements/{id}/activate", ["ContractsManager"], None),
    ("POST", "/agreements/{id}/suspend", ["ComplianceOfficer"], None),
    ("POST", "/agreements/{id}/reinstate", ["ComplianceOfficer"], None),
    ("POST", "/agreements/{id}/terminate", ["ComplianceOfficer"], None),
    ("GET", "/agreements/{id}/vehicles", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("GET", "/agreements/{id}/teaming", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "ResellerOps", "Integrator"], None),
    ("GET", "/agreements/{id}/sales-reports", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps"], None),
    ("GET", "/agreements/{id}/audits", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor"], None),

    ("POST", "/vehicles", ["ContractsManager"], "agreement"),
    ("GET", "/vehicles", ALL_GET, None),
    ("GET", "/vehicles/{id}", ALL_GET, None),
    ("PATCH", "/vehicles/{id}", ["ContractsManager"], None),
    ("POST", "/vehicles/{id}/authorize", ["ContractsManager"], None),
    ("POST", "/vehicles/{id}/suspend", ["ComplianceOfficer"], None),
    ("POST", "/vehicles/{id}/reinstate", ["ComplianceOfficer"], None),
    ("POST", "/vehicles/{id}/expire", ["ComplianceOfficer"], None),
    ("GET", "/vehicles/{id}/price-lists", ALL_GET, None),
    ("GET", "/vehicles/{id}/orders", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("GET", "/vehicles/{id}/teaming-scopes", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "ResellerOps", "Integrator"], None),

    ("GET", "/price-lists/{id}/orders", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("POST", "/price-lists", ["ContractsManager"], "vehicle"),
    ("GET", "/price-lists", ALL_GET, None),
    ("GET", "/price-lists/{id}", ALL_GET, None),
    ("GET", "/price-lists/{id}/lines", ALL_GET, None),
    ("POST", "/price-lists/{id}/submit", ["ContractsManager"], None),
    ("POST", "/price-lists/{id}/activate", ["ComplianceOfficer"], None),
    ("POST", "/price-lists/{id}/reject", ["ComplianceOfficer"], None),
    ("POST", "/price-lists/{id}/reopen", ["ContractsManager"], None),
    ("GET", "/price-lists/{id}/modifications", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor"], None),

    ("POST", "/price-modifications", ["ContractsManager"], "price_list"),
    ("GET", "/price-modifications/{id}", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor"], None),
    ("POST", "/price-modifications/{id}/approve", ["ComplianceOfficer"], None),
    ("POST", "/price-modifications/{id}/reject", ["ComplianceOfficer"], None),

    ("POST", "/teaming", ["ContractsManager"], "agreement"),
    ("GET", "/teaming", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "ResellerOps", "Integrator"], None),
    ("GET", "/teaming/{id}", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "ResellerOps", "Integrator"], None),
    ("GET", "/teaming/{id}/scopes", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "ResellerOps", "Integrator"], None),
    ("GET", "/teaming/{id}/orders", ALL_GET, None),
    ("POST", "/teaming/{id}/approve", ["ComplianceOfficer"], None),
    ("POST", "/teaming/{id}/suspend", ["ComplianceOfficer"], None),
    ("POST", "/teaming/{id}/reinstate", ["ComplianceOfficer"], None),
    ("POST", "/teaming/{id}/terminate", ["ContractsManager"], None),

    ("POST", "/orders", ["Integrator", "ResellerOps"], "vehicle"),
    ("GET", "/orders", ALL_GET, None),
    ("GET", "/orders/{id}", ALL_GET, None),
    ("POST", "/orders/{id}/submit", ["Integrator", "ResellerOps"], None),
    ("POST", "/orders/{id}/deliver", ["ResellerOps"], None),
    ("POST", "/orders/{id}/cancel", ["Integrator", "ResellerOps"], "order"),
    ("GET", "/orders/{id}/invoices", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("GET", "/orders/{id}/disputes", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps"], None),

    ("POST", "/invoices", ["ResellerOps", "FinanceOps"], "order"),
    ("GET", "/invoices", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("GET", "/invoices/{id}", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps", "ResellerOps"], None),
    ("POST", "/invoices/{id}/pay", ["FinanceOps"], None),
    ("POST", "/invoices/{id}/void", ["FinanceOps"], None),

    ("POST", "/disputes", ["ComplianceOfficer", "FinanceOps"], "order"),
    ("GET", "/disputes", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps"], None),
    ("GET", "/disputes/{id}", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps"], None),
    ("POST", "/disputes/{id}/resolve", ["ComplianceOfficer"], None),

    ("POST", "/sales-reports", ["FinanceOps"], "agreement"),
    ("GET", "/sales-reports", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps"], None),
    ("GET", "/sales-reports/{id}", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor", "FinanceOps"], None),
    ("POST", "/sales-reports/{id}/finalize", ["FinanceOps"], None),

    ("POST", "/audits", ["Auditor"], "agreement"),
    ("GET", "/audits", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor"], None),
    ("GET", "/audits/{id}", ["PlatformAdmin", "ContractsManager", "ComplianceOfficer", "Auditor"], None),
    ("POST", "/audits/{id}/issue-finding", ["Auditor"], None),
    ("POST", "/audits/{id}/close", ["ComplianceOfficer"], None),
]

_TEMPLATE_RE = re.compile(r"\{id\}")


def _template_regex(template):
    return re.compile("^" + _TEMPLATE_RE.sub(r"(?P<id>[^/]+)", template) + "$")


_COMPILED = [(m, t, _template_regex(t), roles, fk) for (m, t, roles, fk) in ROUTES]


def match_route(method, path):
    """Return (roles, fk_entity, params_dict) for the route, or None."""
    for m, template, rx, roles, fk in _COMPILED:
        if m != method:
            continue
        match = rx.match(path)
        if match:
            return roles, fk, match.groupdict()
    return None


def auth_check():
    """Pipeline steps 1-2. Raises ApiError on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role:
        raise ApiError(ERR_MISSING_AUTH_HEADERS, "X-User-ID and X-User-Role headers are required", 401)
    route = match_route(request.method, request.path)
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHORIZED, "role is not a declared role", 403)
    if route is None:
        raise ApiError(ERR_UNAUTHORIZED, "method/path not declared for this role", 403)
    roles, _fk, _params = route
    if role not in roles:
        raise ApiError(ERR_UNAUTHORIZED, "role not permitted on this endpoint", 403)
    return user_id, role
