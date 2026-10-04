"""Cyclic state machines: the offer window and the qualification revision loop (PRD 3.2, 3.6)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_backup_offer, assert_qualification,
    reset_clock, advance_clock, build_qualified_household, create_qualification,
    approve_qualification, get_qualification, enroll_bridge_program, fund_program,
    go_live_departing, draft_backup_offer, issue_backup_offer, get_backup_offer,
    record_site_visit, occupy_new_home,
    TEST_USERS, ApiErrorId, LOGICAL_CLOCK_START,
)

COORD = TEST_USERS["coordinator_headers"]


def _offer_ready_scenario():
    """A funded program with the departing home live, offer drafted at the clock start."""
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "9 Departing Way", "appraised_value_cents": 50_000_000,
                   "mortgage_payoff_cents": 20_000_000, "condition_grade": "B"},
        new={"address": "10 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="OPTIMISTIC", target_purchase_price_cents=40_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])
    sc["program"], sc["loan"], sc["qualification"] = program, loan, q
    return sc


def test_backup_offer_cycles_from_issued_through_expiry_back_to_issued(api):
    """PRD section 3.6: "Issuing sets the offer's `expires_at` to `window_start` plus
    `window_days`, and moves it to `ISSUED`."

    PRD section 3.9: "An offer in `ISSUED` expires when the logical clock passes its
    `expires_at`"

    PRD section 3.9: "an `EXPIRED` offer may be reissued when the property is still
    `LISTED`, which sets a fresh `expires_at` of the current clock plus the original
    window"

    Design: Difficulty/non_linear_state_machine/backup_offer_cyclic_expire_extend_reissue
    """
    reset_clock()
    sc = _offer_ready_scenario()
    go_live_departing(sc)
    offer = draft_backup_offer(sc, offer_price_cents=44_000_000, window_days=30,
                               window_start=LOGICAL_CLOCK_START)
    issued = issue_backup_offer(offer["id"])
    assert issued["status"] == "ISSUED"
    assert issued["expires_at"] > issued["window_start"], "expiry sits window_days past the start"

    advance_clock("2026-10-15T00:00:00Z")
    expired = get_backup_offer(offer["id"])
    assert expired["status"] == "EXPIRED", "the clock passed expires_at without a client touch"

    reissued = validate_success(api.extend_backup_offer(offer["id"], COORD), 200)
    assert reissued["status"] == "ISSUED", "an expired offer returns to ISSUED, a cycle"
    assert reissued["expires_at"] != issued["expires_at"], (
        "re-issuing recomputes expires_at from the current clock"
    )


def test_backup_offer_window_cycle_advances_version_at_every_hop(api):
    """PRD section 3.2: "Expiring a qualification is a mutation in its own right and
    advances the qualification's `version`, as does expiration of a backup offer."

    PRD section 2.5: "a state transition caused by the logical clock, or by a cascade from
    another resource, is still a mutation and still refreshes `updated_at` and increments
    `version` on every resource it touches."

    Design: Difficulty/non_linear_state_machine/backup_offer_cyclic_expire_extend_reissue
    """
    reset_clock()
    sc = _offer_ready_scenario()
    go_live_departing(sc)
    offer = draft_backup_offer(sc, offer_price_cents=44_000_000, window_days=30,
                               window_start=LOGICAL_CLOCK_START)
    assert_backup_offer(offer)
    v1 = offer["version"]
    issued = issue_backup_offer(offer["id"])
    v2 = issued["version"]
    assert v2 > v1, "issuing is a mutation"

    advance_clock("2026-10-15T00:00:00Z")
    v3 = get_backup_offer(offer["id"])["version"]
    assert v3 > v2, "clock-driven expiration still increments version"

    extended = validate_success(api.extend_backup_offer(offer["id"], COORD), 200)
    assert extended["version"] > v3, "re-issuing is a mutation"


def test_qualification_revision_returns_approved_record_to_pending(api):
    """PRD section 3.2: "Revision is also permitted on a qualification that has already
    been approved, in which case the record returns to `PENDING` — but only while no
    enrolment has moved past its own opening state; a qualification that has already been
    enrolled and funded can no longer be reopened this way, and the attempt is refused."

    PRD section 3.2: "The coordinator may revise the reading or the target price while the
    record is still open, which re-derives both the capacity and the equity ratio."

    Design: Difficulty/non_linear_state_machine/qualification_revision_pending_cycle
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=10_000_000,
        departing={"address": "13 Departing Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = create_qualification(sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
                             variant_used="CONSERVATIVE", target_purchase_price_cents=50_000_000)
    # equity 30000000, credited ratio 7000 + 1000 = 8000 bps -> 24000000
    assert q["capacity_cents"] == 24_000_000
    approved = approve_qualification(q["id"])
    assert approved["status"] == "APPROVED"

    revised = validate_success(
        api.revise_qualification(q["id"], {"variant_used": "OPTIMISTIC"}, COORD), 200)
    assert revised["status"] == "PENDING", "approval is undone by revision"
    # optimistic ratio 9000 bps -> 27000000
    assert revised["capacity_cents"] == 27_000_000, "capacity is re-derived under the new reading"


def test_qualification_cycle_reapproves_with_the_revised_capacity(api):
    """PRD section 3.2: "A coordinator approves an open qualification to mint the
    capacity"

    PRD section 2.5: "Every entity except one also carries a `version` integer that the
    server increments by one on each mutation".

    Design: Difficulty/non_linear_state_machine/qualification_revision_pending_cycle
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=10_000_000,
        departing={"address": "13 Departing Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = create_qualification(sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
                             variant_used="CONSERVATIVE", target_purchase_price_cents=50_000_000)
    first = approve_qualification(q["id"])
    revised = validate_success(
        api.revise_qualification(q["id"], {"variant_used": "OPTIMISTIC"}, COORD), 200)
    second = approve_qualification(q["id"])

    assert_qualification(second)
    assert second["status"] == "APPROVED"
    assert second["capacity_cents"] == 27_000_000, "the re-approval mints the revised capacity"
    assert first["version"] < revised["version"] < second["version"], (
        "version strictly increases across the revision loop"
    )