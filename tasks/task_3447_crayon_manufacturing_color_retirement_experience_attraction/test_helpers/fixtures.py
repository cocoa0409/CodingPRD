"""Composite setup helpers.

The harness restarts the server before every test, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup
calls use the lenient get_success_data() so a setup failure surfaces as a
clear 'Setup failed' message rather than a confusing assertion error.

Identity discipline (segregation of duties, PRD section 2.9): batches are
registered by sm-1 and certified by a DIFFERENT officer (qa-1); formulas are
created/submitted by f-1 and approved by so-1; licensed lines are
created/submitted by bm-1, licensor-approved by the line's licensor_user_id
("lic-1"), and brand-approved by bm-2.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import CLOCK_BOOT_DEFAULT
from .factories import (
    DEFAULTS,
    create_color_payload,
    create_pigment_batch_payload,
    create_formula_payload,
    create_vote_campaign_payload,
    create_spec_payload,
    create_run_payload,
    create_allocation_payload,
    create_licensed_line_payload,
    create_session_payload,
    create_ticket_payload,
    create_vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_licensor_headers,
    make_sourcing_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SOURCING = TEST_USERS["sourcing_headers"]
QA = TEST_USERS["qa_headers"]
QA2 = TEST_USERS["qa2_headers"]
FORMULATOR = TEST_USERS["formulator_headers"]
SAFETY = TEST_USERS["safety_headers"]
LAB = TEST_USERS["lab_headers"]
BRAND = TEST_USERS["brand_headers"]
BRAND2 = TEST_USERS["brand2_headers"]
PLANNER = TEST_USERS["planner_headers"]
BOXOFFICE = TEST_USERS["boxoffice_headers"]
CONSUMER = TEST_USERS["consumer_headers"]


# ---------------------------------------------------------------------------
# Clock and epoch
# ---------------------------------------------------------------------------

def reset_clock():
    """Pin the logical clock to its documented startup instant (PRD 2.4)."""
    return get_success_data(_api.set_clock(CLOCK_BOOT_DEFAULT, ADMIN))


def set_clock(to_iso8601: str):
    return get_success_data(_api.set_clock(to_iso8601, ADMIN))


def run_epoch():
    """Run the operations epoch checkpoint (PRD 3.8). Returns the tally object."""
    return get_success_data(_api.run_epoch(ADMIN))


# ---------------------------------------------------------------------------
# Colors and vote campaigns
# ---------------------------------------------------------------------------

def create_color(name=None, hex_code=None, is_core_curriculum=None) -> dict:
    overrides = {}
    if name is not None:
        overrides["name"] = name
    if hex_code is not None:
        overrides["hex_code"] = hex_code
    if is_core_curriculum is not None:
        overrides["is_core_curriculum"] = is_core_curriculum
    resp = _api.create_color(create_color_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed creating color: {resp.text}"
    return get_success_data(resp)


def get_color(color_id) -> dict:
    return get_success_data(_api.get_color(color_id, ADMIN))


def open_campaign(color_id, kind="INTRODUCTION",
                  opens=DEFAULTS["CAMPAIGN_OPENS"],
                  closes=DEFAULTS["CAMPAIGN_CLOSES"]) -> dict:
    resp = _api.create_vote_campaign(
        color_id, create_vote_campaign_payload(kind=kind, opens_on=opens, closes_on=closes), ADMIN)
    assert resp.status_code == 201, f"Setup failed opening campaign: {resp.text}"
    return get_success_data(resp)


def cast_votes(campaign_id, segment, choice, count=None):
    payload = create_vote_payload(campaign_id, voter_segment=segment, choice=choice)
    if count is not None:
        payload["count"] = count
    resp = _api.cast_vote(payload, CONSUMER)
    assert resp.status_code == 200, f"Setup failed casting votes: {resp.text}"
    return get_success_data(resp)


def list_campaigns(color_id, params=None) -> list:
    return get_success_data(_api.list_vote_campaigns(color_id, ADMIN, params=params))


def pass_introduction(color_id,
                      opens=DEFAULTS["CAMPAIGN_OPENS"],
                      closes=DEFAULTS["CAMPAIGN_CLOSES"],
                      open_clock="2026-09-06T00:00:00Z",
                      close_clock="2026-09-21T00:00:00Z") -> dict:
    """Drive a color PROPOSED -> IN_VOTE -> ACTIVE via a passing campaign."""
    camp = open_campaign(color_id, "INTRODUCTION", opens, closes)
    set_clock(open_clock)
    run_epoch()
    cast_votes(camp["id"], "KIDS", "YES", 20)
    set_clock(close_clock)
    run_epoch()
    return camp


def make_active_color(name="Cerulean", hex_code="#02A4D3", is_core_curriculum=None,
                      **campaign_window) -> dict:
    """Create a color and walk it to ACTIVE. Returns the fresh color read."""
    color = create_color(name, hex_code, is_core_curriculum)
    pass_introduction(color["id"], **campaign_window)
    return get_color(color["id"])


def retire_color(color_id,
                 opens="2026-10-01T00:00:00Z",
                 closes="2026-10-15T23:59:59Z") -> dict:
    """Drive an ACTIVE color through a passing retirement campaign to RETIRED."""
    camp = open_campaign(color_id, "RETIREMENT", opens, closes)
    set_clock("2026-10-02T00:00:00Z")
    run_epoch()
    cast_votes(camp["id"], "KIDS", "YES", 20)
    set_clock("2026-10-16T00:00:00Z")
    run_epoch()
    return camp


# ---------------------------------------------------------------------------
# Pigment batches
# ---------------------------------------------------------------------------

def create_batch(registered_by="sm-1", **overrides) -> dict:
    """Register a pigment batch (QUARANTINE). Default registrar: sm-1."""
    from .test_users import make_sourcing_headers
    resp = _api.create_pigment_batch(
        create_pigment_batch_payload(**overrides), make_sourcing_headers(registered_by))
    assert resp.status_code == 201, f"Setup failed creating batch: {resp.text}"
    return get_success_data(resp)


def certify_batch(batch_id, by="qa-1") -> dict:
    from .test_users import make_qa_headers
    resp = _api.certification_decision(batch_id, {"decision": "CERTIFY"}, make_qa_headers(by))
    assert resp.status_code == 200, f"Setup failed certifying batch: {resp.text}"
    return get_success_data(resp)


def reject_batch(batch_id, by="qa-1", reason="off-spec color") -> dict:
    from .test_users import make_qa_headers
    resp = _api.certification_decision(
        batch_id, {"decision": "REJECT", "reason": reason}, make_qa_headers(by))
    assert resp.status_code == 200, f"Setup failed rejecting batch: {resp.text}"
    return get_success_data(resp)


def create_certified_batch(**overrides) -> dict:
    """Register (sm-1) then certify (qa-1) — SoD-clean. Returns CERTIFIED batch."""
    batch = create_batch(registered_by="sm-1", **overrides)
    return certify_batch(batch["id"], by="qa-1")


# ---------------------------------------------------------------------------
# Formulas and safety tests
# ---------------------------------------------------------------------------

def create_formula(color_id, **overrides) -> dict:
    resp = _api.create_formula(create_formula_payload(color_id, **overrides), FORMULATOR)
    assert resp.status_code == 201, f"Setup failed creating formula: {resp.text}"
    return get_success_data(resp)


def get_formula(formula_id) -> dict:
    return get_success_data(_api.get_formula(formula_id, ADMIN))


def submit_formula(formula_id, by_headers=FORMULATOR) -> dict:
    resp = _api.formula_transition(formula_id, {"action": "SUBMIT"}, by_headers)
    assert resp.status_code == 200, f"Setup failed submitting formula: {resp.text}"
    return get_success_data(resp)


def list_safety_tests(formula_id) -> list:
    return get_success_data(_api.list_safety_tests(formula_id, SAFETY))


def record_test_result(test_id, outcome, notes="clean") -> dict:
    resp = _api.record_safety_test_result(
        test_id, {"outcome": outcome, "result_notes": notes}, LAB)
    assert resp.status_code == 200, f"Setup failed recording test result: {resp.text}"
    return get_success_data(resp)


def pass_latest_safety_test(formula_id) -> dict:
    tests = list_safety_tests(formula_id)
    assert tests, "Setup failed: no safety test exists to pass"
    return record_test_result(tests[-1]["id"], "PASS")


def approve_formula(formula_id, by_headers=SAFETY) -> dict:
    resp = _api.formula_transition(formula_id, {"action": "APPROVE"}, by_headers)
    assert resp.status_code == 200, f"Setup failed approving formula: {resp.text}"
    return get_success_data(resp)


def create_approved_formula(color_id, **overrides) -> dict:
    """Create (f-1) -> SUBMIT (f-1) -> PASS test (lab-1) -> APPROVE (so-1)."""
    formula = create_formula(color_id, **overrides)
    submit_formula(formula["id"])
    pass_latest_safety_test(formula["id"])
    approve_formula(formula["id"])
    return get_formula(formula["id"])


# ---------------------------------------------------------------------------
# Assortment specs
# ---------------------------------------------------------------------------

def create_spec(entries, **overrides) -> dict:
    resp = _api.create_assortment_spec(create_spec_payload(entries, **overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed creating spec: {resp.text}"
    return get_success_data(resp)


def get_spec(spec_id) -> dict:
    return get_success_data(_api.get_assortment_spec(spec_id, ADMIN))


def get_spec_version(spec_id) -> int:
    return get_spec(spec_id)["version"]


# ---------------------------------------------------------------------------
# Production runs
# ---------------------------------------------------------------------------

def create_run(spec_id, batch_id, **overrides) -> dict:
    resp = _api.create_production_run(create_run_payload(spec_id, batch_id, **overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed creating run: {resp.text}"
    return get_success_data(resp)


def advance_run(run_id, packed_counts=None) -> dict:
    payload = {"action": "ADVANCE"}
    if packed_counts is not None:
        payload["packed_counts"] = packed_counts
    resp = _api.production_run_transition(run_id, payload, ADMIN)
    assert resp.status_code == 200, f"Setup failed advancing run: {resp.text}"
    return get_success_data(resp)


def advance_run_to_packing(run_id) -> dict:
    """PLANNED -> MOLDING -> LABELING -> PACKING."""
    advance_run(run_id)
    advance_run(run_id)
    return advance_run(run_id)


def complete_run(run_id, packed_counts) -> dict:
    """The PACKING -> COMPLETED advance carrying packed_counts."""
    return advance_run(run_id, packed_counts=packed_counts)


def list_lots(run_id) -> list:
    return get_success_data(_api.list_inventory_lots(run_id, ADMIN))


def get_run(run_id) -> dict:
    return get_success_data(_api.get_production_run(run_id, ADMIN))


# ---------------------------------------------------------------------------
# The canonical production-capable scenario
# ---------------------------------------------------------------------------

def production_setup(color_name="Cerulean", color_hex="#02A4D3",
                     is_core_curriculum=True, entry_count=8,
                     wholesale_price_cents=1600) -> dict:
    """Color ACTIVE + RETAIL spec {<color>: entry_count} + CERTIFIED batch +
    APPROVED formula. Returns {'color', 'spec', 'batch', 'formula'}.

    The color starts at the logical-clock boot instant; the introduction
    campaign window leaves the clock at 2026-09-21T00:00:00Z.
    """
    color = make_active_color(color_name, color_hex, is_core_curriculum)
    spec = create_spec([{"color_id": color["id"], "count": entry_count}],
                       wholesale_price_cents=wholesale_price_cents)
    batch = create_certified_batch()
    formula = create_approved_formula(color["id"])
    return {"color": color, "spec": spec, "batch": batch, "formula": formula}


def production_setup_with_completed_run(packed_units=1000, planned_boxes=125) -> dict:
    """production_setup + one run driven to COMPLETED with an exact pack.

    Default: 125 planned boxes of an 8-count spec, 1000 units packed ->
    boxes_produced 125, waste 0, one AVAILABLE lot of 125 boxes.
    """
    env = production_setup()
    run = create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=planned_boxes)
    advance_run_to_packing(run["id"])
    packed = [{"color_id": env["color"]["id"], "count": packed_units}]
    run = complete_run(run["id"], packed)
    env["run"] = run
    env["lot"] = list_lots(run["id"])[0]
    return env


# ---------------------------------------------------------------------------
# Retail allocations
# ---------------------------------------------------------------------------

def create_allocation(spec_id, requested_boxes=10, priority_tier="PLATINUM",
                      retailer_name="MegaMart",
                      requested_ship_date=DEFAULTS["SHIP_DATE"]):
    """Create an allocation with a freshly read OCC version. Returns the
    RetailAllocation data (201)."""
    spec_v = get_spec_version(spec_id)
    payload = create_allocation_payload(
        spec_id, spec_v, retailer_name=retailer_name, priority_tier=priority_tier,
        requested_boxes=requested_boxes, requested_ship_date=requested_ship_date)
    resp = _api.create_retail_allocation(payload, PLANNER)
    assert resp.status_code == 201, f"Setup failed creating allocation: {resp.text}"
    return get_success_data(resp)


def allocation_decision(alloc_id, action) -> dict:
    resp = _api.allocation_decision(alloc_id, {"action": action}, PLANNER)
    assert resp.status_code == 200, f"Setup failed allocation decision {action}: {resp.text}"
    return get_success_data(resp)


def get_allocation(alloc_id) -> dict:
    return get_success_data(_api.get_retail_allocation(alloc_id, PLANNER))


# ---------------------------------------------------------------------------
# Licensed lines
# ---------------------------------------------------------------------------

def create_licensed_line(formula_id, **overrides) -> dict:
    resp = _api.create_licensed_line(create_licensed_line_payload(formula_id, **overrides), BRAND)
    assert resp.status_code == 201, f"Setup failed creating licensed line: {resp.text}"
    return get_success_data(resp)


def line_transition(line_id, action, expected_formula_version, headers):
    resp = _api.licensed_line_transition(
        line_id, {"action": action, "expected_formula_version": expected_formula_version}, headers)
    return resp


def line_transition_ok(line_id, action, expected_formula_version, headers) -> dict:
    resp = line_transition(line_id, action, expected_formula_version, headers)
    assert resp.status_code == 200, f"Setup failed line transition {action}: {resp.text}"
    return get_success_data(resp)


def get_line(line_id) -> dict:
    return get_success_data(_api.get_licensed_line(line_id, ADMIN))


def create_approved_licensed_line(formula_id, licensor_user_id="lic-1", **overrides) -> dict:
    """Create (bm-1) -> SUBMIT (bm-1) -> LICENSOR_APPROVE (licensor) ->
    BRAND_APPROVE (bm-2). Returns the fresh APPROVED line read.

    Note: BRAND_APPROVE bumps the formula's licensed_use_count and therefore
    its version by 1, and pins that resulting version on the line.
    """
    frm_v = get_formula(formula_id)["version"]
    line = create_licensed_line(formula_id, licensor_user_id=licensor_user_id, **overrides)
    line_transition_ok(line["id"], "SUBMIT", frm_v, BRAND)
    line_transition_ok(line["id"], "LICENSOR_APPROVE", frm_v,
                       make_licensor_headers(licensor_user_id))
    line_transition_ok(line["id"], "BRAND_APPROVE", frm_v, BRAND2)
    return get_line(line["id"])


# ---------------------------------------------------------------------------
# Attraction sessions and tickets
# ---------------------------------------------------------------------------

def create_session(venue="Hall A", date="2026-10-17T00:00:00Z", start_minute=600,
                   duration_minutes=120, capacity_units=100, base_price_cents=2000,
                   is_charter=None) -> dict:
    overrides = dict(venue_name=venue, session_date=date, start_minute=start_minute,
                     duration_minutes=duration_minutes, capacity_units=capacity_units,
                     base_price_cents=base_price_cents)
    if is_charter is not None:
        overrides["is_charter"] = is_charter
    resp = _api.create_attraction_session(create_session_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed creating session: {resp.text}"
    return get_success_data(resp)


def get_session(session_id) -> dict:
    return get_success_data(_api.get_attraction_session(session_id, ADMIN))


def book_individual(session_id):
    return _api.create_ticket(create_ticket_payload(session_id, kind="INDIVIDUAL"), BOXOFFICE)


def book_group(session_id, group_size, school_name):
    return _api.create_ticket(
        create_ticket_payload(session_id, kind="GROUP", group_size=group_size,
                              school_name=school_name),
        BOXOFFICE)


def book_individual_ok(session_id) -> dict:
    resp = book_individual(session_id)
    assert resp.status_code == 201, f"Setup failed booking individual: {resp.text}"
    return get_success_data(resp)


def book_group_ok(session_id, group_size, school_name) -> dict:
    resp = book_group(session_id, group_size, school_name)
    assert resp.status_code == 201, f"Setup failed booking group: {resp.text}"
    return get_success_data(resp)


def ticket_decision_ok(ticket_id, action) -> dict:
    resp = _api.ticket_decision(ticket_id, {"action": action}, BOXOFFICE)
    assert resp.status_code == 200, f"Setup failed ticket decision {action}: {resp.text}"
    return get_success_data(resp)

def list_session_tickets(session_id, params=None) -> list:
    return get_success_data(_api.list_session_tickets(session_id, ADMIN, params=params))


def find_ticket(session_id, ticket_id) -> dict:
    for t in list_session_tickets(session_id):
        if t["id"] == ticket_id:
            return t
    raise AssertionError(f"ticket {ticket_id} not found in session {session_id}")


def two_color_production_setup() -> dict:
    """Two ACTIVE colors (Cerulean core, Denim non-core) each with an APPROVED
    formula, one CERTIFIED batch, and a 16-box RETAIL spec {Cerulean:8,
    Denim:8} at 3200 cents. Clock ends at 2026-10-11T00:00:00Z.

    The second introduction campaign uses a later, non-overlapping window.
    """
    color1 = make_active_color("Cerulean", "#02A4D3", True)
    color2 = make_active_color(
        "Denim", "#1560BD", None,
        opens="2026-09-25T00:00:00Z", closes="2026-10-10T23:59:59Z",
        open_clock="2026-09-26T00:00:00Z", close_clock="2026-10-11T00:00:00Z")
    spec = create_spec(
        [{"color_id": color1["id"], "count": 8}, {"color_id": color2["id"], "count": 8}],
        name="Duo 16-box", wholesale_price_cents=3200)
    batch = create_certified_batch()
    formula1 = create_approved_formula(color1["id"])
    formula2 = create_approved_formula(
        color2["id"], pigment_recipe=[{"pigment_name": "Prussian Blue", "parts": 2}])
    return {"color1": color1, "color2": color2, "spec": spec, "batch": batch,
            "formula1": formula1, "formula2": formula2}


def two_color_run_at_packing(planned_boxes=10) -> dict:
    """two_color_production_setup + one run advanced to PACKING."""
    env = two_color_production_setup()
    run = create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=planned_boxes)
    advance_run_to_packing(run["id"])
    env["run"] = get_run(run["id"])
    return env
