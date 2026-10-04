"""Pre-built role headers for every role of the agency.

`ManagingDirector`, `DistrictDirector` and `FinancialRep` are Adviser-backed:
their `X-User-ID` names an `Advisor` row, and ownership-scoped operations
compare an entity's advisor foreign key to it. Use the matching
`make_<role>_headers(advisor_id)` builder for those roles whenever the call
is ownership-gated.

`PlatformAdmin`, `RecruitingOfficer`, `LicensingCoordinator` and `Any` carry
an opaque operator identifier that is never compared to a persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # ManagingDirector — adviser-backed; this constant is only for calls that
    # are not ownership-scoped.
    "managing_director_headers": build_user_headers("test-managing-director-1", "ManagingDirector"),
    # DistrictDirector — adviser-backed.
    "district_director_headers": build_user_headers("test-district-director-1", "DistrictDirector"),
    # FinancialRep — adviser-backed.
    "financial_rep_headers": build_user_headers("test-financial-rep-1", "FinancialRep"),
    # Opaque operators.
    "recruiting_officer_headers": build_user_headers("test-recruiting-officer-1", "RecruitingOfficer"),
    "licensing_coordinator_headers": build_user_headers("test-licensing-coordinator-1", "LicensingCoordinator"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


# --- Per-instance builders for the adviser-backed roles --------------------

def make_managing_director_headers(advisor_id: str) -> dict:
    """ManagingDirector headers whose authority is carried by `advisor_id`."""
    return build_user_headers(advisor_id, "ManagingDirector")


def make_district_director_headers(advisor_id: str) -> dict:
    """DistrictDirector headers whose authority is carried by `advisor_id`."""
    return build_user_headers(advisor_id, "DistrictDirector")


def make_financial_rep_headers(advisor_id: str) -> dict:
    """FinancialRep headers for the advisor `advisor_id`.

    Mandatory for ownership-scoped calls such as submitting a joint work case
    (X-User-ID must equal the case's lead_advisor_id) or disputing a persistency
    record (X-User-ID must equal the record's advisor_id).
    """
    return build_user_headers(advisor_id, "FinancialRep")


# Convenience aliases used throughout the fixtures and tests.
md_headers = TEST_USERS["managing_director_headers"]
dd_headers = TEST_USERS["district_director_headers"]
rep_headers = TEST_USERS["financial_rep_headers"]
ro_headers = TEST_USERS["recruiting_officer_headers"]
lc_headers = TEST_USERS["licensing_coordinator_headers"]
admin_headers = TEST_USERS["platform_admin_headers"]
any_headers = TEST_USERS["any_headers"]