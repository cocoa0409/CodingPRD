"""Pre-built header dicts, one per acting operator.

The PRD states: "Every request - without exception, including reads - must
carry two headers: `X-User-ID`, identifying the acting operator, and
`X-User-Role`, naming the role that operator is acting in."

Distinct operators are given distinct `X-User-ID` values so that the three
segregation-of-duties pairs of PRD 2.9 can be exercised in both directions.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AUTHORIZED_INSPECTOR,
    ROLE_CIVIL_CONTRACTOR,
    ROLE_ERECTION_SUPERINTENDENT,
    ROLE_PROJECT_ENGINEER,
    ROLE_QC_INSPECTOR,
    ROLE_WELDER,
)

# --- Opaque operator identifiers (PRD 2.1) -----------------------------
PE1_ID = "pe-1"
PE2_ID = "pe-2"
CC1_ID = "cc-1"
ES1_ID = "es-1"
QC1_ID = "qc-1"
QC2_ID = "qc-2"
AI1_ID = "ai-1"
AI2_ID = "ai-2"
AI3_ID = "ai-3"
AI9_ID = "ai-9"

# --- Header sets -------------------------------------------------------
# ProjectEngineer: tank design, courses, water sources, plans and approval,
# coating specs, appurtenance design, the commissioning path, and the
# foundation accept-or-reject decision.
PE1 = build_user_headers(PE1_ID, ROLE_PROJECT_ENGINEER)
PE2 = build_user_headers(PE2_ID, ROLE_PROJECT_ENGINEER)

# CivilContractor: foundation package registration and settlement surveys.
CC1 = build_user_headers(CC1_ID, ROLE_CIVIL_CONTRACTOR)

# ErectionSuperintendent: plate lots, allocation, fit-up, seam declaration,
# repair start, withdrawal reservation and cancellation, fill advance,
# appurtenance installation.
ES1 = build_user_headers(ES1_ID, ROLE_ERECTION_SUPERINTENDENT)

# QcInspector: NDE scheduling and results, and every coating quality step.
# QC1 must differ from AI1 so that an examination result reported by QC1 on a
# welder qualified by AI1 does not collide under PRD 2.9.
QC1 = build_user_headers(QC1_ID, ROLE_QC_INSPECTOR)
QC2 = build_user_headers(QC2_ID, ROLE_QC_INSPECTOR)

# The qualifying inspector acting in the QcInspector role: used to prove the
# segregation-of-duties collision on an examination result.
QC_AS_AI1 = build_user_headers(AI1_ID, ROLE_QC_INSPECTOR)

# AuthorizedInspector: welder qualification, report voiding, hydrotest
# completion, commissioning review.
# AI1 qualifies welders. AI2 records hydrotest completion and voids reports.
# AI3 reviews commissioning packages (PE1 submits them).
AI1 = build_user_headers(AI1_ID, ROLE_AUTHORIZED_INSPECTOR)
AI2 = build_user_headers(AI2_ID, ROLE_AUTHORIZED_INSPECTOR)
AI3 = build_user_headers(AI3_ID, ROLE_AUTHORIZED_INSPECTOR)
AI9 = build_user_headers(AI9_ID, ROLE_AUTHORIZED_INSPECTOR)

# The plan approver acting in the AuthorizedInspector role: used to prove the
# segregation-of-duties collision on a hydrotest completion decision.
AI_AS_PE1 = build_user_headers(PE1_ID, ROLE_AUTHORIZED_INSPECTOR)


def welder_headers(welder_id: str) -> dict:
    """Headers for the Welder role, whose X-User-ID is the Welder row's own id.

    The PRD states: "When `X-User-Role` is `Welder`, `X-User-ID` is the `id` of
    the acting `Welder` row".
    """
    return build_user_headers(welder_id, ROLE_WELDER)


def headers_for_role(user_id: str, role: str) -> dict:
    """Arbitrary operator/role pair, for role-authorisation probes."""
    return build_user_headers(user_id, role)


# --- Deliberately malformed header sets --------------------------------
# "If either header is absent, or is present but holds an empty string, the
# request is rejected with ERR_UNAUTHENTICATED".
#
# Blank here means the literal empty string, never a whitespace-only value:
# some HTTP clients drop a whitespace-only header instead of sending it, which
# would turn a blank-value probe into an absent-header probe by accident.
BLANK_USER_ID = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PROJECT_ENGINEER,
    "Content-Type": "application/json",
}

BLANK_USER_ROLE = {
    "X-User-ID": PE1_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

MISSING_USER_ID = {
    "X-User-Role": ROLE_PROJECT_ENGINEER,
    "Content-Type": "application/json",
}

MISSING_USER_ROLE = {
    "X-User-ID": PE1_ID,
    "Content-Type": "application/json",
}

NO_HEADERS = {"Content-Type": "application/json"}
