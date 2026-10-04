"""Pre-built role headers for every role in the PRD (PRD §2.1).

``X-User-ID`` is an opaque identifier with no entity row for ProgramAdmin,
Underwriter, CardholderService, Applicant and CoBrandIssuer, so the shared
constants are canonical for those roles. ``RetailPartnerAnalyst`` and
``Cardholder`` are entity-backed: their ``X-User-ID`` is the id of the acting
RetailPartner / Account, so ownership-gated calls MUST use the per-instance
builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "cardholder_service_headers": build_user_headers("test-service-1", "CardholderService"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "co_brand_issuer_headers": build_user_headers("test-cobrand-1", "CoBrandIssuer"),
}


def make_retail_partner_analyst_headers(partner_id: str) -> dict:
    """RetailPartnerAnalyst is entity_backed:RetailPartner — pass the real
    RetailPartner.id so ownership checks on partner-scoped resources match."""
    return build_user_headers(partner_id, "RetailPartnerAnalyst")


def make_cardholder_headers(account_id: str) -> dict:
    """Cardholder is entity_backed:Account — pass the real Account.id so the
    ownership check on the cardholder's own account matches."""
    return build_user_headers(account_id, "Cardholder")