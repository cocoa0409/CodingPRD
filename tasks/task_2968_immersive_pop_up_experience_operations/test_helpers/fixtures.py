"""Composite setup builders.

Every builder here drives the public API only: it makes the same calls a client
would make, in the order the PRD admits them, and returns the response bodies
so a test can assert against real identifiers.  Setup calls go through
``get_success_data`` because a setup step only has to succeed, not to be
inspected; the assertions belong in the tests.

Two conventions matter.  First, every builder takes ``**overrides`` and threads
them into the payload of the resource it creates, so a test can move one field
and leave the rest of a long chain legal.  Second, builders that depend on a
parent's ``version`` always re-read that parent immediately before the call
that needs it, because an earlier hop of the same builder may already have
advanced it.
"""

from itertools import count
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import CLOCK_EPOCH, REQUIRED_CERTIFICATIONS, TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_guest_headers,
)

VOM = TEST_USERS["venue_ops_manager_headers"]
LM = TEST_USERS["licensing_manager_headers"]
REP = TEST_USERS["licensor_rep_headers"]
REP_OTHER = TEST_USERS["other_licensor_rep_headers"]
PRODUCER = TEST_USERS["experience_producer_headers"]
PRODUCER_OTHER = TEST_USERS["other_experience_producer_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]
OFFICER_OTHER = TEST_USERS["other_safety_officer_headers"]
AGENT = TEST_USERS["guest_services_agent_headers"]

_SEQ = count(1)


def next_seq() -> int:
    """A process-unique small integer for building unique codes and emails."""
    return next(_SEQ)


# ─── Logical clock ──────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Park the logical clock on an exact instant."""
    return get_success_data(api_client.set_clock(to_iso8601, VOM))


def reset_clock() -> Dict[str, Any]:
    """Park the logical clock back on its declared starting instant."""
    return set_clock(CLOCK_EPOCH)


# ─── Tier 1: single-resource state progressions ─────────────────────────────

def create_venue(**overrides: Any) -> dict:
    """A venue in DRAFT."""
    return get_success_data(
        api_client.create_venue(f.venue_payload(**overrides), VOM)
    )


def venue_under_review(**overrides: Any) -> dict:
    """A venue whose first permit package has been filed."""
    venue = create_venue(**overrides)
    get_success_data(
        api_client.submit_permit_package(
            venue["id"], f.permit_submission_payload(), VOM
        )
    )
    return read_venue(venue["id"])


def venue_permitted(**overrides: Any) -> dict:
    """A venue in PERMIT_ISSUED - the earliest state a run may be planned in."""
    venue = venue_under_review(**overrides)
    get_success_data(
        api_client.decide_permit(
            venue["id"], f.permit_decision_payload("ISSUED"), OFFICER
        )
    )
    return read_venue(venue["id"])


def venue_lease_active(**overrides: Any) -> dict:
    """A venue in LEASE_ACTIVE.

    The clock must already be on or after the lease start date; the default
    lease starts on the clock's own starting date, so no clock move is needed.
    """
    venue = venue_permitted(**overrides)
    get_success_data(api_client.activate_lease(venue["id"], VOM))
    return read_venue(venue["id"])


def create_kit(**overrides: Any) -> dict:
    """A build kit in READY and LOCALIZED, with a unique kit code."""
    overrides.setdefault("code", f.kit_code(next_seq()))
    return get_success_data(api_client.create_kit(f.kit_payload(**overrides), VOM))


def create_agreement(**overrides: Any) -> dict:
    """A licence agreement in DRAFT."""
    return get_success_data(
        api_client.create_agreement(f.agreement_payload(**overrides), LM)
    )


def agreement_active(**overrides: Any) -> dict:
    """A licence agreement in ACTIVE - the only state a run may name."""
    agreement = create_agreement(**overrides)
    get_success_data(api_client.activate_agreement(agreement["id"], LM))
    return read_agreement(agreement["id"])


def create_guest(**overrides: Any) -> dict:
    """A guest account in ACTIVE, with a unique email address."""
    overrides.setdefault("email", f"guest{next_seq()}@example.com")
    return get_success_data(
        api_client.create_guest(f.guest_payload(**overrides), AGENT)
    )


# ─── Re-reads (a builder never trusts a stale copy of a parent) ─────────────

def read_venue(venue_id: str) -> dict:
    return get_success_data(api_client.get_venue(venue_id, VOM))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, LM))


def read_submission(submission_id: str) -> dict:
    return get_success_data(api_client.get_submission(submission_id, PRODUCER))


def read_run(run_id: str) -> dict:
    return get_success_data(api_client.get_run(run_id, PRODUCER))


def read_room(room_id: str) -> dict:
    return get_success_data(api_client.get_room(room_id, PRODUCER))


def read_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_slot(slot_id, PRODUCER))


def read_guest(guest_id: str) -> dict:
    return get_success_data(api_client.get_guest(guest_id, AGENT))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, AGENT))


def read_staff_member(staff_id: str) -> dict:
    return get_success_data(api_client.get_staff_member(staff_id, PRODUCER))


def read_shift(shift_id: str) -> dict:
    return get_success_data(api_client.get_shift(shift_id, PRODUCER))


def read_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, OFFICER))


def read_kit(kit_id: str) -> dict:
    return get_success_data(api_client.get_kit(kit_id, VOM))


def read_statement(statement_id: str) -> dict:
    return get_success_data(api_client.get_statement(statement_id, LM))


def agreement_version(agreement_id: str) -> int:
    """The agreement's current version, read fresh for a concurrency guard."""
    return read_agreement(agreement_id)["version"]


def run_version(run_id: str) -> int:
    """The run's current version, read fresh for a concurrency guard."""
    return read_run(run_id)["version"]


# ─── Tier 2: the entity hierarchy ───────────────────────────────────────────

def planned_run(venue: Optional[dict] = None, agreement: Optional[dict] = None,
                kit: Optional[dict] = None, **overrides: Any) -> dict:
    """A run in PLANNED and UNCLEARED, on a permitted venue and active licence.

    Returns the run row only; use :func:`run_bundle` when the test also needs
    the venue, the licence or the kit.
    """
    return run_bundle(venue=venue, agreement=agreement, kit=kit, **overrides)["run"]


def run_bundle(venue: Optional[dict] = None, agreement: Optional[dict] = None,
               kit: Optional[dict] = None, lease_active: bool = False,
               venue_overrides: Optional[Dict[str, Any]] = None,
               agreement_overrides: Optional[Dict[str, Any]] = None,
               kit_overrides: Optional[Dict[str, Any]] = None,
               **overrides: Any) -> Dict[str, Any]:
    """The smallest complete world that holds a run: venue, licence, kit, run.

    ``lease_active`` switches the venue's lease on before the run is created,
    which is what the run needs before it can be opened.
    """
    if venue is None:
        builder = venue_lease_active if lease_active else venue_permitted
        venue = builder(**(venue_overrides or {}))
    if agreement is None:
        agreement = agreement_active(**(agreement_overrides or {}))
    if kit is None:
        kit = create_kit(**(kit_overrides or {}))
    run = get_success_data(
        api_client.create_run(
            f.run_payload(venue["id"], agreement["id"], kit["id"], **overrides),
            PRODUCER,
        )
    )
    return {
        "venue": read_venue(venue["id"]),
        "agreement": read_agreement(agreement["id"]),
        "kit": read_kit(kit["id"]),
        "run": run,
    }


def add_room(run_id: str, room_sequence: int = 1, **overrides: Any) -> dict:
    """One themed room on a run, which is what gives the run a capacity."""
    return get_success_data(
        api_client.create_room(
            f.room_payload(run_id, room_sequence, **overrides), PRODUCER
        )
    )


def run_with_room(**kwargs: Any) -> Dict[str, Any]:
    """A run that has a capacity, because a roomless run has none at all.

    The default room passes 40 guests every 15 minutes on a 45-minute cadence,
    so the bottleneck term is 120 and the run's effective_capacity is 120.
    """
    room_overrides = kwargs.pop("room_overrides", None) or {}
    bundle = run_bundle(**kwargs)
    bundle["room"] = add_room(bundle["run"]["id"], **room_overrides)
    bundle["run"] = read_run(bundle["run"]["id"])
    return bundle


def draft_slot(run_id: str, **overrides: Any) -> dict:
    """An admission window in DRAFT, with every seat counter at 0."""
    return get_success_data(
        api_client.create_slot(f.slot_payload(run_id, **overrides), PRODUCER)
    )


def open_slot(run_id: str, **overrides: Any) -> dict:
    """An admission window in OPEN, with every seat available."""
    slot = draft_slot(run_id, **overrides)
    get_success_data(api_client.release_slot(slot["id"], PRODUCER))
    return read_slot(slot["id"])


def enrol_staff(run_id: str, staff_role: str = "PERFORMER",
                **overrides: Any) -> dict:
    """A staff member in CANDIDATE, holding every certification the craft needs."""
    return get_success_data(
        api_client.create_staff_member(
            f.staff_member_payload(run_id, staff_role, **overrides), PRODUCER
        )
    )


def trained_staff(run_id: str, staff_role: str = "PERFORMER",
                  training_score: int = 90, completed_rehearsal_count: int = 4,
                  scheduled_rehearsal_count: Optional[int] = None,
                  incident_delta: Optional[int] = None,
                  **overrides: Any) -> dict:
    """A staff member in TRAINING whose audit readiness clears the 78.00 floor.

    With a full certification set, four completed rehearsals and a training
    score of 90 the audit score is 96.00, comfortably above the floor.
    """
    member = enrol_staff(run_id, staff_role, **overrides)
    record: Dict[str, Any] = {
        "training_score": training_score,
        "completed_rehearsal_count": completed_rehearsal_count,
    }
    if scheduled_rehearsal_count is not None:
        record["scheduled_rehearsal_count"] = scheduled_rehearsal_count
    if incident_delta is not None:
        record["incident_delta"] = incident_delta
    get_success_data(
        api_client.add_training_record(
            member["id"], f.training_record_payload(**record), PRODUCER
        )
    )
    return read_staff_member(member["id"])


def cleared_staff(run_id: str, staff_role: str = "PERFORMER",
                  **overrides: Any) -> dict:
    """A staff member in CLEARED - the only state a shift may be booked for."""
    member = trained_staff(run_id, staff_role, **overrides)
    get_success_data(
        api_client.decide_staff_status(
            member["id"], f.staff_status_decision_payload("CLEAR"), PRODUCER
        )
    )
    return read_staff_member(member["id"])


def full_roster(run_id: str) -> Dict[str, dict]:
    """One CLEARED member of each craft, which is the staffing half of the gate.

    The crafts are enrolled in a fixed order so that the clearing of the
    technician is always the call that completes the staffing conjunction.
    """
    roster = {}
    for key, role, name in (
        ("performer", "PERFORMER", "Ines Okafor"),
        ("ambassador", "AMBASSADOR", "Dara Vance"),
        ("technician", "TECHNICIAN", "Piet Halloran"),
    ):
        roster[key] = cleared_staff(run_id, role, full_name=name)
    return roster


def book_shift(staff_member_id: str, **overrides: Any) -> dict:
    """One shift on one cleared person."""
    return get_success_data(
        api_client.create_shift(f.shift_payload(staff_member_id, **overrides), PRODUCER)
    )


def approved_submission(agreement_id: str, run_id: str,
                        scope: str = "CREATIVE_EXECUTION",
                        asset_code: str = "ATRIUM-SCRIPT-01",
                        note: str = "cleared for build",
                        **overrides: Any) -> dict:
    """A creative asset carried all the way to APPROVED.

    The agreement's version is read immediately before the create, because an
    earlier submission on the same agreement will already have advanced it.
    """
    submission = get_success_data(
        api_client.create_submission(
            f.submission_payload(
                agreement_id, run_id, agreement_version(agreement_id),
                scope=scope, asset_code=asset_code, **overrides
            ),
            PRODUCER,
        )
    )
    get_success_data(api_client.start_submission_review(submission["id"], REP))
    get_success_data(
        api_client.decide_submission(
            submission["id"], f.submission_decision_payload("APPROVED", note), REP
        )
    )
    return read_submission(submission["id"])


def submission_in_review(agreement_id: str, run_id: str,
                         **overrides: Any) -> dict:
    """A creative asset sitting in IN_REVIEW, awaiting the licensor's decision."""
    submission = get_success_data(
        api_client.create_submission(
            f.submission_payload(
                agreement_id, run_id, agreement_version(agreement_id), **overrides
            ),
            PRODUCER,
        )
    )
    get_success_data(api_client.start_submission_review(submission["id"], REP))
    return read_submission(submission["id"])


def scheduled_inspection(run_id: str, inspection_type: str = "EGRESS",
                         **overrides: Any) -> dict:
    """A safety inspection booked but not yet finalised."""
    return get_success_data(
        api_client.create_inspection(
            f.inspection_payload(run_id, inspection_type, **overrides), OFFICER
        )
    )


def finalized_inspection(run_id: str, inspection_type: str = "EGRESS",
                         headers: Optional[Dict[str, str]] = None,
                         create_overrides: Optional[Dict[str, Any]] = None,
                         **finalize_overrides: Any) -> dict:
    """An inspection finalised with the numbers the caller chooses.

    The default numbers - 400 cm measured against a 400 cm design, no findings
    and a severity of NONE - land on the PASS rung of the verdict ladder.
    """
    inspection = scheduled_inspection(
        run_id, inspection_type, **(create_overrides or {})
    )
    get_success_data(
        api_client.finalize_inspection(
            inspection["id"],
            f.inspection_finalize_payload(**finalize_overrides),
            headers or OFFICER,
        )
    )
    return read_inspection(inspection["id"])


# ─── Tier 3: whole-lifecycle shortcuts ──────────────────────────────────────

def cleared_run(**kwargs: Any) -> Dict[str, Any]:
    """A run in PLANNED whose compliance standing has been driven to CLEARED.

    The gate is a conjunction: every scope the licence holds veto rights over
    needs an APPROVED asset for this run, and each of the three crafts needs a
    CLEARED member.  The crafts are cleared last, so the technician's clearance
    is the call that completes the gate.  The venue's lease is switched on so
    the run is ready to be opened.
    """
    kwargs.setdefault("lease_active", True)
    bundle = run_with_room(**kwargs)
    run_id = bundle["run"]["id"]
    agreement_id = bundle["agreement"]["id"]
    bundle["submissions"] = {}
    for index, scope in enumerate(bundle["agreement"]["approval_scopes"], start=1):
        bundle["submissions"][scope] = approved_submission(
            agreement_id, run_id, scope=scope, asset_code=f"ATRIUM-ASSET-{index:02d}"
        )
    bundle["submission"] = next(iter(bundle["submissions"].values()))
    bundle["roster"] = full_roster(run_id)
    bundle["agreement"] = read_agreement(agreement_id)
    bundle["run"] = read_run(run_id)
    return bundle


def open_run(slot_overrides: Optional[Dict[str, Any]] = None,
             **kwargs: Any) -> Dict[str, Any]:
    """A run in OPEN and CLEARED with one released admission window.

    Opening demands all of it at once: a PLANNED run, a LEASE_ACTIVE venue, a
    CLEARED compliance standing, a capacity above 0 and at least one window
    already OPEN, so the window is released before the run is opened.
    """
    bundle = cleared_run(**kwargs)
    bundle["slot"] = open_slot(bundle["run"]["id"], **(slot_overrides or {}))
    get_success_data(api_client.open_run(bundle["run"]["id"], PRODUCER))
    bundle["run"] = read_run(bundle["run"]["id"])
    bundle["slot"] = read_slot(bundle["slot"]["id"])
    return bundle


def selling_world(guest_overrides: Optional[Dict[str, Any]] = None,
                  **kwargs: Any) -> Dict[str, Any]:
    """An open run, a released window and an active guest ready to buy."""
    bundle = open_run(**kwargs)
    bundle["guest"] = create_guest(**(guest_overrides or {}))
    return bundle


def place_order(slot_id: str, guest_account_id: str,
                headers: Optional[Dict[str, str]] = None,
                **overrides: Any) -> dict:
    """A ticket order in PENDING, holding its seats on the window."""
    return get_success_data(
        api_client.create_order(
            f.order_payload(slot_id, guest_account_id, **overrides),
            headers or AGENT,
        )
    )


def confirmed_order(slot_id: str, guest_account_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    **overrides: Any) -> dict:
    """A ticket order in CONFIRMED, with its seats moved from held to sold."""
    order = place_order(slot_id, guest_account_id, headers, **overrides)
    get_success_data(api_client.confirm_order(order["id"], AGENT))
    return read_order(order["id"])


def refund_due_order(slot_id: str, guest_account_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     cancel_headers: Optional[Dict[str, str]] = None,
                     **overrides: Any) -> dict:
    """A confirmed order cancelled back into REFUND_DUE, split already fixed."""
    order = confirmed_order(slot_id, guest_account_id, headers, **overrides)
    get_success_data(
        api_client.cancel_order(order["id"], f.cancel_payload(), cancel_headers or AGENT)
    )
    return read_order(order["id"])


def refunded_order(slot_id: str, guest_account_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   **overrides: Any) -> dict:
    """A refund settled all the way to REFUNDED, so the credit has landed."""
    order = refund_due_order(slot_id, guest_account_id, headers, **overrides)
    get_success_data(api_client.settle_refund(order["id"], AGENT))
    return read_order(order["id"])


def sell_out_slot(slot: dict, guest_account_id: str,
                  order_type: str = "GROUP") -> List[dict]:
    """Confirm orders until the window has no seat left available.

    The window's whole released capacity is sold in parties no larger than the
    run's group ceiling, so utilisation over the released windows is 100.
    """
    remaining = slot["available_capacity"]
    run = read_run(slot["run_id"])
    step = min(run["max_group_size"], remaining) or 1
    orders = []
    while remaining > 0:
        party = min(step, remaining)
        orders.append(
            confirmed_order(
                slot["id"], guest_account_id, party_size=party,
                order_type=order_type if party > 1 else "SINGLE",
            )
        )
        remaining -= party
    return orders


# ─── Tier 4: targeting an exact threshold ───────────────────────────────────

def suspended_run(bundle: Optional[Dict[str, Any]] = None,
                  headers: Optional[Dict[str, str]] = None,
                  **kwargs: Any) -> Dict[str, Any]:
    """A run driven to SUSPENDED by a failed inspection.

    A severity of CRITICAL takes the second rung of the verdict ladder, so the
    verdict is FAIL whatever the measured geometry says, and the failure
    cascade suspends the run, its released windows and its confirmed orders.
    """
    bundle = bundle if bundle is not None else open_run(**kwargs)
    bundle["suspending_inspection"] = finalized_inspection(
        bundle["run"]["id"],
        headers=headers or OFFICER,
        severity="CRITICAL",
        findings_count=1,
        findings_note="egress corridor obstructed by stored scenic flats",
    )
    bundle["run"] = read_run(bundle["run"]["id"])
    if "slot" in bundle:
        bundle["slot"] = read_slot(bundle["slot"]["id"])
    return bundle


def lift_with_fresh_pass(bundle: Dict[str, Any],
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Clear a suspension with a later PASS of the same inspection type.

    The lifting officer must differ from the officer who finalised the
    suspending inspection, so the second officer is used by default.
    """
    clearing = finalized_inspection(
        bundle["run"]["id"],
        inspection_type=bundle["suspending_inspection"]["inspection_type"],
        headers=headers or OFFICER_OTHER,
    )
    get_success_data(
        api_client.lift_suspension(
            bundle["run"]["id"], f.lift_suspension_payload(clearing["id"]),
            headers or OFFICER_OTHER,
        )
    )
    bundle["clearing_inspection"] = clearing
    bundle["run"] = read_run(bundle["run"]["id"])
    return bundle


def run_at_demand(utilisation_seats: int = 10, sold_seats: int = 10,
                  option_days: int = 30, **kwargs: Any) -> Dict[str, Any]:
    """An open run whose demand index lands on an exact figure.

    Demand is utilisation less half the refund share.  With no refunded order
    the refund term is 0.00, so selling ``sold_seats`` of a window released at
    ``utilisation_seats`` puts the index at exactly 100 times their ratio - ten
    seats with seven sold is exactly 70.00, the inclusive extension floor.
    """
    venue_overrides = dict(kwargs.pop("venue_overrides", None) or {})
    venue_overrides.setdefault("lease_extension_option_days", option_days)
    bundle = selling_world(
        venue_overrides=venue_overrides,
        slot_overrides={"base_capacity": utilisation_seats,
                        "wheelchair_positions": 0},
        **kwargs,
    )
    bundle["orders"] = []
    remaining = sold_seats
    while remaining > 0:
        party = min(bundle["run"]["max_group_size"], remaining)
        bundle["orders"].append(
            confirmed_order(
                bundle["slot"]["id"], bundle["guest"]["id"], party_size=party,
                order_type="GROUP" if party > 1 else "SINGLE",
            )
        )
        remaining -= party
    bundle["slot"] = read_slot(bundle["slot"]["id"])
    bundle["run"] = read_run(bundle["run"]["id"])
    bundle["venue"] = read_venue(bundle["venue"]["id"])
    return bundle


def extended_run(requested_extension_days: int = 7, **kwargs: Any) -> Dict[str, Any]:
    """A run carried through one successful extension into EXTENDED.

    The granting producer must not be the producer who created the run, so the
    second producer grants it.
    """
    kwargs.setdefault("option_days", max(requested_extension_days, 30))
    bundle = run_at_demand(**kwargs)
    get_success_data(
        api_client.grant_extension(
            bundle["run"]["id"], f.extension_payload(requested_extension_days),
            PRODUCER_OTHER,
        )
    )
    bundle["run"] = read_run(bundle["run"]["id"])
    bundle["venue"] = read_venue(bundle["venue"]["id"])
    return bundle


def closing_run(bundle: Optional[Dict[str, Any]] = None,
                **kwargs: Any) -> Dict[str, Any]:
    """A run in CLOSING: the shop front is shut and every window is closed out."""
    bundle = bundle if bundle is not None else open_run(**kwargs)
    get_success_data(
        api_client.decide_closure(
            bundle["run"]["id"], f.closure_decision_payload("START_CLOSING"), PRODUCER
        )
    )
    bundle["run"] = read_run(bundle["run"]["id"])
    if "slot" in bundle:
        bundle["slot"] = read_slot(bundle["slot"]["id"])
    return bundle


def closed_run(bundle: Optional[Dict[str, Any]] = None,
               **kwargs: Any) -> Dict[str, Any]:
    """A run carried to the terminal CLOSED, having struck its kit.

    Closure is admissible only with clean books, so this builder is used on a
    world whose orders are all settled or cancelled and whose shifts are none.
    """
    bundle = closing_run(bundle, **kwargs)
    get_success_data(
        api_client.decide_closure(
            bundle["run"]["id"], f.closure_decision_payload("CLOSE"), PRODUCER
        )
    )
    bundle["run"] = read_run(bundle["run"]["id"])
    bundle["kit"] = read_kit(bundle["kit"]["id"])
    bundle["venue"] = read_venue(bundle["venue"]["id"])
    return bundle


def kit_in_transit(module_count: int = 20, **kwargs: Any) -> Dict[str, Any]:
    """A kit struck off a closed run with its score still at or above 60.00.

    A brand-new kit of twenty modules pays 4.00 plus 0.30 a module, so a
    hundred-point kit lands on 90.00 and routes to IN_TRANSIT.
    """
    kwargs.setdefault("kit_overrides", {"module_count": module_count})
    return closed_run(**kwargs)


def kit_refurb_required(initial_condition_score: float = 65.00,
                        module_count: int = 20, **kwargs: Any) -> Dict[str, Any]:
    """A kit struck off a closed run with its score below 60.00.

    Sixty-five points less the ten-point strike charge of a twenty-module kit
    lands on 55.00, which routes the kit to REFURB_REQUIRED and resets its
    localisation posture to PENDING.
    """
    kwargs.setdefault("kit_overrides", {
        "initial_condition_score": initial_condition_score,
        "module_count": module_count,
    })
    return closed_run(**kwargs)


# ─── Tier 5: finalisation and terminal states ───────────────────────────────

def draft_statement(run_id: str, **overrides: Any) -> dict:
    """A royalty statement in DRAFT, priced from the provisional variant.

    The run's version is read immediately before the create, because the
    create's own stale-version guard reads the value the previous hop left.
    """
    return get_success_data(
        api_client.create_statement(
            f.statement_payload(run_id, run_version(run_id), **overrides), LM
        )
    )


def issued_statement(run_id: str, period_start_date: str = "2026-08-01",
                     period_end_date: str = "2026-08-31",
                     finalize_at: str = "2026-09-01T00:00:00Z",
                     **overrides: Any) -> dict:
    """A statement issued after its period has ended.

    Finalisation is admissible only once the clock's calendar date is strictly
    after the period end, so the clock is parked one day past it.
    """
    statement = draft_statement(
        run_id, period_start_date=period_start_date,
        period_end_date=period_end_date, **overrides
    )
    set_clock(finalize_at)
    get_success_data(api_client.finalize_statement(statement["id"], LM))
    return read_statement(statement["id"])


def settled_statement(run_id: str, **kwargs: Any) -> dict:
    """A statement carried to the terminal SETTLED."""
    statement = issued_statement(run_id, **kwargs)
    get_success_data(api_client.settle_statement(statement["id"], LM))
    return read_statement(statement["id"])


def restricted_guest(**kwargs: Any) -> Dict[str, Any]:
    """A guest account driven to RESTRICTED by three recorded no-shows.

    The strike threshold is cumulative and inclusive, so the third no-show is
    the one that restricts the account.  Each no-show needs its own confirmed
    order on a window the clock has already passed.
    """
    bundle = selling_world(**kwargs)
    slot_start = bundle["slot"]["slot_start_utc"]
    slot_end = bundle["slot"]["slot_end_utc"]
    bundle["no_show_orders"] = []
    for _ in range(3):
        order = confirmed_order(
            bundle["slot"]["id"], bundle["guest"]["id"], party_size=1
        )
        bundle["no_show_orders"].append(order)
    # A no-show may only be recorded strictly after fifteen minutes past the
    # window's end, so the clock is moved past that bound once.
    set_clock(_plus_minutes(slot_end, 16))
    for order in bundle["no_show_orders"]:
        get_success_data(
            api_client.record_attendance(
                order["id"], f.attendance_payload("NO_SHOW"), AGENT
            )
        )
    bundle["slot_start_utc"] = slot_start
    bundle["guest"] = read_guest(bundle["guest"]["id"])
    return bundle


def _plus_minutes(instant: str, minutes: int) -> str:
    """Shift an ISO 8601 UTC instant by whole minutes, keeping the Z suffix."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.strptime(instant.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    parsed = parsed.replace(tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plus_hours(instant: str, hours: float) -> str:
    """Shift an ISO 8601 UTC instant by hours, keeping the Z suffix."""
    return _plus_minutes(instant, int(round(hours * 60)))


def park_clock_hours_before(instant: str, hours: float) -> str:
    """Park the clock an exact number of hours before an instant.

    The refund ladder reads the hours remaining without flooring them, so the
    72-hour and 24-hour rungs are only reachable from an exact position.
    """
    target = _plus_hours(instant, -hours)
    set_clock(target)
    return target
