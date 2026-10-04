"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "company_rep_headers": build_user_headers("test-company-rep-1", "CompanyRep"),
    # opaque roles: shared constant is the canonical form.
    "house_manager_headers": build_user_headers("test-house-manager-1", "HouseManager"),
    "box_office_agent_headers": build_user_headers("test-box-office-1", "BoxOfficeAgent"),
}


def make_company_rep_headers(company_id: str) -> dict:
    """For CompanyRep (entity_backed: ProductionCompany). Pass the actual
    ProductionCompany.id as company_id whenever the call is ownership-gated."""
    return build_user_headers(company_id, "CompanyRep")


def make_house_manager_headers(user_id: str) -> dict:
    """HouseManager is opaque; any identifier works."""
    return build_user_headers(user_id, "HouseManager")


def make_box_office_agent_headers(user_id: str) -> dict:
    """BoxOfficeAgent is opaque; any identifier works."""
    return build_user_headers(user_id, "BoxOfficeAgent")
