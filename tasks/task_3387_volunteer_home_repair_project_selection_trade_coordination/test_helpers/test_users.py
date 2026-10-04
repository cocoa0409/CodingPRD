"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding differs by role:
  - Homeowner:    X-User-ID is the acting HomeownerApplication's id  -> per-instance builder
  - Volunteer:    X-User-ID is the acting Volunteer's id             -> per-instance builder
  - TradePartner: X-User-ID is the acting TradeContractor's id       -> per-instance builder
  - SponsorRep:   X-User-ID is the acting Sponsor's id               -> per-instance builder
  - PlatformAdmin / AffiliateStaff / Assessor / Anonymous: opaque operator
    identifiers, never compared to any entity id.

TEST_USERS entries for entity-backed roles are FALLBACKS for tests that never
exercise ownership (400/404 paths). Any ownership-gated call MUST use the
make_<role>_headers(entity_id) builder with the real entity id, or every
ownership check will reject the request.
"""

from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN_ID = "test-platform-admin-1"
AFFILIATE_STAFF_ID = "test-affiliate-staff-1"
ASSESSOR_ID = "test-assessor-1"
ANONYMOUS_ID = "anon-caller-1"

TEST_USERS = {
    # Opaque roles: canonical shared form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "affiliate_staff_headers": build_user_headers(AFFILIATE_STAFF_ID, "AffiliateStaff"),
    "assessor_headers": build_user_headers(ASSESSOR_ID, "Assessor"),
    "anonymous_headers": build_user_headers(ANONYMOUS_ID, "Anonymous"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "trade_partner_headers": build_user_headers("test-trade-partner-1", "TradePartner"),
    "sponsor_rep_headers": build_user_headers("test-sponsor-rep-1", "SponsorRep"),
}


# --- Per-instance builders (mandatory for entity-backed roles) ----------------

def make_homeowner_headers(application_id: str) -> dict:
    """Homeowner: X-User-ID must equal the owning HomeownerApplication's id."""
    return build_user_headers(application_id, "Homeowner")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Volunteer: X-User-ID must equal the acting Volunteer's id."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_trade_partner_headers(contractor_id: str) -> dict:
    """TradePartner: X-User-ID must equal the acting TradeContractor's id."""
    return build_user_headers(contractor_id, "TradePartner")


def make_sponsor_rep_headers(sponsor_id: str) -> dict:
    """SponsorRep: X-User-ID must equal the acting Sponsor's id."""
    return build_user_headers(sponsor_id, "SponsorRep")


# --- Opaque-role builders -------------------------------------------------------

def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_affiliate_staff_headers(user_id: str = AFFILIATE_STAFF_ID) -> dict:
    return build_user_headers(user_id, "AffiliateStaff")


def make_assessor_headers(user_id: str = ASSESSOR_ID) -> dict:
    return build_user_headers(user_id, "Assessor")


def make_anonymous_headers(user_id: str = ANONYMOUS_ID) -> dict:
    return build_user_headers(user_id, "Anonymous")
