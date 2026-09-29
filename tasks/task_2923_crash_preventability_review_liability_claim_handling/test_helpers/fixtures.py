"""Composite state builders and the pytest fixtures shared by the suite.

Every builder here reaches the state it names exclusively through public
endpoints, because each test runs against an empty database.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.constants import (
    CLOCK_EPOCH,
    LAYER_KIND_EXCESS,
    LAYER_KIND_PRIMARY,
    LAYER_KIND_SIR,
    OPERATOR_IDS,
    REQUIRED_EVIDENCE_KINDS,
    SEVERITY_MINOR,
)
from test_helpers.test_users import (
    make_auditor_headers,
    make_claims_adjuster_headers,
    make_claims_manager_headers,
    make_committee_member_headers,
    make_dispatcher_headers,
    make_driver_headers,
    make_safety_admin_headers,
    make_safety_manager_headers,
)

Json = Dict[str, Any]

# Header shorthands used by the builders below.
SAFETY_ADMIN = make_safety_admin_headers()
DISPATCHER = make_dispatcher_headers()
SAFETY_MANAGER = make_safety_manager_headers(OPERATOR_IDS["safety_manager_decider"])
APPEALS_MANAGER = make_safety_manager_headers(OPERATOR_IDS["safety_manager_appeals"])
COMMITTEE_ONE = make_committee_member_headers(OPERATOR_IDS["committee_member_one"])
COMMITTEE_TWO = make_committee_member_headers(OPERATOR_IDS["committee_member_two"])
COMMITTEE_THREE = make_committee_member_headers(OPERATOR_IDS["committee_member_three"])
CLAIMS_ADJUSTER = make_claims_adjuster_headers()
CLAIMS_MANAGER = make_claims_manager_headers()
AUDITOR = make_auditor_headers()

COMMITTEE_HEADERS = (COMMITTEE_ONE, COMMITTEE_TWO, COMMITTEE_THREE)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> Json:
    """Move the logical clock to the given instant."""
    return get_success_data(
        api.set_current_utc(factories.clock_payload(current_utc), SAFETY_ADMIN)
    )


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------


def build_terminal(api: ApiClient, **kwargs: Any) -> Json:
    return get_success_data(api.create_terminal(factories.terminal_payload(**kwargs), SAFETY_ADMIN))


def build_driver(api: ApiClient, terminal_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_driver(factories.driver_payload(terminal_id, **kwargs), SAFETY_ADMIN)
    )


def build_crash(api: ApiClient, driver_id: str, terminal_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_crash(factories.crash_payload(driver_id, terminal_id, **kwargs), DISPATCHER)
    )


def build_statement(api: ApiClient, crash_id: str, driver_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_driver_statement(
            crash_id,
            factories.driver_statement_payload(**kwargs),
            make_driver_headers(driver_id),
        )
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def request_evidence(api: ApiClient, crash_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_evidence_item(crash_id, factories.evidence_payload(**kwargs), DISPATCHER)
    )


def preserve_evidence(api: ApiClient, evidence_item_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.preserve_evidence_item(
            evidence_item_id, factories.preserve_payload(**kwargs), DISPATCHER
        )
    )


def build_preserved_evidence(api: ApiClient, crash_id: str, **kwargs: Any) -> Json:
    """Request an artifact and immediately preserve it."""
    requested = request_evidence(api, crash_id, **kwargs)
    return preserve_evidence(api, requested["id"])


def purge_evidence(api: ApiClient, evidence_item_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.purge_evidence_item(
            evidence_item_id, factories.purge_payload(**kwargs), SAFETY_ADMIN
        )
    )


def bracketing_window(occurred_at: str) -> Dict[str, str]:
    """A window that brackets the crash instant, opening one hour before it."""
    from test_helpers.assertions import shift_instant

    return {
        "window_start_at": shift_instant(occurred_at, hours=-1),
        "window_end_at": shift_instant(occurred_at, hours=1),
    }


def build_complete_posture(
    api: ApiClient, crash: Json, severity: Optional[str] = None
) -> List[Json]:
    """Preserve one bracketing artifact of every kind the severity requires."""
    window = bracketing_window(crash["occurred_at"])
    kinds = REQUIRED_EVIDENCE_KINDS[severity or crash["severity"]]
    preserved = []
    for index, kind in enumerate(kinds):
        preserved.append(
            build_preserved_evidence(
                api,
                crash["id"],
                kind=kind,
                source_device_id=f"DEV-{index + 1:03d}",
                **window,
            )
        )
    return preserved


# ---------------------------------------------------------------------------
# Review cases
# ---------------------------------------------------------------------------


def build_review_case(api: ApiClient, crash_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_review_case(factories.review_case_payload(crash_id, **kwargs), SAFETY_MANAGER)
    )


def open_deliberation(api: ApiClient, review_case_id: str) -> Json:
    return get_success_data(api.open_deliberation(review_case_id, headers=SAFETY_MANAGER))


def build_case_in_deliberation(api: ApiClient, crash_id: str, **kwargs: Any) -> Json:
    case = build_review_case(api, crash_id, **kwargs)
    return open_deliberation(api, case["id"])


def cast_ballot(
    api: ApiClient,
    review_case_id: str,
    expected_version: int,
    headers: Json,
    vote: str,
    scores: Optional[Json] = None,
    **kwargs: Any,
) -> Json:
    """Cast one ballot and return the updated review case."""
    return get_success_data(
        api.cast_vote(
            review_case_id,
            factories.vote_payload(expected_version, vote=vote, scores=scores, **kwargs),
            headers,
        )
    )


def cast_quorum(
    api: ApiClient,
    case: Json,
    vote: str,
    scores: Optional[Json] = None,
    members: Sequence[Json] = COMMITTEE_HEADERS,
) -> Json:
    """Cast one ballot per member, chaining the observed version each time."""
    current = case
    for headers in members:
        current = cast_ballot(
            api, case["id"], current["version"], headers, vote=vote, scores=scores
        )
    return current


def decide_case(api: ApiClient, review_case_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.decide_review_case(review_case_id, headers=headers or SAFETY_MANAGER)
    )


def grant_appeal(
    api: ApiClient, review_case_id: str, headers: Optional[Json] = None, **kwargs: Any
) -> Json:
    return get_success_data(
        api.appeal_review_case(
            review_case_id, factories.appeal_payload(**kwargs), headers or APPEALS_MANAGER
        )
    )


# ---------------------------------------------------------------------------
# Policy tower, claims, demands and negotiation
# ---------------------------------------------------------------------------


def build_policy_layer(api: ApiClient, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_policy_layer(factories.policy_layer_payload(**kwargs), CLAIMS_MANAGER)
    )


def build_single_layer_tower(
    api: ApiClient, program_year: int = 2026, limit_cents: int = 10_000_000
) -> List[Json]:
    """A tower consisting of the self-insured retention alone."""
    return [
        build_policy_layer(
            api,
            program_year=program_year,
            layer_index=1,
            layer_type=LAYER_KIND_SIR,
            attachment_point_cents=0,
            limit_cents=limit_cents,
        )
    ]


def build_tower(
    api: ApiClient,
    layers: Sequence[Tuple[str, int]],
    program_year: int = 2026,
) -> List[Json]:
    """Build a contiguous tower from (layer_type, limit_cents) pairs."""
    built: List[Json] = []
    attachment = 0
    for index, (layer_type, limit_cents) in enumerate(layers, start=1):
        built.append(
            build_policy_layer(
                api,
                program_year=program_year,
                layer_index=index,
                layer_type=layer_type,
                attachment_point_cents=attachment,
                limit_cents=limit_cents,
                insurer_name=f"{layer_type} carrier {index}",
            )
        )
        attachment += limit_cents
    return built


def build_three_layer_tower(api: ApiClient, program_year: int = 2026) -> List[Json]:
    """Retention, primary and excess layers stacked without gaps."""
    return build_tower(
        api,
        [
            (LAYER_KIND_SIR, 10_000_000),
            (LAYER_KIND_PRIMARY, 5_000_000),
            (LAYER_KIND_EXCESS, 20_000_000),
        ],
        program_year=program_year,
    )


def build_claim(api: ApiClient, crash_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_claim(factories.claim_payload(crash_id, **kwargs), CLAIMS_ADJUSTER)
    )


def build_demand(api: ApiClient, claim_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_demand(claim_id, factories.demand_payload(**kwargs), CLAIMS_ADJUSTER)
    )


def make_offer(api: ApiClient, demand_id: str, carrier_offer_cents: int) -> Json:
    return get_success_data(
        api.create_offer(demand_id, factories.offer_payload(carrier_offer_cents), CLAIMS_ADJUSTER)
    )


def make_counter(api: ApiClient, demand_id: str, claimant_counter_cents: int) -> Json:
    return get_success_data(
        api.create_counter(
            demand_id, factories.counter_payload(claimant_counter_cents), CLAIMS_ADJUSTER
        )
    )


def settle(api: ApiClient, demand_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.settle_demand(demand_id, factories.settle_payload(**kwargs), CLAIMS_MANAGER)
    )


def rescind(api: ApiClient, demand_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.rescind_settlement(demand_id, factories.rescind_payload(**kwargs), CLAIMS_MANAGER)
    )


def assign_counsel(api: ApiClient, claim_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.assign_counsel(claim_id, factories.counsel_assignment_payload(**kwargs), CLAIMS_MANAGER)
    )


def revise_reserve(api: ApiClient, claim_id: str, expected_version: int, **kwargs: Any) -> Json:
    return get_success_data(
        api.revise_reserve(
            claim_id,
            factories.reserve_revision_payload(expected_version, **kwargs),
            CLAIMS_ADJUSTER,
        )
    )


def build_subrogation_demand(api: ApiClient, claim_id: str, **kwargs: Any) -> Json:
    return get_success_data(
        api.create_subrogation_demand(
            claim_id, factories.subrogation_demand_payload(**kwargs), CLAIMS_ADJUSTER
        )
    )


def build_discipline(
    api: ApiClient, driver_id: str, crash_id: str, **kwargs: Any
) -> Json:
    return get_success_data(
        api.create_disciplinary_action(
            factories.disciplinary_action_payload(driver_id, crash_id, **kwargs),
            SAFETY_MANAGER,
        )
    )


# ---------------------------------------------------------------------------
# Recurring composite preambles
# ---------------------------------------------------------------------------


def build_fleet(
    api: ApiClient,
    terminal_code: str = "GRE02",
    annual_miles_millions: Any = 2.0,
    employee_code: str = "D-5701",
    hire_date: str = "2015-04-06",
    **terminal_kwargs: Any,
) -> Tuple[Json, Json]:
    """One terminal with one driver assigned to it."""
    terminal = build_terminal(
        api,
        terminal_code=terminal_code,
        annual_miles_millions=annual_miles_millions,
        **terminal_kwargs,
    )
    driver = build_driver(
        api, terminal["id"], employee_code=employee_code, hire_date=hire_date
    )
    return terminal, driver


def build_reviewable_crash(
    api: ApiClient,
    severity: str = SEVERITY_MINOR,
    terminal_code: str = "GRE02",
    annual_miles_millions: Any = 2.0,
    employee_code: str = "D-5701",
    hire_date: str = "2015-04-06",
    with_statement: bool = True,
    **crash_kwargs: Any,
) -> Json:
    """A crash whose evidence posture is complete and whose statement is on file."""
    terminal, driver = build_fleet(
        api,
        terminal_code=terminal_code,
        annual_miles_millions=annual_miles_millions,
        employee_code=employee_code,
        hire_date=hire_date,
    )
    crash = build_crash(api, driver["id"], terminal["id"], severity=severity, **crash_kwargs)
    preserved = build_complete_posture(api, crash)
    if with_statement:
        build_statement(api, crash["id"], driver["id"])
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "evidence": preserved,
    }


def build_decided_case(
    api: ApiClient,
    vote: str,
    scores: Optional[Json] = None,
    severity: str = SEVERITY_MINOR,
    **kwargs: Any,
) -> Json:
    """A review case carried through deliberation, a full quorum and a decision."""
    context = build_reviewable_crash(api, severity=severity, **kwargs)
    case = build_case_in_deliberation(api, context["crash"]["id"])
    balloted = cast_quorum(api, case, vote=vote, scores=scores)
    decided = decide_case(api, case["id"])
    context["review_case"] = decided
    context["balloted"] = balloted
    return context


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the freshly started service."""
    return ApiClient()


@pytest.fixture
def safety_admin_headers() -> Json:
    return make_safety_admin_headers()


@pytest.fixture
def dispatcher_headers() -> Json:
    return make_dispatcher_headers()


@pytest.fixture
def safety_manager_headers() -> Json:
    return make_safety_manager_headers(OPERATOR_IDS["safety_manager_decider"])


@pytest.fixture
def appeals_manager_headers() -> Json:
    return make_safety_manager_headers(OPERATOR_IDS["safety_manager_appeals"])


@pytest.fixture
def committee_headers() -> Sequence[Json]:
    return COMMITTEE_HEADERS


@pytest.fixture
def claims_adjuster_headers() -> Json:
    return make_claims_adjuster_headers()


@pytest.fixture
def claims_manager_headers() -> Json:
    return make_claims_manager_headers()


@pytest.fixture
def auditor_headers() -> Json:
    return make_auditor_headers()


@pytest.fixture
def clock_epoch() -> str:
    return CLOCK_EPOCH


@pytest.fixture
def fleet(api: ApiClient) -> Tuple[Json, Json]:
    """One terminal and one long-tenured driver."""
    return build_fleet(api)


@pytest.fixture
def reviewable_crash(api: ApiClient) -> Json:
    """A minor crash with a complete evidence posture and a filed statement."""
    return build_reviewable_crash(api)
