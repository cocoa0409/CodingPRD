"""Pre-built role headers for every role in the PRD.

Five roles carry opaque identity: their X-User-ID is an operator identifier
that is never compared against any row's id, so a shared constant is the
canonical form. Three roles are entity-backed (Reader, Writer,
CommitteeMember): their X-User-ID must be the id of the acting row, so
every ownership-gated call MUST use the matching per-instance builder.
"""

from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator identifiers. Segregation of duties requires two
# different people for coverage approval, milestone payment and greenlight
# ballots, so the story-editor and business-affairs desks each get two.
EDITOR_ASSIGN_USER_ID = "editor-assign-1"
EDITOR_APPROVE_USER_ID = "editor-approve-1"
BA_APPROVER_USER_ID = "ba-approver-1"
BA_PAYER_USER_ID = "ba-payer-1"
EXEC_ALPHA_USER_ID = "exec-alpha"
EXEC_BETA_USER_ID = "exec-beta"
ADMIN_USER_ID = "admin-1"
SUBMITTER_USER_ID = "submitter-1"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "slate_admin_headers": build_user_headers(ADMIN_USER_ID, "SlateAdmin"),
    "story_editor_headers": build_user_headers(EDITOR_ASSIGN_USER_ID, "StoryEditor"),
    "story_editor_approver_headers": build_user_headers(
        EDITOR_APPROVE_USER_ID, "StoryEditor"
    ),
    "submitter_headers": build_user_headers(SUBMITTER_USER_ID, "Submitter"),
    "business_affairs_headers": build_user_headers(
        BA_APPROVER_USER_ID, "BusinessAffairs"
    ),
    "business_affairs_payer_headers": build_user_headers(
        BA_PAYER_USER_ID, "BusinessAffairs"
    ),
    "development_exec_headers": build_user_headers(
        EXEC_ALPHA_USER_ID, "DevelopmentExec"
    ),
    # Entity-backed roles — these shared constants are only safe for calls that
    # do not exercise ownership (400-on-bad-payload, 404-on-missing-resource).
    "reader_headers": build_user_headers("test-reader-1", "Reader"),
    "writer_headers": build_user_headers("test-writer-1", "Writer"),
    "committee_member_headers": build_user_headers(
        "test-member-1", "CommitteeMember"
    ),
}


# ---- Opaque-role builders (any operator id) --------------------------------


def make_slate_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "SlateAdmin")


def make_story_editor_headers(user_id: str = EDITOR_ASSIGN_USER_ID) -> dict:
    return build_user_headers(user_id, "StoryEditor")


def make_submitter_headers(user_id: str = SUBMITTER_USER_ID) -> dict:
    return build_user_headers(user_id, "Submitter")


def make_business_affairs_headers(user_id: str = BA_APPROVER_USER_ID) -> dict:
    return build_user_headers(user_id, "BusinessAffairs")


def make_development_exec_headers(user_id: str = EXEC_ALPHA_USER_ID) -> dict:
    return build_user_headers(user_id, "DevelopmentExec")


# ---- Entity-backed builders (mandatory for ownership-gated calls) ----------


def make_reader_headers(reader_id: str) -> dict:
    """For the Reader role. Pass the acting Reader row's id as reader_id."""
    return build_user_headers(reader_id, "Reader")


def make_writer_headers(writer_id: str) -> dict:
    """For the Writer role. Pass the acting Writer row's id as writer_id."""
    return build_user_headers(writer_id, "Writer")


def make_committee_member_headers(member_id: str) -> dict:
    """For the CommitteeMember role. Pass the acting seat's id as member_id."""
    return build_user_headers(member_id, "CommitteeMember")


# Convenient aliases used throughout the suite.
ADMIN = TEST_USERS["slate_admin_headers"]
EDITOR_ASSIGN = TEST_USERS["story_editor_headers"]
EDITOR_APPROVE = TEST_USERS["story_editor_approver_headers"]
SUBMITTER = TEST_USERS["submitter_headers"]
BA_APPROVER = TEST_USERS["business_affairs_headers"]
BA_PAYER = TEST_USERS["business_affairs_payer_headers"]
EXEC_ALPHA = TEST_USERS["development_exec_headers"]
EXEC_BETA = make_development_exec_headers(EXEC_BETA_USER_ID)
