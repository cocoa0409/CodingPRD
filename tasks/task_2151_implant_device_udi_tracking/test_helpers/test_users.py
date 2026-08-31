"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque identity: any non-empty string is
accepted for `X-User-ID` and is recorded verbatim into the actor fields, so a
shared constant is always safe for them.  The sixth role, `VendorRep`, is
entity-backed: its `X-User-ID` must be the `id` of an existing vendor, so
callers MUST build its headers per-instance with `make_vendor_rep_headers()`.
"""

from prd_bench_local_runner.testing import build_user_headers

# ─── Opaque operator identities ────────────────────────────────────────────
# Two distinct ids exist per operational role so the three separations of duty
# can be satisfied without switching roles.
RECEIVING_TECH_1 = "rt-01"
RECEIVING_TECH_2 = "rt-02"
INVENTORY_LEAD_1 = "il-01"
INVENTORY_LEAD_2 = "il-02"
CIRC_CLINICIAN_1 = "cc-01"
CIRC_CLINICIAN_2 = "cc-02"
COMPLIANCE_OFFICER_1 = "co-01"
COMPLIANCE_OFFICER_2 = "co-02"
REVENUE_ANALYST_1 = "ri-01"
REVENUE_ANALYST_2 = "ri-02"


TEST_USERS = {
    "receiving_tech_headers": build_user_headers(RECEIVING_TECH_1, "ReceivingTech"),
    "receiving_tech_2_headers": build_user_headers(RECEIVING_TECH_2, "ReceivingTech"),
    "inventory_lead_headers": build_user_headers(INVENTORY_LEAD_1, "InventoryLead"),
    "inventory_lead_2_headers": build_user_headers(INVENTORY_LEAD_2, "InventoryLead"),
    "circ_clinician_headers": build_user_headers(CIRC_CLINICIAN_1, "CircClinician"),
    "circ_clinician_2_headers": build_user_headers(CIRC_CLINICIAN_2, "CircClinician"),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_1, "ComplianceOfficer"
    ),
    "compliance_officer_2_headers": build_user_headers(
        COMPLIANCE_OFFICER_2, "ComplianceOfficer"
    ),
    "revenue_analyst_headers": build_user_headers(
        REVENUE_ANALYST_1, "RevenueIntegrityAnalyst"
    ),
    "revenue_analyst_2_headers": build_user_headers(
        REVENUE_ANALYST_2, "RevenueIntegrityAnalyst"
    ),
}

# Convenience aliases used throughout the fixtures and the test suite.
RT = TEST_USERS["receiving_tech_headers"]
RT2 = TEST_USERS["receiving_tech_2_headers"]
IL = TEST_USERS["inventory_lead_headers"]
IL2 = TEST_USERS["inventory_lead_2_headers"]
CC = TEST_USERS["circ_clinician_headers"]
CC2 = TEST_USERS["circ_clinician_2_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
RI = TEST_USERS["revenue_analyst_headers"]
RI2 = TEST_USERS["revenue_analyst_2_headers"]


# ─── Per-instance builders ────────────────────────────────────────────────

def make_vendor_rep_headers(vendor_id: str) -> dict:
    """Headers for a `VendorRep`.

    `VendorRep` is entity-backed: `X-User-ID` must be the id of an existing
    vendor, and ownership checks compare a resource's vendor foreign key
    against it.  Always pass the real `Vendor.id`.
    """
    return build_user_headers(vendor_id, "VendorRep")


def make_receiving_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReceivingTech")


def make_inventory_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InventoryLead")


def make_circ_clinician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CircClinician")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_revenue_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RevenueIntegrityAnalyst")
