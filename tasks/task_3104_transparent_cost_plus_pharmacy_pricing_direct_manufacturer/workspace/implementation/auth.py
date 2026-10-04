"""Role extraction, permission table and patient-ownership enforcement.

PRD §2.1: every request carries X-User-ID and X-User-Role. An absent or
undeclarable role is ERR_MISSING_ROLE_HEADER (401) before any other
consideration; a declared but unpermitted role is ERR_ROLE_NOT_PERMITTED
(403); a Patient addressing a resource that is not theirs is
ERR_PATIENT_OWNERSHIP_REQUIRED (403).
"""

from errors import ApiError, fail

ROLES = ("Patient", "Pharmacist", "PharmacyOps", "Anonymous")

# The caller's role is validated against the declared four BEFORE the route is
# matched (PRD §2.1, "before any other consideration"), so an unmatched path
# reached with a bogus role reports the header error rather than a 404.
EXEMPT_PATHS = ("/_health",)

# key -> permitted roles, keyed by "METHOD:rule" as declared in the PRD §4
# endpoint table. Route rules and endpoint keys are kept identical on purpose.
PERMISSIONS = {
    "POST:/_clock/set_current_utc": ("PharmacyOps",),
    "GET:/_health": ("Anonymous", "Patient", "Pharmacist", "PharmacyOps"),
    "POST:/manufacturers": ("PharmacyOps",),
    "GET:/manufacturers/<manufacturer_id>": ("PharmacyOps",),
    "GET:/manufacturers": ("PharmacyOps",),
    "POST:/manufacturers/<manufacturer_id>/state": ("PharmacyOps",),
    "GET:/manufacturers/<manufacturer_id>/drug-prices": ("PharmacyOps",),
    "POST:/drugs": ("PharmacyOps",),
    "GET:/drugs/<drug_id>": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/drugs": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/formularies/<drug_id>/stock-check": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/formularies/<drug_id>/supply-summary": ("PharmacyOps", "Pharmacist"),
    "GET:/formularies/<drug_id>/expansion-score": ("PharmacyOps", "Pharmacist"),
    "POST:/formularies/<drug_id>/expansion": ("PharmacyOps",),
    "POST:/formularies/<drug_id>/delist": ("PharmacyOps",),
    "POST:/manufacturer-drug-prices": ("PharmacyOps",),
    "GET:/manufacturer-drug-prices/<price_id>": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/manufacturer-drug-prices": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/drugs/<drug_id>/manufacturer-drug-prices": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/drugs/<drug_id>/prescriptions": ("PharmacyOps", "Pharmacist"),
    "POST:/manufacturer-drug-prices/<price_id>/activation": ("PharmacyOps",),
    "POST:/manufacturer-drug-prices/<price_id>/sourcing": ("PharmacyOps",),
    "POST:/manufacturer-drug-prices/<price_id>/revocation": ("PharmacyOps",),
    "POST:/pharmacies": ("PharmacyOps",),
    "GET:/pharmacies/<pharmacy_id>": ("PharmacyOps", "Pharmacist"),
    "GET:/pharmacies": ("PharmacyOps",),
    "POST:/pharmacies/<pharmacy_id>/licenses": ("PharmacyOps",),
    "GET:/pharmacies/<pharmacy_id>/licenses": ("PharmacyOps", "Pharmacist"),
    "GET:/pharmacies/<pharmacy_id>/licenses/<license_id>": ("PharmacyOps", "Pharmacist"),
    "POST:/pharmacies/<pharmacy_id>/licenses/<license_id>/state": ("PharmacyOps",),
    "POST:/pharmacies/<pharmacy_id>/licenses/<license_id>/verification": ("PharmacyOps",),
    "POST:/patients": ("PharmacyOps",),
    "GET:/patients/<patient_id>": ("PharmacyOps", "Patient"),
    "GET:/patients": ("PharmacyOps",),
    "POST:/prescribers": ("PharmacyOps",),
    "GET:/prescribers/<prescriber_id>": ("PharmacyOps", "Pharmacist"),
    "POST:/prescribers/<prescriber_id>/state": ("PharmacyOps",),
    "POST:/prescriptions": ("PharmacyOps",),
    "GET:/prescriptions/<prescription_id>": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/prescriptions": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/prescription-requests": ("PharmacyOps", "Pharmacist"),
    "GET:/claims": ("PharmacyOps", "Pharmacist"),
    "GET:/shipments": ("PharmacyOps", "Pharmacist"),
    "GET:/comparisons": ("PharmacyOps", "Pharmacist"),
    "GET:/patients/<patient_id>/prescriptions": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/prescribers/<prescriber_id>/prescriptions": ("PharmacyOps", "Pharmacist"),
    "POST:/prescriptions/<prescription_id>/intake-requests": ("PharmacyOps",),
    "POST:/prescriptions/<prescription_id>/termination": ("Pharmacist",),
    "POST:/prescriptions/<prescription_id>/substitution": ("Pharmacist",),
    "GET:/prescription-requests/<request_id>": ("PharmacyOps", "Pharmacist"),
    "GET:/prescriptions/<prescription_id>/intake-requests": ("PharmacyOps", "Pharmacist"),
    "POST:/prescription-requests/<request_id>/review": ("Pharmacist",),
    "POST:/prescription-requests/<request_id>/acceptance": ("Pharmacist",),
    "POST:/prescription-requests/<request_id>/rejection": ("Pharmacist",),
    "POST:/orders": ("PharmacyOps",),
    "GET:/orders/<order_id>": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/orders": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/prescriptions/<prescription_id>/orders": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/prescription-requests/<request_id>/orders": ("PharmacyOps", "Pharmacist"),
    "GET:/pharmacies/<pharmacy_id>/orders": ("PharmacyOps", "Pharmacist"),
    "GET:/manufacturer-drug-prices/<price_id>/orders": ("PharmacyOps", "Pharmacist"),
    "POST:/orders/<order_id>/payment": ("PharmacyOps",),
    "POST:/orders/<order_id>/fulfillment": ("PharmacyOps",),
    "POST:/orders/<order_id>/shipping": ("PharmacyOps",),
    "POST:/orders/<order_id>/delivery": ("PharmacyOps",),
    "POST:/orders/<order_id>/cancellation": ("PharmacyOps",),
    "GET:/orders/<order_id>/comparisons": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/orders/<order_id>/comparison": ("PharmacyOps", "Pharmacist", "Patient"),
    "POST:/orders/<order_id>/comparisons/<comparison_id>/refresh": ("PharmacyOps",),
    "POST:/orders/<order_id>/substantiation-enablement": ("PharmacyOps",),
    "POST:/orders/<order_id>/substantiation-disablement": ("PharmacyOps",),
    "GET:/orders/<order_id>/substantiation-records": ("PharmacyOps", "Pharmacist"),
    "POST:/claims/<claim_id>/refill-authorizations": ("Pharmacist",),
    "GET:/claims/<claim_id>": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/claim-summaries/<claim_id>": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/prescriptions/<prescription_id>/claims": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/orders/<order_id>/shipments": ("PharmacyOps", "Pharmacist", "Patient"),
    "GET:/prescription-requests/<request_id>/shipments": ("PharmacyOps", "Pharmacist"),
    "GET:/shipment-summaries/<shipment_id>": ("PharmacyOps", "Pharmacist", "Patient"),
    "POST:/price-substantiations": ("PharmacyOps",),
    "GET:/price-substantiations/<substantiation_id>": ("PharmacyOps", "Pharmacist"),
    "GET:/price-substantiations": ("PharmacyOps", "Pharmacist"),
}

# Paths whose addressed resource is patient-scoped: the ownership rule of
# PRD §2.1 applies when the declared role is Patient.
PATIENT_SCOPED_PATHS = (
    "/orders",
    "/prescriptions",
    "/prescription-requests",
    "/claims",
    "/claim-summaries",
    "/comparisons",
    "/shipments",
    "/shipment-summaries",
    "/patients",
    "/price-substantiations",
    "/drugs",
    "/formularies",
    "/manufacturer-drug-prices",
    "/pharmacies",
    "/prescribers",
    "/manufacturers",
    "/_clock",
)


def is_patient_scoped(path):
    for prefix in PATIENT_SCOPED_PATHS:
        if prefix == "/_clock":
            return True
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def declared_role(raw_role):
    """Validate the role header; every other consideration comes after."""
    if raw_role is None:
        fail("ERR_MISSING_ROLE_HEADER")
    role = str(raw_role).strip()
    if role not in ROLES:
        fail("ERR_MISSING_ROLE_HEADER")
    return role


def require_permission(role, method, rule, permitted):
    if role not in permitted:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform %s %s." % (role, method, rule),
            403,
        )


def require_ownership(role, user_id, owner_patient_id):
    """PRD §2.1: never applies to Pharmacist or PharmacyOps callers."""
    if role != "Patient":
        return
    if owner_patient_id is None:
        fail("ERR_PATIENT_OWNERSHIP_REQUIRED")
    if str(user_id or "") != str(owner_patient_id):
        fail("ERR_PATIENT_OWNERSHIP_REQUIRED")