"""Caller identities for the four declared roles.

Per PRD Section 2.1, every request carries ``X-User-ID`` and ``X-User-Role``.
Three roles are opaque operator identities (ProgramOps, SponsorBankOps,
DisputesAgent) whose ``X-User-ID`` is never matched against any persisted
entity; a stable shared header set is enough for them.

The Member role is entity-backed: its ``X-User-ID`` must equal the ``id`` of
the Member record that owns the resource being touched, so ownership-gated
calls must use ``make_member_headers(member_id)`` with the real member id.
The shared ``TEST_USERS["member"]`` entry is only for calls where ownership
is irrelevant to the assertion (for example a forbidden-call probe that never
reaches the ownership check).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

ROLE_MEMBER = UserRole.MEMBER.value
ROLE_PROGRAM_OPS = UserRole.PROGRAM_OPS.value
ROLE_SPONSOR_BANK_OPS = UserRole.SPONSOR_BANK_OPS.value
ROLE_DISPUTES_AGENT = UserRole.DISPUTES_AGENT.value

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque operator identities; the server never compares these to entities.
    "program_ops": build_user_headers("ops-program-1", ROLE_PROGRAM_OPS),
    "sponsor_bank_ops": build_user_headers("ops-bank-1", ROLE_SPONSOR_BANK_OPS),
    "disputes_agent": build_user_headers("ops-disputes-1", ROLE_DISPUTES_AGENT),
    # Fallback for Member calls whose assertion does not depend on ownership.
    "member": build_user_headers("test-member-1", ROLE_MEMBER),
}


def make_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for the entity-backed Member role.

    ``member_id`` must be the real ``id`` of the Member record owning the
    resource under the path; the server compares ``X-User-ID`` to the owning
    member and rejects a mismatch with ERR_FORBIDDEN.
    """
    return build_user_headers(member_id, ROLE_MEMBER)
