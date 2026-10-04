"""Pre-built role headers for every role in the PRD.

A MemberRep's X-User-ID is the id of the Member it represents, so member-scoped
calls must always be built per instance with make_member_rep_headers(member_id).
"""
from prd_bench_local_runner.testing import build_user_headers

REGISTRY_ADMIN_1 = "admin-1"
QA_CREATOR = "qa-creator"
QA_SETTLER = "qa-settler"
QA_JUDGE = "qa-judge"
BORROWER_LINE = "borrower-line-1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "registry_admin_headers": build_user_headers(REGISTRY_ADMIN_1, "RegistryAdmin"),
    "qa_creator_headers": build_user_headers(QA_CREATOR, "QAAuditor"),
    "qa_settler_headers": build_user_headers(QA_SETTLER, "QAAuditor"),
    "qa_judge_headers": build_user_headers(QA_JUDGE, "QAAuditor"),
    "borrower_inquirer_headers": build_user_headers(BORROWER_LINE, "BorrowerInquirer"),
    # Entity-backed role: fallback only, never valid for member-scoped calls.
    "member_rep_headers": build_user_headers("member-unbound", "MemberRep"),
}


def make_registry_admin_headers(user_id: str = REGISTRY_ADMIN_1) -> dict:
    return build_user_headers(user_id, "RegistryAdmin")


def make_qa_auditor_headers(user_id: str = QA_CREATOR) -> dict:
    return build_user_headers(user_id, "QAAuditor")


def make_borrower_inquirer_headers(user_id: str = BORROWER_LINE) -> dict:
    return build_user_headers(user_id, "BorrowerInquirer")


def make_member_rep_headers(member_id: str) -> dict:
    """A MemberRep caller's X-User-ID is the Member's own id."""
    return build_user_headers(member_id, "MemberRep")


ALL_ROLES = ["RegistryAdmin", "MemberRep", "QAAuditor", "BorrowerInquirer"]
