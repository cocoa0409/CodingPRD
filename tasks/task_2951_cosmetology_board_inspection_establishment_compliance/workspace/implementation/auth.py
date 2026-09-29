"""Authentication, RBAC and ownership scoping (PRD 2.1 and 2.9 steps 1-6)."""
from flask import request

import store
from errors import fail

ROLES = (
    "BoardAdmin",
    "Inspector",
    "HearingOfficer",
    "EstablishmentOwner",
    "Practitioner",
    "SchoolRegistrar",
    "HealthAuthorityLiaison",
)

ENTITY_BACKED = {
    "EstablishmentOwner": store.establishments,
    "Practitioner": store.practitioners,
    "SchoolRegistrar": store.schools,
}


class Ctx(object):
    __slots__ = ("role", "user_id", "actor")

    def __init__(self, role, user_id, actor):
        self.role = role
        self.user_id = user_id
        self.actor = actor

    @property
    def is_owner(self):
        return self.role == "EstablishmentOwner"

    @property
    def is_prac(self):
        return self.role == "Practitioner"

    @property
    def is_registrar(self):
        return self.role == "SchoolRegistrar"


def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role.strip() == "" or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised X-User-Role value.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not access this endpoint." % role)
    actor = None
    if role in ENTITY_BACKED:
        actor = ENTITY_BACKED[role].get(user_id)
        if actor is None:
            fail("ERR_UNAUTHORIZED", "X-User-ID does not resolve to a %s row." % role)
    return Ctx(role, user_id, actor)


def deny():
    fail("ERR_UNAUTHORIZED", "Caller is outside the ownership scope of this resource.")


# ------------------------------------------------------- reachability helpers
def est_of_workstation(ws):
    return ws["establishment_id"]


def est_of_rental(rental):
    ws = store.workstations.get(rental["workstation_id"])
    return ws["establishment_id"] if ws else None


def est_of_inspection(insp):
    return insp["establishment_id"]


def est_of_citation(cit):
    insp = store.inspections.get(cit["inspection_id"])
    return insp["establishment_id"] if insp else None


def est_of_finding(finding):
    insp = store.inspections.get(finding["inspection_id"])
    return insp["establishment_id"] if insp else None


def citation_of_hearing(hearing):
    return store.citations.get(hearing["citation_id"])


def practitioner_linked_to_establishment(practitioner_id, establishment_id, statuses=("PROPOSED", "ACTIVE")):
    """True when a booth rental in one of `statuses` joins the practitioner to the salon."""
    ws_ids = set(
        w["id"] for w in store.workstations.values() if w["establishment_id"] == establishment_id
    )
    for r in store.booth_rentals.values():
        if r["practitioner_id"] == practitioner_id and r["workstation_id"] in ws_ids:
            if statuses is None or r["status"] in statuses:
                return True
    return False


def practitioner_touches_workstation(practitioner_id, ws):
    if ws.get("posted_practitioner_id") == practitioner_id:
        return True
    for r in store.booth_rentals.values():
        if r["workstation_id"] == ws["id"] and r["practitioner_id"] == practitioner_id:
            return True
    return False


def practitioner_reachable_from_establishment(practitioner_id, establishment_id):
    return practitioner_linked_to_establishment(practitioner_id, establishment_id, statuses=None)
