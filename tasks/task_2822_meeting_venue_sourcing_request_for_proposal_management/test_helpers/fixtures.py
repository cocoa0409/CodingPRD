"""Composite state builders and pytest fixtures.

Each test runs against a freshly started server with an empty store, so every
piece of state a test needs is built here through the documented endpoints only.

The module is layered:

* **Tier 1 — single-step builders** (``set_clock``, ``create_venue``, ...) wrap
  one endpoint call and return the created resource.
* **Tier 2 — workflow steps** (``promote_entry``, ``issue_rfp``, ...) advance one
  artefact along its state machine.
* **Tier 3 — chain helpers** (``submit_bid``, ``approve_all_steps``, ...) run the
  short multi-call sequences the sourcing workflow repeats.
* **Tier 4 — worlds** (``build_sourcing_world`` and friends) assemble the whole
  pipeline up to a named milestone and return every identifier a test needs.
* **Tier 5 — pytest fixtures** expose those worlds by name.

Money is always sent as a JSON number and instants always carry three fractional
digits, matching the field types the PRD declares.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_SOURCING_WINDOW
from .test_users import (
    APPROVER_ALT_HEADERS,
    APPROVER_HEADERS,
    APPROVER_THIRD_HEADERS,
    FINANCE_HEADERS,
    PLANNER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_venue_rep_headers,
)

# The approver identity used for each control level. Each level gets a distinct
# identifier and none of them is the awarding planner.
APPROVER_HEADERS_BY_LEVEL = {
    "PROGRAM_COMPLIANCE": PROGRAM_ADMIN_HEADERS,
    "MANAGER": APPROVER_HEADERS,
    "VP": APPROVER_ALT_HEADERS,
    "LEGAL": APPROVER_THIRD_HEADERS,
}


# ---------------------------------------------------------------------------
# Tier 1: single-step builders
# ---------------------------------------------------------------------------
def set_clock(current_utc: str, headers: Dict[str, str] = PROGRAM_ADMIN_HEADERS) -> None:
    """Move the server's logical current UTC instant."""
    response = api_client.set_clock(factories.clock_payload(current_utc), headers)
    get_success_data(response, 200)


def create_benchmark(**overrides: Any) -> Dict[str, Any]:
    response = api_client.create_rate_benchmark(
        factories.rate_benchmark_payload(**overrides), PROGRAM_ADMIN_HEADERS
    )
    return get_success_data(response, 201)


def create_venue(**overrides: Any) -> Dict[str, Any]:
    response = api_client.create_venue(
        factories.venue_payload(**overrides), PROGRAM_ADMIN_HEADERS
    )
    return get_success_data(response, 201)


def create_second_venue(**overrides: Any) -> Dict[str, Any]:
    response = api_client.create_venue(
        factories.second_venue_payload(**overrides), PROGRAM_ADMIN_HEADERS
    )
    return get_success_data(response, 201)


def set_preferred_status(venue_id: str, status: str) -> Dict[str, Any]:
    response = api_client.update_venue_preferred_status(
        venue_id, factories.preferred_status_payload(status), PROGRAM_ADMIN_HEADERS
    )
    return get_success_data(response, 200)


def create_event(**overrides: Any) -> Dict[str, Any]:
    response = api_client.create_event(
        factories.event_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 201)


def read_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_event(event_id, PLANNER_HEADERS), 200)


def read_venue(venue_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_venue(venue_id, PLANNER_HEADERS), 200)


def read_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_shortlist_entry(entry_id, PLANNER_HEADERS), 200
    )


def read_proposal(proposal_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_proposal(proposal_id, PLANNER_HEADERS), 200)


def read_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_contract(contract_id, PLANNER_HEADERS), 200)


def read_rfp(rfp_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_rfp(rfp_id, PLANNER_HEADERS), 200)


def read_inspection(inspection_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_site_inspection(inspection_id, PLANNER_HEADERS), 200
    )


def event_version(event_id: str) -> int:
    return read_event(event_id)["version"]


def proposal_version(proposal_id: str) -> int:
    return read_proposal(proposal_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: workflow steps
# ---------------------------------------------------------------------------
def lock_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.lock_event_requirements(event_id, PLANNER_HEADERS), 200
    )


def add_entry(event_id: str, venue_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.create_shortlist_entry(
        event_id, factories.shortlist_entry_payload(venue_id, **overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 201)


def promote_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.shortlist_entry(entry_id, PLANNER_HEADERS), 200)


def eliminate_entry(entry_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.eliminate_shortlist_entry(
        entry_id, factories.eliminate_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 200)


def plan_inspection(entry_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.create_site_inspection(
        factories.site_inspection_payload(entry_id, **overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 201)


def complete_inspection(inspection_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.complete_site_inspection(
        inspection_id, factories.complete_inspection_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 200)


def cancel_inspection(inspection_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.cancel_site_inspection(
        inspection_id, factories.cancel_inspection_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 200)


def create_rfp(event_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.create_rfp(
        event_id, factories.rfp_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 201)


def issue_rfp(rfp_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.issue_rfp(rfp_id, PLANNER_HEADERS), 200)


def close_rfp(rfp_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_rfp(rfp_id, PLANNER_HEADERS), 200)


def find_invited_proposal(rfp_id: str, venue_id: str) -> Dict[str, Any]:
    """Locate the ``INVITED`` bid minted for one venue by issuing a round.

    The bid collection is the only discovery channel for these shells.
    """
    response = api_client.list_proposals(
        PLANNER_HEADERS, {"rfp_id": rfp_id, "venue_id": venue_id}
    )
    rows = get_success_data(response, 200)
    assert rows, f"no bid was minted for venue {venue_id} on round {rfp_id}"
    return rows[0]


def list_round_proposals(rfp_id: str) -> List[Dict[str, Any]]:
    response = api_client.list_proposals(PLANNER_HEADERS, {"rfp_id": rfp_id, "limit": 100})
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Tier 3: chain helpers
# ---------------------------------------------------------------------------
def submit_bid(proposal_id: str, venue_id: str, **grid_overrides: Any) -> Dict[str, Any]:
    """Submit the standardized grid for one venue's own bid."""
    response = api_client.submit_proposal(
        proposal_id,
        factories.proposal_submission_payload(**grid_overrides),
        make_venue_rep_headers(venue_id),
    )
    return get_success_data(response, 200)


def decline_bid(proposal_id: str, venue_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.decline_proposal(proposal_id, make_venue_rep_headers(venue_id)), 200
    )


def withdraw_bid(proposal_id: str, venue_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_proposal(proposal_id, make_venue_rep_headers(venue_id)), 200
    )


def evaluate_bid(proposal_id: str, basis: str = "CONTRACTED_BASIS") -> Dict[str, Any]:
    response = api_client.evaluate_proposal(
        proposal_id, factories.evaluate_payload(basis), PLANNER_HEADERS
    )
    return get_success_data(response, 201)


def raise_counter(proposal_id: str, **overrides: Any) -> Dict[str, Any]:
    """Raise a counter, reading the bid's current version first."""
    payload = factories.counter_payload(proposal_version(proposal_id), **overrides)
    response = api_client.create_counter(proposal_id, payload, PLANNER_HEADERS)
    return get_success_data(response, 201)


def revise_bid(
    proposal_id: str, venue_id: str, counter_id: str, accepted: bool = True, **overrides: Any
) -> Dict[str, Any]:
    response = api_client.revise_proposal(
        proposal_id,
        factories.revision_payload(counter_id, accepted, **overrides),
        make_venue_rep_headers(venue_id),
    )
    return get_success_data(response, 200)


def award_bid(event_id: str, proposal_id: str, **overrides: Any) -> Dict[str, Any]:
    """Award a bid, reading the event's current version first."""
    payload = factories.award_payload(proposal_id, event_version(event_id), **overrides)
    response = api_client.award_event(event_id, payload, PLANNER_HEADERS)
    return get_success_data(response, 201)


def route_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.route_approvals(contract_id, PLANNER_HEADERS), 200
    )


def approval_steps(contract_id: str) -> List[Dict[str, Any]]:
    response = api_client.list_approval_steps(contract_id, PLANNER_HEADERS, {"limit": 100})
    return get_success_data(response, 200)


def decide_step(
    step_id: str, decision: str, headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    response = api_client.decide_approval_step(
        step_id, factories.decision_payload(decision, **overrides), headers
    )
    return get_success_data(response, 200)


def approve_all_steps(contract_id: str) -> List[Dict[str, Any]]:
    """Approve every control step in ``step_seq`` order.

    Each level is decided by the identity its ``required_role`` admits, and every
    approving identity is distinct from the others and from the awarding planner.
    """
    decided = []
    for step in sorted(approval_steps(contract_id), key=lambda s: s["step_seq"]):
        headers = APPROVER_HEADERS_BY_LEVEL[step["approval_level"]]
        decided.append(decide_step(step["id"], "APPROVED", headers))
    return decided


def sign_contract(contract_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.sign_contract(
        contract_id, factories.sign_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 200)


def countersign_contract(contract_id: str, venue_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.countersign_contract(
        contract_id,
        factories.countersign_payload(**overrides),
        make_venue_rep_headers(venue_id),
    )
    return get_success_data(response, 200)


def terminate_contract(contract_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.terminate_contract(
        contract_id, factories.terminate_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 200)


def generate_deposit_schedule(contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.generate_deposit_schedule(contract_id, FINANCE_HEADERS), 200
    )


def deposit_installments(contract_id: str) -> List[Dict[str, Any]]:
    response = api_client.list_deposit_installments(
        contract_id, FINANCE_HEADERS, {"limit": 100}
    )
    return get_success_data(response, 200)


def pay_installment(installment_id: str, amount: float, **overrides: Any) -> Dict[str, Any]:
    response = api_client.pay_deposit_installment(
        installment_id, factories.pay_installment_payload(amount, **overrides), FINANCE_HEADERS
    )
    return get_success_data(response, 200)


def file_post_event_report(event_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.create_post_event_report(
        event_id, factories.post_event_report_payload(**overrides), PLANNER_HEADERS
    )
    return get_success_data(response, 201)


def capture_review(venue_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api_client.create_performance_review(
        venue_id, factories.performance_review_payload(**overrides), PROGRAM_ADMIN_HEADERS
    )
    return get_success_data(response, 201)


# ---------------------------------------------------------------------------
# Tier 4: whole-pipeline worlds
# ---------------------------------------------------------------------------
def build_sourcing_world(
    clock: str = CLOCK_SOURCING_WINDOW,
    benchmark_overrides: Optional[Dict[str, Any]] = None,
    venue_overrides: Optional[Dict[str, Any]] = None,
    event_overrides: Optional[Dict[str, Any]] = None,
    entry_overrides: Optional[Dict[str, Any]] = None,
    promote: bool = True,
) -> Dict[str, Any]:
    """Published benchmark, registered venue, locked requirement and one entry.

    With ``promote`` left true the entry has been committed to the solicitation,
    which is the state from which a round may be issued.
    """
    set_clock(clock)
    benchmark = create_benchmark(**(benchmark_overrides or {}))
    venue = create_venue(**(venue_overrides or {}))
    event = create_event(**(event_overrides or {}))
    lock_event(event["id"])
    entry = add_entry(event["id"], venue["id"], **(entry_overrides or {}))
    if promote:
        entry = promote_entry(entry["id"])
    return {
        "benchmark": benchmark,
        "benchmark_id": benchmark["id"],
        "venue": venue,
        "venue_id": venue["id"],
        "event": event,
        "event_id": event["id"],
        "entry": entry,
        "entry_id": entry["id"],
    }


def build_issued_round(
    rfp_overrides: Optional[Dict[str, Any]] = None, **world_kwargs: Any
) -> Dict[str, Any]:
    """A sourcing world whose round 1 has been issued, with the invited bid found."""
    world = build_sourcing_world(**world_kwargs)
    rfp = create_rfp(world["event_id"], **(rfp_overrides or {}))
    rfp = issue_rfp(rfp["id"])
    proposal = find_invited_proposal(rfp["id"], world["venue_id"])
    world.update(
        {"rfp": rfp, "rfp_id": rfp["id"], "proposal": proposal, "proposal_id": proposal["id"]}
    )
    return world


def build_submitted_bid(
    bid_overrides: Optional[Dict[str, Any]] = None, **round_kwargs: Any
) -> Dict[str, Any]:
    """An issued round whose single invited venue has submitted its grid."""
    world = build_issued_round(**round_kwargs)
    world["proposal"] = submit_bid(
        world["proposal_id"], world["venue_id"], **(bid_overrides or {})
    )
    return world


def build_evaluated_bid(
    basis: str = "CONTRACTED_BASIS",
    close_round: bool = False,
    **submitted_kwargs: Any,
) -> Dict[str, Any]:
    """A submitted bid that has been priced once, leaving it ``UNDER_REVIEW``."""
    world = build_submitted_bid(**submitted_kwargs)
    if close_round:
        world["rfp"] = close_rfp(world["rfp_id"])
    world["evaluation"] = evaluate_bid(world["proposal_id"], basis)
    world["proposal"] = read_proposal(world["proposal_id"])
    return world


def build_awarded_contract(**evaluated_kwargs: Any) -> Dict[str, Any]:
    """An awarded event: round closed, bid priced on the contracted basis, contract minted."""
    evaluated_kwargs.setdefault("close_round", True)
    evaluated_kwargs.setdefault("basis", "CONTRACTED_BASIS")
    world = build_evaluated_bid(**evaluated_kwargs)
    contract = award_bid(world["event_id"], world["proposal_id"])
    world.update({"contract": contract, "contract_id": contract["id"]})
    return world


def build_routed_contract(**awarded_kwargs: Any) -> Dict[str, Any]:
    """An awarded contract whose approval chain has been generated."""
    world = build_awarded_contract(**awarded_kwargs)
    world["contract"] = route_contract(world["contract_id"])
    world["steps"] = approval_steps(world["contract_id"])
    return world


def build_executed_contract(**awarded_kwargs: Any) -> Dict[str, Any]:
    """A fully executed contract: every control approved, both signatures in place."""
    world = build_routed_contract(**awarded_kwargs)
    approve_all_steps(world["contract_id"])
    sign_contract(world["contract_id"])
    world["contract"] = countersign_contract(world["contract_id"], world["venue_id"])
    world["steps"] = approval_steps(world["contract_id"])
    return world


def build_deposit_scheduled_contract(**executed_kwargs: Any) -> Dict[str, Any]:
    """An executed contract carrying its three-installment deposit schedule."""
    world = build_executed_contract(**executed_kwargs)
    world["contract"] = generate_deposit_schedule(world["contract_id"])
    world["installments"] = deposit_installments(world["contract_id"])
    return world


def build_two_venue_round(
    second_venue_overrides: Optional[Dict[str, Any]] = None,
    second_entry_overrides: Optional[Dict[str, Any]] = None,
    rfp_overrides: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """Two promoted venues on one event, with round 1 issued to both.

    The second venue's artefacts are returned under the ``*_b`` keys.
    """
    world = build_sourcing_world(**world_kwargs)
    venue_b = create_second_venue(**(second_venue_overrides or {}))
    entry_b_overrides = {"rank_seq": 2}
    entry_b_overrides.update(second_entry_overrides or {})
    entry_b = add_entry(world["event_id"], venue_b["id"], **entry_b_overrides)
    entry_b = promote_entry(entry_b["id"])
    rfp = create_rfp(world["event_id"], **(rfp_overrides or {}))
    rfp = issue_rfp(rfp["id"])
    proposal_a = find_invited_proposal(rfp["id"], world["venue_id"])
    proposal_b = find_invited_proposal(rfp["id"], venue_b["id"])
    world.update(
        {
            "venue_b": venue_b,
            "venue_b_id": venue_b["id"],
            "entry_b": entry_b,
            "entry_b_id": entry_b["id"],
            "rfp": rfp,
            "rfp_id": rfp["id"],
            "proposal": proposal_a,
            "proposal_id": proposal_a["id"],
            "proposal_b": proposal_b,
            "proposal_b_id": proposal_b["id"],
        }
    )
    return world


def build_negotiation_cycle(loops: int = 1, **submitted_kwargs: Any) -> Dict[str, Any]:
    """Run the counter/revise/evaluate cycle ``loops`` times over one live bid.

    The round stays ``ISSUED`` throughout, because a counter may only be raised
    while the parent round is open.
    """
    world = build_submitted_bid(**submitted_kwargs)
    evaluate_bid(world["proposal_id"], "CONTRACTED_BASIS")
    counters = []
    for index in range(loops):
        counter = raise_counter(
            world["proposal_id"],
            term_category="RATE",
            proposed_numeric_value=235.00,
            planner_note="Bring the rate to 235.00.",
        )
        counters.append(counter)
        revise_bid(
            world["proposal_id"],
            world["venue_id"],
            counter["id"],
            accepted=True,
            revised_room_rate_usd=235.00,
        )
        evaluate_bid(world["proposal_id"], "CONTRACTED_BASIS")
    world["counters"] = counters
    world["proposal"] = read_proposal(world["proposal_id"])
    return world


# ---------------------------------------------------------------------------
# Tier 5: pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sourcing_world() -> Dict[str, Any]:
    return build_sourcing_world()


@pytest.fixture
def issued_round() -> Dict[str, Any]:
    return build_issued_round()


@pytest.fixture
def submitted_bid() -> Dict[str, Any]:
    return build_submitted_bid()


@pytest.fixture
def evaluated_bid() -> Dict[str, Any]:
    return build_evaluated_bid()


@pytest.fixture
def awarded_contract() -> Dict[str, Any]:
    return build_awarded_contract()


@pytest.fixture
def routed_contract() -> Dict[str, Any]:
    return build_routed_contract()


@pytest.fixture
def executed_contract() -> Dict[str, Any]:
    return build_executed_contract()


@pytest.fixture
def deposit_scheduled_contract() -> Dict[str, Any]:
    return build_deposit_scheduled_contract()


@pytest.fixture
def two_venue_round() -> Dict[str, Any]:
    return build_two_venue_round()


@pytest.fixture
def sourcing_clock() -> str:
    """Place the logical clock inside the sourcing window and hand back the instant."""
    set_clock(CLOCK_SOURCING_WINDOW)
    return CLOCK_SOURCING_WINDOW
