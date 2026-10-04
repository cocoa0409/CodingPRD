"""Caller identities for the fifteen roles (PRD §2.1).

Thirteen roles are opaque operator identities: any stable token works, so this
module hands out pre-built header dicts for them in TEST_USERS.

Two roles are entity-backed and CANNOT be shared constants on ownership-gated
calls:
  * Docent — `X-User-ID` must be the `id` of the acting Docent (confirming an
    assignment compares it to `assignment.docent_id`),
  * Member — `X-User-ID` must be the `id` of the acting Member (a member-priced
    purchase requires `member_id == X-User-ID`; holder-cancel compares against
    the pass's `holder_member_id`).
Fixtures MUST call `make_docent_headers(docent["id"])` /
`make_member_headers(member["id"])` for those. The TEST_USERS entries for the
two entity-backed roles exist only for probes where ownership is irrelevant.

Ownership is keyed on `X-User-ID` even for opaque roles where the PRD says so:
a Public caller cancels only passes/reservations they created (the response
records `created_by_user_id`), a Curator submits only their own review, and
segregation of duties requires the deciding chair's `X-User-ID` to differ from
the review's `submitted_by_user_id` — hence every role also has a
`make_<role>_headers(user_id)` builder, and Curator / CommitteeChair / Public /
Scholar get second named constants for two-person scenarios.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

Headers = Dict[str, str]

# ── Default opaque identities ────────────────────────────────────────────────
PLATFORM_ADMIN_USER_ID = "admin-1"
VISITOR_SERVICES_USER_ID = "vservices-1"
SECURITY_SCREENER_USER_ID = "screener-1"
EXHIBITION_MANAGER_USER_ID = "exh-manager-1"
PROGRAM_COORDINATOR_USER_ID = "coordinator-1"
PUBLIC_USER_ID = "visitor-1"
LOANS_OFFICER_USER_ID = "loans-1"
BORROWER_REP_USER_ID = "borrower-1"
REGISTRAR_USER_ID = "registrar-1"
CURATOR_USER_ID = "cur-1"
COMMITTEE_CHAIR_USER_ID = "chair-1"
FINANCE_OFFICER_USER_ID = "finance-1"
SCHOLAR_USER_ID = "scholar-1"

# Second identities, for scenarios needing two distinct callers of one role —
# most importantly segregation of duties, where the chair's X-User-ID must
# differ from the submitting curator's X-User-ID.
PUBLIC_2_USER_ID = "visitor-2"
CURATOR_2_USER_ID = "cur-2"
COMMITTEE_CHAIR_2_USER_ID = "chair-2"
SCHOLAR_2_USER_ID = "scholar-2"

# A syntactically valid id that owns nothing, for ownership probes that need a
# caller whose X-User-ID matches no recorded creator / holder / docent.
UNREGISTERED_USER_ID = "00000000-0000-4000-8000-000000000000"


# ── Per-role header builders (required for every role) ───────────────────────
def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_visitor_services_headers(user_id: str = VISITOR_SERVICES_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.VISITOR_SERVICES.value)


def make_security_screener_headers(user_id: str = SECURITY_SCREENER_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.SECURITY_SCREENER.value)


def make_exhibition_manager_headers(user_id: str = EXHIBITION_MANAGER_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.EXHIBITION_MANAGER.value)


def make_program_coordinator_headers(user_id: str = PROGRAM_COORDINATOR_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.PROGRAM_COORDINATOR.value)


def make_docent_headers(user_id: str) -> Headers:
    """Docent is entity-backed: pass the acting Docent's id whenever the call
    is ownership-gated (confirming an assignment always is)."""
    return build_user_headers(user_id, UserRole.DOCENT.value)


def make_public_headers(user_id: str = PUBLIC_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.PUBLIC.value)


def make_member_headers(user_id: str) -> Headers:
    """Member is entity-backed: pass the acting Member's id whenever the call
    is ownership-gated (member-priced purchase, holder-cancel, self-read)."""
    return build_user_headers(user_id, UserRole.MEMBER.value)


def make_loans_officer_headers(user_id: str = LOANS_OFFICER_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.LOANS_OFFICER.value)


def make_borrower_rep_headers(user_id: str = BORROWER_REP_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.BORROWER_REP.value)


def make_registrar_headers(user_id: str = REGISTRAR_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.REGISTRAR.value)


def make_curator_headers(user_id: str = CURATOR_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.CURATOR.value)


def make_committee_chair_headers(user_id: str = COMMITTEE_CHAIR_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.COMMITTEE_CHAIR.value)


def make_finance_officer_headers(user_id: str = FINANCE_OFFICER_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.FINANCE_OFFICER.value)


def make_scholar_headers(user_id: str = SCHOLAR_USER_ID) -> Headers:
    return build_user_headers(user_id, UserRole.SCHOLAR.value)


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary caller, for probes needing an unusual pairing."""
    return build_user_headers(user_id, role)


# ── Shared constants: default identity per role ──────────────────────────────
# Safe for 400/404/role-denial probes and for opaque-role business calls whose
# success does not depend on owning the subject resource. For ownership-gated
# calls build headers from the resource's recorded id instead.
TEST_USERS: Dict[str, Headers] = {
    "platform_admin_headers": make_platform_admin_headers(),
    "visitor_services_headers": make_visitor_services_headers(),
    "security_screener_headers": make_security_screener_headers(),
    "exhibition_manager_headers": make_exhibition_manager_headers(),
    "program_coordinator_headers": make_program_coordinator_headers(),
    # Fallback only — never use for confirm/ownership calls.
    "docent_headers": make_docent_headers(UNREGISTERED_USER_ID),
    "public_headers": make_public_headers(),
    # Fallback only — never use for member-priced purchase/ownership calls.
    "member_headers": make_member_headers(UNREGISTERED_USER_ID),
    "loans_officer_headers": make_loans_officer_headers(),
    "borrower_rep_headers": make_borrower_rep_headers(),
    "registrar_headers": make_registrar_headers(),
    "curator_headers": make_curator_headers(),
    "committee_chair_headers": make_committee_chair_headers(),
    "finance_officer_headers": make_finance_officer_headers(),
    "scholar_headers": make_scholar_headers(),
    # Second identities for two-person scenarios.
    "public_2_headers": make_public_headers(PUBLIC_2_USER_ID),
    "curator_2_headers": make_curator_headers(CURATOR_2_USER_ID),
    "committee_chair_2_headers": make_committee_chair_headers(COMMITTEE_CHAIR_2_USER_ID),
    "scholar_2_headers": make_scholar_headers(SCHOLAR_2_USER_ID),
}

# An empty header block: probes of the authentication gate (PRD §2.1) send no
# identity headers at all.
NO_HEADERS: Headers = {}
