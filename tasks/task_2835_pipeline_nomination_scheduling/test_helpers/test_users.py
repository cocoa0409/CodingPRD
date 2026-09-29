"""Pre-built role headers for every role in the PRD.

`Shipper` is the only role whose `X-User-ID` is compared to a persisted row's
`id` (PRD 2.1), so ownership-gated calls MUST use `make_shipper_headers()` with
the real Shipper id. The other three roles carry opaque operator identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    CERTIFIER_USER_ID,
    PUBLISHER_USER_ID,
    SECOND_CERTIFIER_USER_ID,
    TARIFF_ADMIN_USER_ID,
)

TEST_USERS = {
    # Shipper is entity-backed: this shared constant is a fallback for tests that
    # do NOT exercise ownership (401/400/404 shapes only).
    "shipper_headers": build_user_headers("test-shipper-1", "Shipper"),
    # The three opaque roles: the shared constant is the canonical form.
    "scheduler_headers": build_user_headers("test-scheduler-1", "PipelineScheduler"),
    "terminal_operator_headers": build_user_headers(
        "test-terminal-operator-1", "TerminalOperator"
    ),
    "tariff_administrator_headers": build_user_headers(
        "test-tariff-admin-1", "TariffAdministrator"
    ),
    # Named scheduler identities for the duty-separation chain (PRD 2.10).
    "publisher_headers": build_user_headers(PUBLISHER_USER_ID, "PipelineScheduler"),
    "certifier_headers": build_user_headers(CERTIFIER_USER_ID, "PipelineScheduler"),
    "second_certifier_headers": build_user_headers(
        SECOND_CERTIFIER_USER_ID, "PipelineScheduler"
    ),
    "invoicer_headers": build_user_headers(TARIFF_ADMIN_USER_ID, "TariffAdministrator"),
}


def make_shipper_headers(user_id: str) -> dict:
    """Headers for the `Shipper` role.

    PRD 2.1: "When `X-User-Role` is `Shipper`, `X-User-ID` is the `id` of the
    acting `Shipper` row". Pass the real Shipper id whenever the call is
    ownership-gated.
    """
    return build_user_headers(user_id, "Shipper")


def make_scheduler_headers(user_id: str) -> dict:
    """Headers for `PipelineScheduler` under a chosen opaque operator id."""
    return build_user_headers(user_id, "PipelineScheduler")


def make_terminal_operator_headers(user_id: str) -> dict:
    """Headers for `TerminalOperator` under a chosen opaque operator id."""
    return build_user_headers(user_id, "TerminalOperator")


def make_tariff_administrator_headers(user_id: str) -> dict:
    """Headers for `TariffAdministrator` under a chosen opaque operator id."""
    return build_user_headers(user_id, "TariffAdministrator")


# Convenient module-level aliases used throughout the fixtures.
SHIPPER = TEST_USERS["shipper_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
OPERATOR = TEST_USERS["terminal_operator_headers"]
ADMIN = TEST_USERS["tariff_administrator_headers"]
PUBLISHER = TEST_USERS["publisher_headers"]
CERTIFIER = TEST_USERS["certifier_headers"]
SECOND_CERTIFIER = TEST_USERS["second_certifier_headers"]
INVOICER = TEST_USERS["invoicer_headers"]

# Headers with no role at all, for the authentication rank of the refusal ladder.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
