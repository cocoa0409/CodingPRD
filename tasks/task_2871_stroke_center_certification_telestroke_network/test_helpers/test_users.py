"""Pre-built role headers for every role in the PRD (PRD 2.1).

Five of the six roles are opaque: their `X-User-ID` is an operator identifier
that is never compared to any entity's `id`, so a shared constant is the
canonical form for them.  `Neurologist` is the only entity-backed role - its
`X-User-ID` is the `id` of the acting Neurologist record - so ownership-gated
consult and determination calls MUST use make_neurologist_headers() with the
real neurologist id.

Two segregation-of-duties barriers (PRD 2.10) compare two opaque identifiers to
each other, so this module also exposes a second distinct identifier for the
QualityAbstractor and the CertificationReviewer/ProgramCoordinator pair.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.  Distinct owners get distinct ids.
ED_PHYSICIAN_USER_ID = "ed-physician-001"
ED_PHYSICIAN_ALT_USER_ID = "ed-physician-002"
TRANSFER_COORDINATOR_USER_ID = "transfer-coordinator-001"
QUALITY_ABSTRACTOR_USER_ID = "quality-abstractor-001"
QUALITY_ATTESTER_USER_ID = "quality-abstractor-002"
PROGRAM_COORDINATOR_USER_ID = "program-coordinator-001"
PROGRAM_COORDINATOR_ALT_USER_ID = "program-coordinator-002"
CERTIFICATION_REVIEWER_USER_ID = "certification-reviewer-001"
CERTIFICATION_REVIEWER_ALT_USER_ID = "certification-reviewer-002"

# Placeholder identifier for the entity-backed Neurologist role.  It is only
# safe on calls that do not exercise ownership (bad payload, missing record).
NEUROLOGIST_PLACEHOLDER_USER_ID = "neurologist-not-a-real-record"

TEST_USERS = {
    "ed_physician_headers": build_user_headers(ED_PHYSICIAN_USER_ID, "EdPhysician"),
    "ed_physician_alt_headers": build_user_headers(ED_PHYSICIAN_ALT_USER_ID, "EdPhysician"),
    "transfer_coordinator_headers": build_user_headers(
        TRANSFER_COORDINATOR_USER_ID, "TransferCoordinator"
    ),
    "quality_abstractor_headers": build_user_headers(
        QUALITY_ABSTRACTOR_USER_ID, "QualityAbstractor"
    ),
    "quality_attester_headers": build_user_headers(
        QUALITY_ATTESTER_USER_ID, "QualityAbstractor"
    ),
    "program_coordinator_headers": build_user_headers(
        PROGRAM_COORDINATOR_USER_ID, "ProgramCoordinator"
    ),
    "program_coordinator_alt_headers": build_user_headers(
        PROGRAM_COORDINATOR_ALT_USER_ID, "ProgramCoordinator"
    ),
    "certification_reviewer_headers": build_user_headers(
        CERTIFICATION_REVIEWER_USER_ID, "CertificationReviewer"
    ),
    "certification_reviewer_alt_headers": build_user_headers(
        CERTIFICATION_REVIEWER_ALT_USER_ID, "CertificationReviewer"
    ),
    # Fallback only - never use for an ownership-gated consult action.
    "neurologist_headers": build_user_headers(
        NEUROLOGIST_PLACEHOLDER_USER_ID, "Neurologist"
    ),
}


def make_neurologist_headers(neurologist_id: str) -> dict:
    """Headers for the entity-backed Neurologist role.

    Pass the actual Neurologist record's `id`: every consult lifecycle action
    and the checklist determination compare it to the consult's
    `assigned_neurologist_id`.
    """
    return build_user_headers(neurologist_id, "Neurologist")


def make_ed_physician_headers(user_id: str) -> dict:
    """Headers for an EdPhysician with a caller-chosen opaque operator id."""
    return build_user_headers(user_id, "EdPhysician")


def make_quality_abstractor_headers(user_id: str) -> dict:
    """Headers for a QualityAbstractor with a caller-chosen opaque operator id."""
    return build_user_headers(user_id, "QualityAbstractor")


def make_program_coordinator_headers(user_id: str) -> dict:
    """Headers for a ProgramCoordinator with a caller-chosen opaque operator id."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_certification_reviewer_headers(user_id: str) -> dict:
    """Headers for a CertificationReviewer with a caller-chosen opaque operator id."""
    return build_user_headers(user_id, "CertificationReviewer")


def make_transfer_coordinator_headers(user_id: str) -> dict:
    """Headers for a TransferCoordinator with a caller-chosen opaque operator id."""
    return build_user_headers(user_id, "TransferCoordinator")


# Convenience aliases used throughout the suite.
ED = TEST_USERS["ed_physician_headers"]
ED_ALT = TEST_USERS["ed_physician_alt_headers"]
COORD = TEST_USERS["program_coordinator_headers"]
COORD_ALT = TEST_USERS["program_coordinator_alt_headers"]
REVIEWER = TEST_USERS["certification_reviewer_headers"]
REVIEWER_ALT = TEST_USERS["certification_reviewer_alt_headers"]
ABSTRACTOR = TEST_USERS["quality_abstractor_headers"]
ATTESTER = TEST_USERS["quality_attester_headers"]
TRANSFER = TEST_USERS["transfer_coordinator_headers"]
