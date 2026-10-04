"""Auth header extraction and the role-permission matrix (PRD 2.1, 4)."""

import re

from errors import fail
from repository import find

ROLES = [
    "Anonymous",
    "Buyer",
    "DeliveryAdvisor",
    "TradeInSpecialist",
    "FinancePartner",
    "ServiceTechnician",
    "PartsCoordinator",
    "PlatformAdmin",
]

ENTITY_BACKED_PREFIX = "entity_backed:"

# (method, path pattern, allowed roles) — taken verbatim from the PRD endpoint table.
PERMISSIONS = [
    ("POST", "/v1/_clock/set_current_utc", ["PlatformAdmin"]),
    ("POST", "/v1/_payments/simulate", ["PlatformAdmin"]),
    ("POST", "/v1/buyers", ["Anonymous"]),
    ("GET", "/v1/buyers", ["PlatformAdmin", "FinancePartner"]),
    ("GET", "/v1/buyers/<buyer>", ["Buyer", "PlatformAdmin", "FinancePartner", "DeliveryAdvisor"]),
    ("POST", "/v1/buyers/<buyer>/identity-verification", ["PlatformAdmin", "Buyer"]),
    ("POST", "/v1/buyers/<buyer>/suspend", ["PlatformAdmin"]),
    ("GET", "/v1/buyers/<buyer>/fee-ledger-entries", ["PlatformAdmin", "FinancePartner", "Buyer"]),
    ("GET", "/v1/buyers/<buyer>/orders", ["PlatformAdmin", "DeliveryAdvisor", "FinancePartner", "Buyer"]),
    ("GET", "/v1/buyers/<buyer>/trade-in-appraisals", ["TradeInSpecialist", "PlatformAdmin", "FinancePartner", "Buyer"]),
    ("GET", "/v1/buyers/<buyer>/financing-applications", ["FinancePartner", "PlatformAdmin", "Buyer"]),
    ("POST", "/v1/jurisdictions", ["PlatformAdmin"]),
    ("GET", "/v1/jurisdictions", ["PlatformAdmin", "DeliveryAdvisor"]),
    ("GET", "/v1/jurisdictions/<jurisdiction>", ["PlatformAdmin", "DeliveryAdvisor", "Buyer"]),
    ("POST", "/v1/jurisdictions/<jurisdiction>/enact", ["PlatformAdmin"]),
    ("POST", "/v1/delivery-centers", ["PlatformAdmin"]),
    ("GET", "/v1/delivery-centers", ["PlatformAdmin", "DeliveryAdvisor", "ServiceTechnician"]),
    ("GET", "/v1/delivery-centers/<center>", ["PlatformAdmin", "DeliveryAdvisor", "ServiceTechnician", "PartsCoordinator"]),
    ("GET", "/v1/delivery-centers/<center>/delivery-appointments", ["DeliveryAdvisor", "PlatformAdmin"]),
    ("GET", "/v1/delivery-centers/<center>/service-appointments", ["ServiceTechnician", "PlatformAdmin"]),
    ("GET", "/v1/delivery-centers/<center>/mobile-service-visits", ["PartsCoordinator", "ServiceTechnician", "PlatformAdmin"]),
    ("POST", "/v1/delivery-centers/<center>/suspend", ["PlatformAdmin"]),
    ("POST", "/v1/delivery-centers/<center>/reinstate", ["PlatformAdmin"]),
    ("POST", "/v1/vehicle-configurations", ["PlatformAdmin"]),
    ("GET", "/v1/vehicle-configurations", ["PlatformAdmin", "Buyer"]),
    ("GET", "/v1/vehicle-configurations/<configuration>", ["PlatformAdmin", "Buyer", "TradeInSpecialist"]),
    ("POST", "/v1/vehicle-configurations/<configuration>/options", ["PlatformAdmin"]),
    ("GET", "/v1/vehicle-configurations/<configuration>/options", ["PlatformAdmin", "Buyer", "TradeInSpecialist"]),
    ("GET", "/v1/configuration-options", ["PlatformAdmin", "Buyer", "TradeInSpecialist"]),
    ("GET", "/v1/configuration-options/<option>", ["PlatformAdmin", "Buyer", "TradeInSpecialist"]),
    ("POST", "/v1/configuration-options/<option>/retire", ["PlatformAdmin"]),
    ("POST", "/v1/orders", ["Buyer", "PlatformAdmin"]),
    ("GET", "/v1/orders", ["Buyer", "PlatformAdmin", "DeliveryAdvisor", "FinancePartner", "TradeInSpecialist"]),
    ("GET", "/v1/orders/<order>", ["Buyer", "PlatformAdmin", "DeliveryAdvisor", "FinancePartner", "TradeInSpecialist", "ServiceTechnician"]),
    ("POST", "/v1/orders/<order>/configuration-changes", ["Buyer"]),
    ("POST", "/v1/orders/<order>/place", ["Buyer"]),
    ("POST", "/v1/orders/<order>/lock-configuration", ["Buyer", "PlatformAdmin"]),
    ("POST", "/v1/orders/<order>/cancel", ["Buyer", "PlatformAdmin"]),
    ("POST", "/v1/orders/<order>/allocation", ["PlatformAdmin"]),
    ("POST", "/v1/orders/<order>/dispatch-to-transport", ["PlatformAdmin"]),
    ("POST", "/v1/orders/<order>/arrive-at-center", ["PlatformAdmin"]),
    ("POST", "/v1/orders/<order>/delivery-estimates", ["PlatformAdmin"]),
    ("GET", "/v1/orders/<order>/delivery-estimates", ["Buyer", "PlatformAdmin", "DeliveryAdvisor"]),
    ("GET", "/v1/orders/<order>/trade-in-appraisals", ["Buyer", "PlatformAdmin", "TradeInSpecialist", "FinancePartner"]),
    ("GET", "/v1/orders/<order>/financing-applications", ["Buyer", "PlatformAdmin", "FinancePartner"]),
    ("GET", "/v1/orders/<order>/fee-ledger-entries", ["Buyer", "PlatformAdmin", "FinancePartner"]),
    ("POST", "/v1/orders/<order>/fee-ledger-entries", ["PlatformAdmin"]),
    ("GET", "/v1/orders/<order>/allocation-units", ["PlatformAdmin", "DeliveryAdvisor"]),
    ("GET", "/v1/orders/<order>/delivery-appointments", ["Buyer", "PlatformAdmin", "DeliveryAdvisor"]),
    ("GET", "/v1/orders/<order>/vehicles", ["Buyer", "PlatformAdmin", "ServiceTechnician", "DeliveryAdvisor"]),
    ("POST", "/v1/orders/<order>/trade-in-appraisals", ["Buyer", "TradeInSpecialist"]),
    ("POST", "/v1/orders/<order>/trade-in-appraisals/<appraisal>/appraise", ["TradeInSpecialist"]),
    ("POST", "/v1/orders/<order>/trade-in-appraisals/<appraisal>/offer", ["TradeInSpecialist"]),
    ("POST", "/v1/orders/<order>/trade-in-appraisals/<appraisal>/accept", ["Buyer"]),
    ("POST", "/v1/orders/<order>/trade-in-appraisals/<appraisal>/reject", ["Buyer"]),
    ("POST", "/v1/orders/<order>/trade-in-appraisals/<appraisal>/reappraise", ["TradeInSpecialist"]),
    ("POST", "/v1/orders/<order>/financing-applications", ["Buyer"]),
    ("POST", "/v1/delivery-appointments", ["DeliveryAdvisor"]),
    ("GET", "/v1/delivery-appointments", ["DeliveryAdvisor", "PlatformAdmin", "Buyer"]),
    ("GET", "/v1/delivery-appointments/<appointment>", ["DeliveryAdvisor", "PlatformAdmin", "Buyer"]),
    ("POST", "/v1/delivery-appointments/<appointment>/confirm", ["DeliveryAdvisor"]),
    ("POST", "/v1/delivery-appointments/<appointment>/rebook", ["DeliveryAdvisor"]),
    ("POST", "/v1/delivery-appointments/<appointment>/cancel", ["DeliveryAdvisor"]),
    ("POST", "/v1/delivery-appointments/<appointment>/complete", ["DeliveryAdvisor"]),
    ("GET", "/v1/trade-in-appraisals", ["TradeInSpecialist", "PlatformAdmin", "FinancePartner", "Buyer"]),
    ("GET", "/v1/trade-in-appraisals/<appraisal>", ["TradeInSpecialist", "PlatformAdmin", "FinancePartner", "Buyer"]),
    ("GET", "/v1/financing-applications", ["FinancePartner", "PlatformAdmin", "Buyer"]),
    ("GET", "/v1/financing-applications/<application>", ["FinancePartner", "PlatformAdmin", "Buyer"]),
    ("POST", "/v1/financing-applications/<application>/decision", ["FinancePartner"]),
    ("POST", "/v1/financing-applications/<application>/contract-review", ["FinancePartner"]),
    ("POST", "/v1/financing-applications/<application>/fund", ["FinancePartner"]),
    ("POST", "/v1/production-batches", ["PlatformAdmin"]),
    ("GET", "/v1/production-batches", ["PlatformAdmin"]),
    ("GET", "/v1/production-batches/<batch>", ["PlatformAdmin", "DeliveryAdvisor"]),
    ("POST", "/v1/production-batches/<batch>/start", ["PlatformAdmin"]),
    ("POST", "/v1/production-batches/<batch>/delay", ["PlatformAdmin"]),
    ("POST", "/v1/production-batches/<batch>/resume", ["PlatformAdmin"]),
    ("POST", "/v1/production-batches/<batch>/complete", ["PlatformAdmin"]),
    ("POST", "/v1/production-batches/<batch>/allocation-units", ["PlatformAdmin"]),
    ("GET", "/v1/production-batches/<batch>/allocation-units", ["PlatformAdmin", "DeliveryAdvisor"]),
    ("GET", "/v1/allocation-units/<unit>", ["PlatformAdmin", "DeliveryAdvisor"]),
    ("GET", "/v1/delivery-estimates", ["Buyer", "PlatformAdmin", "DeliveryAdvisor"]),
    ("GET", "/v1/delivery-estimates/<estimate>", ["Buyer", "PlatformAdmin", "DeliveryAdvisor"]),
    ("POST", "/v1/delivery-estimates/<estimate>/restore", ["PlatformAdmin"]),
    ("POST", "/v1/vehicles/<vehicle>/diagnostic-reports", ["ServiceTechnician", "PlatformAdmin"]),
    ("GET", "/v1/diagnostic-reports", ["ServiceTechnician", "PlatformAdmin", "PartsCoordinator"]),
    ("GET", "/v1/diagnostic-reports/<report>", ["ServiceTechnician", "PlatformAdmin", "PartsCoordinator"]),
    ("GET", "/v1/vehicles", ["ServiceTechnician", "PlatformAdmin", "Buyer", "PartsCoordinator"]),
    ("GET", "/v1/vehicles/<vehicle>", ["ServiceTechnician", "PlatformAdmin", "Buyer", "PartsCoordinator"]),
    ("GET", "/v1/vehicles/<vehicle>/diagnostic-reports", ["ServiceTechnician", "PlatformAdmin", "Buyer"]),
    ("GET", "/v1/vehicles/<vehicle>/service-appointments", ["ServiceTechnician", "PlatformAdmin", "Buyer"]),
    ("GET", "/v1/vehicles/<vehicle>/mobile-service-visits", ["ServiceTechnician", "PlatformAdmin", "PartsCoordinator", "Buyer"]),
    ("GET", "/v1/vehicles/<vehicle>/software-entitlements", ["ServiceTechnician", "PlatformAdmin", "Buyer"]),
    ("GET", "/v1/vehicles/<vehicle>/issue-notes", ["ServiceTechnician", "PlatformAdmin", "DeliveryAdvisor", "Buyer"]),
    ("POST", "/v1/vehicles/<vehicle>/retire", ["PlatformAdmin"]),
    ("POST", "/v1/service-appointments", ["ServiceTechnician"]),
    ("GET", "/v1/service-appointments", ["ServiceTechnician", "PlatformAdmin", "PartsCoordinator", "Buyer"]),
    ("GET", "/v1/service-appointments/<service_appointment>", ["ServiceTechnician", "PlatformAdmin", "PartsCoordinator", "Buyer"]),
    ("POST", "/v1/service-appointments/<service_appointment>/schedule-center", ["ServiceTechnician"]),
    ("POST", "/v1/service-appointments/<service_appointment>/cancel", ["ServiceTechnician", "PlatformAdmin"]),
    ("POST", "/v1/mobile-service-visits", ["ServiceTechnician"]),
    ("GET", "/v1/mobile-service-visits", ["ServiceTechnician", "PlatformAdmin", "PartsCoordinator", "Buyer"]),
    ("GET", "/v1/mobile-service-visits/<visit>", ["ServiceTechnician", "PlatformAdmin", "PartsCoordinator", "Buyer"]),
    ("POST", "/v1/mobile-service-visits/<visit>/reserve-parts", ["PartsCoordinator"]),
    ("POST", "/v1/mobile-service-visits/<visit>/confirm-parts-shipment", ["PartsCoordinator"]),
    ("POST", "/v1/mobile-service-visits/<visit>/start", ["ServiceTechnician"]),
    ("POST", "/v1/mobile-service-visits/<visit>/complete", ["ServiceTechnician"]),
    ("POST", "/v1/mobile-service-visits/<visit>/cancel", ["ServiceTechnician", "PlatformAdmin"]),
    ("POST", "/v1/mobile-service-visits/<visit>/reschedule", ["ServiceTechnician"]),
    ("POST", "/v1/vehicles/<vehicle>/software-entitlements", ["PlatformAdmin", "Buyer"]),
    ("GET", "/v1/software-entitlements", ["PlatformAdmin", "ServiceTechnician", "Buyer", "FinancePartner"]),
    ("GET", "/v1/software-entitlements/<entitlement>", ["PlatformAdmin", "Buyer", "ServiceTechnician"]),
    ("POST", "/v1/vehicles/<vehicle>/software-entitlements/<entitlement>/revoke", ["PlatformAdmin"]),
    ("GET", "/v1/issue-notes", ["ServiceTechnician", "PlatformAdmin", "DeliveryAdvisor", "Buyer"]),
    ("GET", "/v1/issue-notes/<note>", ["ServiceTechnician", "PlatformAdmin", "DeliveryAdvisor", "Buyer"]),
    ("POST", "/v1/issue-notes/<note>/resolve", ["ServiceTechnician", "DeliveryAdvisor"]),
    ("POST", "/v1/issue-notes/<note>/waive", ["PlatformAdmin"]),
    ("GET", "/v1/fee-ledger-entries", ["PlatformAdmin", "FinancePartner", "Buyer"]),
]

PLACEHOLDER = re.compile(r"<([a-z_]+)>")


def _compile(pattern):
    regex = PLACEHOLDER.sub(r"(?P<\1>[^/]+)", pattern)
    return re.compile("^" + regex + "$")


# Longer paths first so a more specific rule can never be shadowed.
_COMPILED = []
for _method, _pattern, _roles in sorted(
        PERMISSIONS, key=lambda r: -len(r[1].split("/"))):
    _COMPILED.append((_method, _compile(_pattern), _roles, _pattern))


def resolve_roles(method, path):
    for rule_method, regex, roles, pattern in _COMPILED:
        if rule_method != method:
            continue
        if regex.match(path):
            return roles, pattern
    return None, None


def extract_context(headers):
    role = headers.get("X-User-Role")
    if role is None or role not in ROLES:
        fail("ERR_INVALID_USER_CONTEXT")
    return headers.get("X-User-ID") or "", role


def authorize(method, path, user_id, role):
    roles, _pattern = resolve_roles(method, path)
    if roles is None:
        fail("ERR_INVALID_REQUEST", "No operation is declared for this path.")
    if role not in roles:
        fail("ERR_INSUFFICIENT_PERMISSIONS")
    if role == "Buyer":
        buyer = find("buyer", user_id)
        if buyer is not None and buyer["status"] == "SUSPENDED":
            fail("ERR_BUYER_SUSPENDED")