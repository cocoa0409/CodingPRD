"""Pre-built role headers for every role in the PRD.

Three roles are entity-backed, meaning X-User-ID is the identifier of a persisted
record: `Producer` (a Producer id), `DeviceSupplierRep` (a DeviceSupplier id) and
`HarvestFacilityOperator` (the harvest Premises id). Any ownership-gated call for
those roles MUST use the matching per-instance builder below, never the shared
constant. The other three roles carry opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for entity-backed roles only
# in tests that never exercise an ownership check (bad payload, unknown resource,
# role-denial probes).
TEST_USERS = {
    # entity_backed roles — fallback identities for non-ownership tests only.
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
    "supplier_rep_headers": build_user_headers("test-supplier-rep-1", "DeviceSupplierRep"),
    "harvest_operator_headers": build_user_headers("test-harvest-1", "HarvestFacilityOperator"),
    # opaque roles — the shared constant is the canonical form.
    "state_official_headers": build_user_headers("saho-1", "StateAnimalHealthOfficial"),
    "second_state_official_headers": build_user_headers("saho-2", "StateAnimalHealthOfficial"),
    "trace_analyst_headers": build_user_headers("fta-1", "FederalTraceAnalyst"),
    "second_trace_analyst_headers": build_user_headers("fta-2", "FederalTraceAnalyst"),
    "program_admin_headers": build_user_headers("admin-reg", "ProgramAdmin"),
    "second_program_admin_headers": build_user_headers("admin-apr", "ProgramAdmin"),
}

# Canonical opaque operator identifiers used across fixtures and assertions.
REGISTERING_ADMIN_ID = "admin-reg"
APPROVING_ADMIN_ID = "admin-apr"
STATE_OFFICIAL_ID = "saho-1"
SECOND_STATE_OFFICIAL_ID = "saho-2"
OPENING_ANALYST_ID = "fta-1"
CLOSING_ANALYST_ID = "fta-2"


# --- Per-instance builders — mandatory for every entity-backed role ---------
def make_producer_headers(producer_id: str) -> dict:
    """For `Producer`: X-User-ID is the id of the acting Producer record."""
    return build_user_headers(producer_id, "Producer")


def make_supplier_rep_headers(supplier_id: str) -> dict:
    """For `DeviceSupplierRep`: X-User-ID is the id of the acting DeviceSupplier."""
    return build_user_headers(supplier_id, "DeviceSupplierRep")


def make_harvest_operator_headers(premises_id: str) -> dict:
    """For `HarvestFacilityOperator`: X-User-ID is the id of the harvest Premises."""
    return build_user_headers(premises_id, "HarvestFacilityOperator")


# --- Builders for the opaque roles (identity is a free operator handle) -----
def make_state_official_headers(user_id: str = STATE_OFFICIAL_ID) -> dict:
    return build_user_headers(user_id, "StateAnimalHealthOfficial")


def make_trace_analyst_headers(user_id: str = OPENING_ANALYST_ID) -> dict:
    return build_user_headers(user_id, "FederalTraceAnalyst")


def make_program_admin_headers(user_id: str = REGISTERING_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
