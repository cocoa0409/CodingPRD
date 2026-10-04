"""Middleware: header extraction, role validation, RBAC and ownership (PRD 2.1).

Callers present ``X-User-ID`` and ``X-User-Role`` on every request.  Only the
two system-driving operations that move the logical clock are exempt.
"""

from flask import request

from errors import APIError

ROLES = (
    "Member",
    "CareAdvocate",
    "ClinicalReviewer",
    "ClinicCoordinator",
    "SpecialtyPharmacist",
    "ClaimsProcessor",
    "ClaimsReviewer",
    "NetworkManager",
    "PlanAdministrator",
)

# Verbatim role sets from PRD section 4.  Matched on (method, path-pattern).
# Patterns are compared with each ``{param}`` segment matching exactly one
# non-empty path segment; longer patterns are tried first.
_ENDPOINTS = [
    ("POST", "/_clock/set_current_utc", ("PlanAdministrator", "NetworkManager", "ClaimsProcessor")),
    ("POST", "/_system/tick", ("PlanAdministrator", "NetworkManager", "ClaimsProcessor")),

    ("POST", "/employer-accounts", ("PlanAdministrator",)),
    ("GET", "/employer-accounts/{id}", ("PlanAdministrator", "NetworkManager", "CareAdvocate", "ClaimsProcessor", "ClinicalReviewer")),
    ("GET", "/employer-accounts", ("PlanAdministrator", "NetworkManager", "ClaimsProcessor")),
    ("POST", "/employer-accounts/{id}/suspend", ("PlanAdministrator",)),
    ("POST", "/employer-accounts/{id}/reactivate", ("PlanAdministrator",)),

    ("POST", "/bundle-entitlements", ("PlanAdministrator",)),
    ("GET", "/bundle-entitlements/{id}", ("PlanAdministrator", "CareAdvocate", "ClinicalReviewer", "ClaimsProcessor", "SpecialtyPharmacist")),
    ("GET", "/bundle-entitlements", ("PlanAdministrator", "CareAdvocate", "ClinicalReviewer", "ClaimsProcessor")),
    ("POST", "/bundle-entitlements/{id}/activate", ("PlanAdministrator",)),
    ("POST", "/bundle-entitlements/{id}/reinstate", ("PlanAdministrator",)),

    ("POST", "/care-advocates", ("PlanAdministrator",)),
    ("GET", "/care-advocates/{id}", ("PlanAdministrator", "CareAdvocate", "Member", "NetworkManager")),
    ("GET", "/care-advocates", ("PlanAdministrator", "CareAdvocate", "Member", "NetworkManager")),

    ("POST", "/members", ("CareAdvocate", "PlanAdministrator")),
    ("GET", "/members/{id}", ("Member", "CareAdvocate", "ClinicalReviewer", "ClinicCoordinator", "ClaimsProcessor", "NetworkManager", "SpecialtyPharmacist")),
    ("GET", "/members", ("CareAdvocate", "ClinicalReviewer", "ClinicCoordinator", "ClaimsProcessor", "NetworkManager", "PlanAdministrator")),
    ("POST", "/members/{id}/assign-advocate", ("PlanAdministrator", "NetworkManager")),
    ("POST", "/members/{id}/complete-intake", ("CareAdvocate", "PlanAdministrator")),
    ("POST", "/members/{id}/complete-care", ("CareAdvocate", "PlanAdministrator")),
    ("POST", "/members/{id}/select-clinic", ("CareAdvocate",)),
    ("POST", "/members/{id}/surrender-routes", ("CareAdvocate",)),
    ("GET", "/members/{id}/surrender-routes", ("Member", "CareAdvocate", "ClinicalReviewer", "NetworkManager")),
    ("POST", "/members/{id}/surrender-routes/withdraw", ("CareAdvocate",)),
    ("POST", "/members/{id}/surrender-routes/retire", ("CareAdvocate",)),

    ("GET", "/surrender-routes", ("CareAdvocate", "ClinicalReviewer", "NetworkManager", "PlanAdministrator")),
    ("GET", "/surrender-routes/{id}", ("CareAdvocate", "ClinicalReviewer", "NetworkManager")),

    ("POST", "/clinics", ("NetworkManager",)),
    ("GET", "/clinics/{id}", ("NetworkManager", "ClinicalReviewer", "CareAdvocate", "ClinicCoordinator", "ClaimsProcessor", "PlanAdministrator")),
    ("GET", "/clinics", ("NetworkManager", "ClinicalReviewer", "CareAdvocate", "ClinicCoordinator", "ClaimsProcessor")),
    ("POST", "/clinics/{id}/contracts", ("NetworkManager",)),
    ("POST", "/clinics/{id}/suspend", ("NetworkManager",)),
    ("POST", "/clinics/{id}/terminate", ("NetworkManager",)),
    ("POST", "/clinics/{id}/quality-recompute", ("NetworkManager",)),
    ("POST", "/clinics/{id}/report-outcome", ("ClinicCoordinator",)),

    ("GET", "/clinic-contracts/{id}", ("NetworkManager", "PlanAdministrator", "CareAdvocate", "ClinicalReviewer")),
    ("GET", "/clinic-contracts", ("NetworkManager", "PlanAdministrator", "CareAdvocate", "ClinicalReviewer", "ClaimsProcessor")),
    ("POST", "/clinic-contracts/{id}/activate", ("NetworkManager",)),
    ("POST", "/clinic-contracts/{id}/terminate", ("NetworkManager",)),

    ("POST", "/treatment-plans", ("CareAdvocate",)),
    ("GET", "/treatment-plans/{id}", ("CareAdvocate", "ClinicalReviewer", "ClinicCoordinator", "ClaimsProcessor", "NetworkManager", "Member", "PlanAdministrator")),
    ("GET", "/treatment-plans", ("CareAdvocate", "ClinicalReviewer", "ClinicCoordinator", "ClaimsProcessor", "NetworkManager", "PlanAdministrator")),
    ("POST", "/treatment-plans/{id}/select-clinic", ("CareAdvocate",)),
    ("POST", "/treatment-plans/{id}/preauthorizations", ("CareAdvocate",)),
    ("POST", "/treatment-plans/{id}/resubmit-plan", ("CareAdvocate",)),
    ("POST", "/treatment-plans/{id}/abandon", ("CareAdvocate",)),
    ("POST", "/treatment-plans/{id}/treatment-cycles", ("ClinicCoordinator",)),

    ("GET", "/preauthorizations/{id}", ("CareAdvocate", "ClinicalReviewer", "ClinicCoordinator", "ClaimsProcessor", "SpecialtyPharmacist", "Member")),
    ("GET", "/preauthorizations", ("CareAdvocate", "ClinicalReviewer", "ClinicCoordinator", "ClaimsProcessor", "SpecialtyPharmacist", "PlanAdministrator")),
    ("POST", "/preauthorizations/{id}/begin-clinical-review", ("ClinicalReviewer",)),
    ("POST", "/preauthorizations/{id}/decide", ("ClinicalReviewer",)),
    ("POST", "/preauthorizations/{id}/revise-request", ("CareAdvocate",)),

    ("GET", "/treatment-cycles/{id}", ("ClinicCoordinator", "ClinicalReviewer", "ClaimsProcessor", "NetworkManager", "CareAdvocate", "Member")),
    ("GET", "/treatment-cycles", ("ClinicCoordinator", "ClinicalReviewer", "ClaimsProcessor", "NetworkManager", "CareAdvocate")),
    ("POST", "/treatment-cycles/{id}/start-stimulation", ("ClinicCoordinator",)),
    ("POST", "/treatment-cycles/{id}/record-retrieval", ("ClinicCoordinator",)),
    ("POST", "/treatment-cycles/{id}/record-fertilization", ("ClinicCoordinator",)),
    ("POST", "/treatment-cycles/{id}/record-transfer", ("ClinicCoordinator",)),
    ("POST", "/treatment-cycles/{id}/record-outcome", ("ClinicCoordinator",)),
    ("POST", "/treatment-cycles/{id}/cancel", ("ClinicCoordinator",)),

    ("POST", "/medication-orders", ("SpecialtyPharmacist", "CareAdvocate")),
    ("GET", "/medication-orders/{id}", ("SpecialtyPharmacist", "CareAdvocate", "ClaimsProcessor", "Member", "ClinicalReviewer")),
    ("GET", "/medication-orders", ("SpecialtyPharmacist", "CareAdvocate", "ClaimsProcessor", "ClinicalReviewer", "PlanAdministrator")),
    ("POST", "/medication-orders/{id}/dispense", ("SpecialtyPharmacist",)),
    ("POST", "/medication-orders/{id}/ship", ("SpecialtyPharmacist",)),
    ("POST", "/medication-orders/{id}/deliver", ("SpecialtyPharmacist",)),
    ("POST", "/medication-orders/{id}/cancel", ("SpecialtyPharmacist",)),

    ("POST", "/pathway-requests", ("CareAdvocate",)),
    ("GET", "/pathway-requests/{id}", ("CareAdvocate", "ClinicalReviewer", "Member", "NetworkManager")),
    ("GET", "/pathway-requests", ("CareAdvocate", "ClinicalReviewer", "NetworkManager", "PlanAdministrator")),
    ("POST", "/pathway-requests/{id}/begin-clinical-review", ("ClinicalReviewer",)),
    ("POST", "/pathway-requests/{id}/decide", ("ClinicalReviewer",)),
    ("POST", "/pathway-requests/{id}/activate", ("CareAdvocate",)),
    ("POST", "/pathway-requests/{id}/complete", ("CareAdvocate",)),
    ("POST", "/pathway-requests/{id}/withdraw", ("CareAdvocate",)),

    ("POST", "/claims", ("ClinicCoordinator", "ClaimsProcessor", "SpecialtyPharmacist")),
    ("GET", "/claims/{id}", ("ClaimsProcessor", "ClaimsReviewer", "CareAdvocate", "Member", "ClinicCoordinator", "NetworkManager")),
    ("GET", "/claims", ("ClaimsProcessor", "ClaimsReviewer", "CareAdvocate", "ClinicCoordinator", "NetworkManager", "PlanAdministrator")),
    ("POST", "/claims/{id}/adjudicate", ("ClaimsProcessor",)),
    ("POST", "/claims/{id}/deny", ("ClaimsProcessor",)),
    ("POST", "/claims/{id}/pay", ("ClaimsProcessor",)),
    ("POST", "/claims/{id}/appeal", ("CareAdvocate",)),
    ("POST", "/claims/{id}/appeal-decide", ("ClaimsReviewer",)),
    ("POST", "/claims/{id}/reverse", ("ClaimsProcessor",)),

    ("GET", "/outcome-records/{id}", ("NetworkManager", "ClinicalReviewer", "ClinicCoordinator", "PlanAdministrator")),
    ("GET", "/outcome-records", ("NetworkManager", "ClinicalReviewer", "ClinicCoordinator", "PlanAdministrator", "CareAdvocate")),
    ("POST", "/outcome-records/{id}/amend", ("NetworkManager",)),
    ("POST", "/outcome-records/{id}/void", ("NetworkManager",)),
]

# Endpoints exempt from the header requirement (PRD 2.1).
_EXEMPT = {("POST", "/_clock/set_current_utc"), ("POST", "/_system/tick")}


def _match(method, path, pattern):
    if method != pattern[0]:
        return False
    want = pattern[1].strip("/").split("/")
    got = path.strip("/").split("/")
    if len(want) != len(got):
        return False
    for w, g in zip(want, got):
        if w.startswith("{") and w.endswith("}"):
            if g == "":
                return False
            continue
        if w != g:
            return False
    return True


# Longest patterns first so a nested path never falls through to its parent.
_ORDERED = sorted(_ENDPOINTS, key=lambda e: -len(e[1].split("/")))


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def resolve_actor():
    """Validate the auth headers (priority 1) and the role for this operation (2)."""
    method = request.method
    path = request.path
    if (method, path.rstrip("/") or "/") in _EXEMPT:
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        return Actor(user_id, role)

    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise APIError(
            "ERR_UNAUTHENTICATED",
            "X-User-Role header is absent or names an unrecognised capacity.",
        )
    user_id = request.headers.get("X-User-ID")

    allowed = None
    for pattern in _ORDERED:
        if _match(method, path, pattern):
            allowed = pattern[2]
            break
    if allowed is not None and role not in allowed:
        raise APIError(
            "ERR_UNAUTHORIZED",
            "The calling role is not permitted for this operation.",
        )
    return Actor(user_id, role)


def require_member_ownership(actor, member_id):
    """A Member may read only their own records (PRD 2.1)."""
    if actor is None or actor.role != "Member":
        return
    if member_id is None or actor.user_id != member_id:
        raise APIError(
            "ERR_UNAUTHORIZED",
            "A member may read only their own records.",
        )