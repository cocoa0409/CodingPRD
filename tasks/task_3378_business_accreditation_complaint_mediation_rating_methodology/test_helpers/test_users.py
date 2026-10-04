"""Pre-built role headers for the four roles of PRD §2.1.

BureauAdmin and StandardsReviewer are opaque roles: their X-User-ID is not
compared to any entity id, so the shared constants below are canonical.

BusinessRep and Consumer are entity-backed: X-User-ID must equal the acting
Business.id / Consumer.id on every ownership-gated operation (PRD §2.1).
Fixtures MUST build those headers with make_business_rep_headers(business_id)
/ make_consumer_headers(consumer_id) after creating the entity. The shared
constants for these two roles are fallbacks for tests whose outcome does not
depend on the caller owning the resource (e.g. 400-schema or 404 probes).
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "bureau_admin_headers": build_user_headers("test-bureau-admin-1",
                                               "BureauAdmin"),
    "standards_reviewer_headers": build_user_headers(
        "test-standards-reviewer-1", "StandardsReviewer"),
    # Entity-backed roles — fallback ONLY for non-ownership assertions.
    "business_rep_headers": build_user_headers("test-business-rep-1",
                                               "BusinessRep"),
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
}


def make_business_rep_headers(business_id: str) -> dict:
    """Headers for a BusinessRep acting as the given Business.

    PRD §2.1: "When X-User-Role is BusinessRep, X-User-ID is the id of the
    acting Business; ownership checks on any resource that references a
    Business compare the resource's business field to X-User-ID."
    """
    return build_user_headers(business_id, "BusinessRep")


def make_consumer_headers(consumer_id: str) -> dict:
    """Headers for a Consumer acting as the given Consumer.

    PRD §2.1: "When X-User-Role is Consumer, X-User-ID is the id of the
    acting Consumer; ownership checks compare the filing consumer's id ...
    to X-User-ID."
    """
    return build_user_headers(consumer_id, "Consumer")


def make_bureau_admin_headers(operator_id: str = "test-bureau-admin-1") -> dict:
    """Opaque-role headers; operator id is never compared to entity ids."""
    return build_user_headers(operator_id, "BureauAdmin")


def make_standards_reviewer_headers(
        reviewer_id: str = "test-standards-reviewer-1") -> dict:
    """Opaque-role headers; reviewer id is never compared to entity ids."""
    return build_user_headers(reviewer_id, "StandardsReviewer")
