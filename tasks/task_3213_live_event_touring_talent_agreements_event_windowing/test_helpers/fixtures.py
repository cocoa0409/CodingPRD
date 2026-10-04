"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because each test runs against a freshly restarted server with an
empty database and the logical clock pinned at 2026-09-01T00:00:00Z.

Note on wellness: the PRD (§3.1) pins a fresh talent's wellness_score at the
floor of 0.00 with booking_mode UNBOOKABLE, and §3.6 raises wellness only via
fulfilled bookings. Fixtures below therefore never assume a fresh talent can
be booked; helpers that need a bookable talent only express the reachability
pattern, and tests that depend on a reachable BOOKABLE talent are handled by
the two-condition PRD filter at the test layer.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_talent_payload,
    create_agreement_payload,
    create_arena_payload,
    create_event_payload,
    create_storyline_payload,
    create_chapter_payload,
    create_streaming_partner_payload,
    create_territory_right_payload,
    create_distribution_window_payload,
    create_merch_sale_payload,
    create_royalty_statement_payload,
    create_medical_case_payload,
    create_medical_evaluation_payload,
    create_medical_clearance_payload,
    create_visa_case_payload,
    create_broadcast_anchor_payload,
)
from .test_users import TEST_USERS

TR = TEST_USERS["talent_relations_headers"]
CA = TEST_USERS["contract_admin_headers"]
TP = TEST_USERS["tour_planner_headers"]
SE = TEST_USERS["storyline_editor_headers"]
DM = TEST_USERS["distribution_manager_headers"]
MO = TEST_USERS["merch_ops_headers"]
MD = TEST_USERS["medic_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


# ---------------------------------------------------------------- talents
def create_talent(**overrides):
    """Create a fresh talent. Returns the talent dict."""
    resp = api_client.create_talent(create_talent_payload(**overrides), TR)
    return get_success_data(resp)


# ---------------------------------------------------------------- agreements
def create_draft_agreement(talent_id, **overrides):
    resp = api_client.create_agreement(create_agreement_payload(talent_id, **overrides), CA)
    return get_success_data(resp)


def activate_agreement(agreement):
    """Activate a DRAFT agreement under its current OCC version. Returns the
    activated agreement dict."""
    resp = api_client.activate_agreement(agreement["id"], agreement["version"], CA)
    return get_success_data(resp)


def create_and_activate_agreement(talent_id, **overrides):
    """Draft + activate an agreement. Returns the ACTIVE agreement dict."""
    return activate_agreement(create_draft_agreement(talent_id, **overrides))


# ---------------------------------------------------------------- arenas / events
def create_arena(**overrides):
    resp = api_client.create_arena(create_arena_payload(**overrides), TP)
    return get_success_data(resp)


def create_event(arena_id, **overrides):
    resp = api_client.create_event(create_event_payload(arena_id, **overrides), TP)
    return get_success_data(resp)


def lock_event(event):
    """Lock a SCHEDULED event under its current OCC version."""
    resp = api_client.lock_event(event["id"], event["version"], TP)
    return get_success_data(resp)


def complete_event(event_id):
    resp = api_client.complete_event(event_id, TP)
    return get_success_data(resp)


def cancel_event(event_id):
    resp = api_client.cancel_event(event_id, TP)
    return get_success_data(resp)


# ---------------------------------------------------------------- storylines / chapters
def create_storyline(**overrides):
    resp = api_client.create_storyline(create_storyline_payload(**overrides), SE)
    return get_success_data(resp)


def create_chapter(storyline_id, event_id):
    resp = api_client.create_chapter(create_chapter_payload(storyline_id, event_id), SE)
    return get_success_data(resp)


def activate_storyline(storyline_id):
    resp = api_client.activate_storyline(storyline_id, SE)
    return get_success_data(resp)


def create_active_storyline_with_chapters(event_ids, **storyline_overrides):
    """Storyline + one PLANNED chapter per event + activate.
    Returns (storyline, [chapters])."""
    storyline = create_storyline(**storyline_overrides)
    chapters = [create_chapter(storyline["id"], ev_id) for ev_id in event_ids]
    storyline = activate_storyline(storyline["id"])
    return storyline, chapters


def create_shelved_storyline(arena_id, dates=("2026-09-05", "2026-09-06", "2026-09-07")):
    """ACTIVE storyline with one chapter per event, then cancel all events so
    gap_count reaches 3 and the storyline shelves. Returns (storyline, chapters, events)."""
    events = [create_event(arena_id, event_date=d, name=f"SHELF-{d}") for d in dates]
    storyline, chapters = create_active_storyline_with_chapters([e["id"] for e in events])
    for e in events:
        cancel_event(e["id"])
    storyline = get_success_data(api_client.get_storyline(storyline["id"], SE))
    return storyline, chapters, events


# ---------------------------------------------------------------- distribution
def create_streaming_partner(**overrides):
    resp = api_client.create_streaming_partner(create_streaming_partner_payload(**overrides), DM)
    return get_success_data(resp)


def create_territory_right(partner_id, **overrides):
    resp = api_client.create_territory_right(create_territory_right_payload(partner_id, **overrides), DM)
    return get_success_data(resp)


def create_distribution_window(event_id, partner_id, **overrides):
    resp = api_client.create_distribution_window(
        create_distribution_window_payload(event_id, partner_id, **overrides), DM)
    return get_success_data(resp)


def setup_premium_event_with_spanning_right(arena_id=None, event_date="2026-09-20",
                                            start_time="20:00", end_time="23:00",
                                            right_window=("2026-09-01", "2026-10-01"),
                                            partner_name="DistCo", partner_code="DC"):
    """PREMIUM event + ACTIVE partner + non-exclusive territory right spanning
    the event dates. Returns (event, partner, right)."""
    if arena_id is None:
        arena_id = create_arena()["id"]
    event = create_event(arena_id, event_type="PREMIUM", name="PE",
                         event_date=event_date, start_time=start_time, end_time=end_time)
    partner = create_streaming_partner(name=partner_name, partner_code=partner_code)
    right = create_territory_right(partner["id"], window_start_date=right_window[0],
                                   window_end_date=right_window[1])
    return event, partner, right


# ---------------------------------------------------------------- medical
def create_medical_case(talent_id, **overrides):
    resp = api_client.create_medical_case(create_medical_case_payload(talent_id, **overrides), MD)
    return get_success_data(resp)


def add_evaluation(case_id, evaluator_id, recommends_clearance=True, findings="ok"):
    resp = api_client.create_medical_evaluation(
        case_id,
        create_medical_evaluation_payload(evaluator_id,
                                          recommends_clearance=recommends_clearance,
                                          findings=findings),
        MD)
    return get_success_data(resp)


def clear_case(case_id, cleared_by):
    """Issue clearance; requires >=2 distinct recommending evaluators and a
    clearing medic different from every evaluator (PRD §3.10)."""
    resp = api_client.create_medical_clearance(
        case_id, create_medical_clearance_payload(cleared_by), MD)
    return get_success_data(resp)


def create_case_with_recommending_evals(talent_id, evaluators=("medic-m1", "medic-m3")):
    """OPEN medical case with len(evaluators) recommending evaluations from
    distinct evaluator ids. Returns (case, [evaluations])."""
    case = create_medical_case(talent_id)
    evals = [add_evaluation(case["id"], ev) for ev in evaluators]
    return case, evals


def create_cleared_case(talent_id, evaluators=("medic-m1", "medic-m3"), cleared_by="medic-m2"):
    """Case cleared under the segregation-of-duties protocol.
    Returns (case, clearance)."""
    case, _ = create_case_with_recommending_evals(talent_id, evaluators)
    clearance = clear_case(case["id"], cleared_by)
    case = get_success_data(api_client.get_medical_case(case["id"], MD))
    return case, clearance


# ---------------------------------------------------------------- visas
def create_visa_case(talent_id, **overrides):
    resp = api_client.create_visa_case(create_visa_case_payload(talent_id, **overrides), LC)
    return get_success_data(resp)


def submit_visa_case(case_id):
    resp = api_client.submit_visa_case(case_id, LC)
    return get_success_data(resp)


def grant_visa_case(case_id):
    resp = api_client.grant_visa_case(case_id, LC)
    return get_success_data(resp)


def create_granted_visa(talent_id, **overrides):
    case = create_visa_case(talent_id, **overrides)
    submit_visa_case(case["id"])
    return grant_visa_case(case["id"])


# ---------------------------------------------------------------- clock
def advance_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, CA)
    return get_success_data(resp)


# ---------------------------------------------------------------- misc
def create_broadcast_anchor(**overrides):
    resp = api_client.create_broadcast_anchor(create_broadcast_anchor_payload(**overrides), TP)
    return get_success_data(resp)


def create_merch_sale(event_id, talent_id, **overrides):
    resp = api_client.create_merch_sale(create_merch_sale_payload(event_id, talent_id, **overrides), MO)
    return get_success_data(resp)


def create_royalty_statement(talent_id, **overrides):
    resp = api_client.create_royalty_statement(
        create_royalty_statement_payload(talent_id, **overrides), CA)
    return get_success_data(resp)


def get_talent(talent_id):
    return get_success_data(api_client.get_talent(talent_id, TR))


def get_agreement(agreement_id):
    return get_success_data(api_client.get_agreement(agreement_id, CA))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, TP))


def get_storyline(storyline_id):
    return get_success_data(api_client.get_storyline(storyline_id, SE))


def get_event(event_id):
    return get_success_data(api_client.get_event(event_id, TP))
