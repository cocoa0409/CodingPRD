"""Pre-built role headers for every role in the PRD.

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. Entity-backed roles (MerchantOwner, GuarantorPrincipal) MUST be
built per instance via the make_*_headers builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "servicer_agent_headers": build_user_headers("test-servicer-1", "ServicerAgent"),
    # Entity-backed roles: shared constant is a fallback for non-ownership tests only.
    "merchant_owner_headers": build_user_headers("test-merchant-owner-1", "MerchantOwner"),
    "guarantor_principal_headers": build_user_headers("test-guarantor-1", "GuarantorPrincipal"),
    "bank_officer_headers": build_user_headers("test-bank-officer-1", "BankOfficer"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_merchant_owner_headers(merchant_id: str) -> dict:
    """MerchantOwner is entity-backed: pass the acting Merchant.id whenever
    the call is ownership-gated (offer accept, disclosure acknowledge,
    catch-up initiation)."""
    return build_user_headers(merchant_id, "MerchantOwner")


def make_guarantor_principal_headers(guarantor_id: str) -> dict:
    """GuarantorPrincipal is entity-backed: pass the acting Guarantor.id
    whenever the call is ownership-gated (guarantee acknowledgment)."""
    return build_user_headers(guarantor_id, "GuarantorPrincipal")


def make_bank_officer_headers(user_id: str) -> dict:
    """BankOfficer is opaque; a distinct user id per operator is needed for
    the sale settle segregation-of-duties check."""
    return build_user_headers(user_id, "BankOfficer")
