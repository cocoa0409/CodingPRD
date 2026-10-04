"""Pre-built role headers for every role the PRD recognises.

Exactly one role is backed by a persisted entity. When ``X-User-Role`` is
``Member``, ``X-User-ID`` is the ``id`` of the acting ``Member``, and ownership
checks compare a resource's ``member_id`` to ``X-User-ID``. Every other role
carries an opaque operator identity that the server never compares to an
entity's id, so a shared constant is correct for those roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "attraction_host_headers": build_user_headers("test-attraction-host-1", "AttractionHost"),
    "events_coordinator_headers": build_user_headers(
        "test-events-coordinator-1", "EventsCoordinator"
    ),
    "deal_desk_clerk_headers": build_user_headers("test-deal-desk-clerk-1", "DealDeskClerk"),
    "service_writer_headers": build_user_headers("test-service-writer-1", "ServiceWriter"),
    "service_technician_headers": build_user_headers(
        "test-service-technician-1", "ServiceTechnician"
    ),
    "receiving_manager_headers": build_user_headers(
        "test-receiving-manager-1", "ReceivingManager"
    ),
    "permit_clerk_headers": build_user_headers("test-permit-clerk-1", "PermitClerk"),
    "remit_admin_headers": build_user_headers("test-remit-admin-1", "RemitAdmin"),
    "agency_operator_headers": build_user_headers("test-agency-operator-1", "AgencyOperator"),
    "title_clerk_headers": build_user_headers("test-title-clerk-1", "TitleClerk"),
    "credit_underwriter_headers": build_user_headers(
        "test-credit-underwriter-1", "CreditUnderwriter"
    ),
    "credit_officer_headers": build_user_headers("test-credit-officer-1", "CreditOfficer"),
    "club_card_specialist_headers": build_user_headers(
        "test-club-card-specialist-1", "ClubCardSpecialist"
    ),
    "finance_admin_headers": build_user_headers("test-finance-admin-1", "FinanceAdmin"),
    # Anonymous carries no header at all — the endpoints that admit it are
    # declared anonymous, so an empty header mapping is the canonical form.
    "anonymous_headers": {},
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
STORE_MANAGER = TEST_USERS["store_manager_headers"]
ATTRACTION_HOST = TEST_USERS["attraction_host_headers"]
EVENTS_COORDINATOR = TEST_USERS["events_coordinator_headers"]
DEAL_DESK_CLERK = TEST_USERS["deal_desk_clerk_headers"]
SERVICE_WRITER = TEST_USERS["service_writer_headers"]
SERVICE_TECHNICIAN = TEST_USERS["service_technician_headers"]
RECEIVING_MANAGER = TEST_USERS["receiving_manager_headers"]
PERMIT_CLERK = TEST_USERS["permit_clerk_headers"]
REMIT_ADMIN = TEST_USERS["remit_admin_headers"]
AGENCY_OPERATOR = TEST_USERS["agency_operator_headers"]
TITLE_CLERK = TEST_USERS["title_clerk_headers"]
CREDIT_UNDERWRITER = TEST_USERS["credit_underwriter_headers"]
CREDIT_OFFICER = TEST_USERS["credit_officer_headers"]
CLUB_CARD_SPECIALIST = TEST_USERS["club_card_specialist_headers"]
FINANCE_ADMIN = TEST_USERS["finance_admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def make_member_headers(member_id: str) -> dict:
    """Member is entity-backed: X-User-ID is the acting Member row id.

    Pass the actual Member.id whenever the call is ownership-gated (the member
    read, the member write, a member's own deals, intakes, fulfilments,
    registrations and club card applications).
    """
    return build_user_headers(member_id, "Member")


# Shared fallback for calls whose success does not depend on member ownership.
MEMBER_FALLBACK = build_user_headers("test-member-1", "Member")