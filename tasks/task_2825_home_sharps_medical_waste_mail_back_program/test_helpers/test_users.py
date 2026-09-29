"""Pre-built role headers for every role named by the PRD.

PRD 2.1 splits the six roles into two identity families:

* Opaque operator identifiers — ProgramAdmin, LogisticsCoordinator,
  IntakeTechnician and DestructionOfficer. `X-User-ID` is never compared to any
  entity's `id`, so a shared constant is the canonical form. The technician and
  officer identifiers are nonetheless persisted (`screened_by_user_id`,
  `issued_by_user_id`) and compared to each other for segregation of duties, so
  two distinct constants are supplied for each of those roles.
* Entity-backed identities — SponsorRepresentative (`X-User-ID` is the acting
  Sponsor's `id`) and Patient (`X-User-ID` is the acting Patient's `id`). Every
  ownership-gated call must use the per-instance builder below.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used across the suite.
ADMIN_USER_ID = "admin-01"
LOGISTICS_USER_ID = "logi-01"
INTAKE_TECHNICIAN_USER_ID = "tech-01"
SECOND_INTAKE_TECHNICIAN_USER_ID = "tech-02"
DESTRUCTION_OFFICER_USER_ID = "officer-07"
SECOND_DESTRUCTION_OFFICER_USER_ID = "officer-08"

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (malformed payloads, unknown identifiers, role-membership refusals).
TEST_USERS = {
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "logistics_coordinator_headers": build_user_headers(
        LOGISTICS_USER_ID, "LogisticsCoordinator"
    ),
    "intake_technician_headers": build_user_headers(
        INTAKE_TECHNICIAN_USER_ID, "IntakeTechnician"
    ),
    "second_intake_technician_headers": build_user_headers(
        SECOND_INTAKE_TECHNICIAN_USER_ID, "IntakeTechnician"
    ),
    "destruction_officer_headers": build_user_headers(
        DESTRUCTION_OFFICER_USER_ID, "DestructionOfficer"
    ),
    "second_destruction_officer_headers": build_user_headers(
        SECOND_DESTRUCTION_OFFICER_USER_ID, "DestructionOfficer"
    ),
    # Entity-backed roles: these shared constants are a fallback for tests that
    # never reach an ownership check.
    "sponsor_representative_headers": build_user_headers(
        "unbound-sponsor-rep", "SponsorRepresentative"
    ),
    "patient_headers": build_user_headers("unbound-patient", "Patient"),
}


def make_sponsor_representative_headers(sponsor_id: str) -> dict:
    """Headers for a SponsorRepresentative acting as the sponsor whose `id` is
    `sponsor_id`. Mandatory for every ownership-gated sponsor call."""
    return build_user_headers(sponsor_id, "SponsorRepresentative")


def make_patient_headers(patient_id: str) -> dict:
    """Headers for a Patient acting as the patient whose `id` is `patient_id`.
    Mandatory for every ownership-gated kit call."""
    return build_user_headers(patient_id, "Patient")


def make_program_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers for a ProgramAdmin with an explicit opaque operator identifier."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_logistics_coordinator_headers(user_id: str = LOGISTICS_USER_ID) -> dict:
    """Headers for a LogisticsCoordinator with an explicit opaque identifier."""
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_intake_technician_headers(
    user_id: str = INTAKE_TECHNICIAN_USER_ID,
) -> dict:
    """Headers for an IntakeTechnician; `user_id` is persisted onto the screened
    shipment as `screened_by_user_id`."""
    return build_user_headers(user_id, "IntakeTechnician")


def make_destruction_officer_headers(
    user_id: str = DESTRUCTION_OFFICER_USER_ID,
) -> dict:
    """Headers for a DestructionOfficer; `user_id` is persisted onto every
    certificate as `issued_by_user_id`."""
    return build_user_headers(user_id, "DestructionOfficer")


HEADERS_BY_ROLE = {
    "ProgramAdmin": TEST_USERS["program_admin_headers"],
    "LogisticsCoordinator": TEST_USERS["logistics_coordinator_headers"],
    "IntakeTechnician": TEST_USERS["intake_technician_headers"],
    "DestructionOfficer": TEST_USERS["destruction_officer_headers"],
    "SponsorRepresentative": TEST_USERS["sponsor_representative_headers"],
    "Patient": TEST_USERS["patient_headers"],
}
