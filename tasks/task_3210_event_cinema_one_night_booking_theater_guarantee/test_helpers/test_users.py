"""Pre-built role headers for every role in the PRD (PRD §2.1).

PlatformOps, ProgrammingManager, FinanceOps and ContentOfficer present opaque
operator identifiers never matched against a stored entity. Distributor,
Exhibitor and Theater are entity_backed — their X-User-ID must equal the id of
an existing Distributor / Circuit / Theater row, so any ownership-gated call
MUST use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity_backed roles only on
# calls that do not exercise ownership.
TEST_USERS = {
    "platform_ops_headers": build_user_headers("test-platform-ops-1", "PlatformOps"),
    # A second, distinct platform operator. PRD §2.12 enforces separation of duties
    # on feed-failure confirmation: the operator who confirms must differ from the
    # operator who filed the event. Fixtures that file an event and then confirm it
    # must therefore use two different operator identities.
    "platform_ops_headers_2": build_user_headers("test-platform-ops-2", "PlatformOps"),
    "programming_manager_headers": build_user_headers("test-programming-mgr-1",
                                                      "ProgrammingManager"),
    "finance_ops_headers": build_user_headers("test-finance-ops-1", "FinanceOps"),
    "content_officer_headers": build_user_headers("test-content-officer-1",
                                                  "ContentOfficer"),
    # entity_backed fallbacks — non-ownership calls only.
    "distributor_headers": build_user_headers("test-distributor-1", "Distributor"),
    "exhibitor_headers": build_user_headers("test-exhibitor-1", "Exhibitor"),
    "theater_headers": build_user_headers("test-theater-1", "Theater"),
}


def make_distributor_headers(distributor_id: str) -> dict:
    """For the Distributor role (entity_backed:Distributor). Pass the actual
    Distributor.id whenever the call is ownership-gated."""
    return build_user_headers(distributor_id, "Distributor")


def make_exhibitor_headers(circuit_id: str) -> dict:
    """For the Exhibitor role (entity_backed:Circuit). Pass the actual
    Circuit.id whenever the call is ownership-gated."""
    return build_user_headers(circuit_id, "Exhibitor")


def make_theater_headers(theater_id: str) -> dict:
    """For the Theater role (entity_backed:Theater). Pass the actual
    Theater.id whenever the call is ownership-gated."""
    return build_user_headers(theater_id, "Theater")