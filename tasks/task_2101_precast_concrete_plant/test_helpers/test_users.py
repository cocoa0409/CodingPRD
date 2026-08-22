"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers used across the suite.  For the six opaque roles the
# X-User-ID is an arbitrary operator string; the server records it wherever an
# audit trail or a duty-segregation check needs it but never compares it to a
# row id.
PLANT_ADMIN_USER = "admin-1"
PRODUCTION_SUPERVISOR_USER = "ps-carl"
PRODUCTION_SUPERVISOR_USER_ALT = "ps-dave"
QC_TECHNICIAN_USER = "qc-alice"
QC_TECHNICIAN_USER_ALT = "qc-frank"
QUALITY_ENGINEER_USER = "qe-bob"
QUALITY_ENGINEER_USER_ALT = "qe-gina"
YARD_FOREMAN_USER = "yf-dana"
PERMIT_COORDINATOR_USER = "pc-erin"

TEST_USERS = {
    "plant_admin_headers": build_user_headers(PLANT_ADMIN_USER, "PlantAdmin"),
    "production_supervisor_headers": build_user_headers(
        PRODUCTION_SUPERVISOR_USER, "ProductionSupervisor"
    ),
    "qc_technician_headers": build_user_headers(QC_TECHNICIAN_USER, "QCTechnician"),
    "quality_engineer_headers": build_user_headers(QUALITY_ENGINEER_USER, "QualityEngineer"),
    "yard_foreman_headers": build_user_headers(YARD_FOREMAN_USER, "YardForeman"),
    "permit_coordinator_headers": build_user_headers(
        PERMIT_COORDINATOR_USER, "PermitCoordinator"
    ),
    # ProjectOwner has no shared constant that can ever pass an ownership check:
    # its X-User-ID must be a real Project id, so tests build it per instance.
    "project_owner_headers_unowned": build_user_headers("no-such-project", "ProjectOwner"),
}


def make_plant_admin_headers(user_id=PLANT_ADMIN_USER):
    return build_user_headers(user_id, "PlantAdmin")


def make_production_supervisor_headers(user_id=PRODUCTION_SUPERVISOR_USER):
    return build_user_headers(user_id, "ProductionSupervisor")


def make_qc_technician_headers(user_id=QC_TECHNICIAN_USER):
    return build_user_headers(user_id, "QCTechnician")


def make_quality_engineer_headers(user_id=QUALITY_ENGINEER_USER):
    return build_user_headers(user_id, "QualityEngineer")


def make_yard_foreman_headers(user_id=YARD_FOREMAN_USER):
    return build_user_headers(user_id, "YardForeman")


def make_permit_coordinator_headers(user_id=PERMIT_COORDINATOR_USER):
    return build_user_headers(user_id, "PermitCoordinator")


def make_project_owner_headers(project_id: str):
    """For ProjectOwner: X-User-ID is the id of the acting Project, so every
    ownership-gated call must pass the real Project id here."""
    return build_user_headers(project_id, "ProjectOwner")
