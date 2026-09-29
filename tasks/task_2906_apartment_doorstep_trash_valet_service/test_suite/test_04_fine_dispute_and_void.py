"""The bounded dispute loop and the compensating void of a tag."""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_resident_headers,
    validate_error,
)


def _community_with_one_tenant(name):
    return fixtures.build_active_community(
        name=name,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
    )


def _contamination_fine(world, service_date):
    """One recycling-contamination scan on its own night, and the fine it drew."""
    _, route = fixtures.add_scan_ready_night(world, service_date)
    scan = fixtures.record_scan(
        route["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type="RECYCLING_CONTAMINATION",
    )
    return scan, fixtures.find_fine_for_scan(scan["id"])


# --------------------------------------------------------------------------
# The dispute loop is cyclic and bounded
# --------------------------------------------------------------------------
def _fine_upheld_twice(name="Aspen Mews"):
    """Walk ASSESSED -> DISPUTED -> UPHELD -> DISPUTED -> UPHELD."""
    world = _community_with_one_tenant(name)
    scan, fine = _contamination_fine(world, "2026-09-01")
    resident_id = world["residents"][101]["id"]
    property_id = world["property"]["id"]
    fixtures.dispute_fine(resident_id, fine["id"], "The bin was not mine")
    fixtures.adjudicate_fine(property_id, fine["id"], "UPHELD")
    fixtures.dispute_fine(resident_id, fine["id"], "Second look please")
    fixtures.adjudicate_fine(property_id, fine["id"], "UPHELD")
    world["scan"] = scan
    world["fine"] = fine
    return world


def test_upheld_is_re_enterable_so_the_second_dispute_is_admitted():
    """The loop runs twice before the budget is spent, ending at UPHELD round 2.

    PRD 3.6: "`UPHELD` is **not** terminal: it is re-enterable input to the
    loop, so a resident with round budget left may dispute again, giving the
    sequence `ASSESSED → DISPUTED → UPHELD → DISPUTED → UPHELD` before the
    budget is spent."

    Design: Difficulty/non_linear_state_machine/fine_dispute_cycle_reenters_disputed_twice_then_exhausts_round_budget
    """
    world = _community_with_one_tenant("Aspen Mews")
    scan, fine = _contamination_fine(world, "2026-09-01")
    resident_id = world["residents"][101]["id"]
    property_id = world["property"]["id"]
    assert fine["status"] == "ASSESSED"
    assert fine["dispute_round"] == 0

    first_dispute = fixtures.dispute_fine(resident_id, fine["id"], "The bin was not mine")
    assert first_dispute["status"] == "DISPUTED"
    assert first_dispute["dispute_round"] == 1

    first_ruling = fixtures.adjudicate_fine(property_id, fine["id"], "UPHELD")
    assert first_ruling["status"] == "UPHELD"
    assert first_ruling["dispute_round"] == 1

    second_dispute = fixtures.dispute_fine(resident_id, fine["id"], "Second look please")
    assert second_dispute["status"] == "DISPUTED"
    assert second_dispute["dispute_round"] == 2

    second_ruling = fixtures.adjudicate_fine(property_id, fine["id"], "UPHELD")
    assert second_ruling["status"] == "UPHELD"
    assert second_ruling["dispute_round"] == 2
    assert fixtures.read_resident(resident_id)["fines_outstanding_cents"] == 2500


def test_a_third_dispute_exhausts_the_round_budget():
    """With the counter at two the loop refuses to be re-entered.

    PRD 3.6: "A dispute is permitted only while `dispute_round` is still below
    two; a third attempt is refused with `ERR_DISPUTE_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/fine_dispute_cycle_reenters_disputed_twice_then_exhausts_round_budget
    """
    world = _fine_upheld_twice()
    resident_id = world["residents"][101]["id"]

    response = api_client.dispute_fine(
        world["fine"]["id"],
        factories.dispute_payload("One more time"),
        make_resident_headers(resident_id),
    )

    validate_error(response, ApiErrorId.ERR_DISPUTE_ROUNDS_EXHAUSTED.value, 409)
    unchanged = fixtures.read_fine(world["fine"]["id"])
    assert unchanged["status"] == "UPHELD"
    assert unchanged["dispute_round"] == 2
    assert fixtures.read_resident(resident_id)["fines_outstanding_cents"] == 2500


def test_the_disputed_fine_is_argued_without_touching_the_balance():
    """A dispute moves the state only; the money stays outstanding throughout.

    PRD 3.6: "The fine moves to `DISPUTED`, `dispute_round` increases by one,
    and the balance is deliberately **not** touched: a disputed fine remains
    outstanding while it is argued."

    Design: Difficulty/non_linear_state_machine/fine_dispute_cycle_reenters_disputed_twice_then_exhausts_round_budget
    """
    world = _community_with_one_tenant("Aspen Mews")
    _, fine = _contamination_fine(world, "2026-09-01")
    resident_id = world["residents"][101]["id"]
    before = fixtures.read_resident(resident_id)

    fixtures.dispute_fine(resident_id, fine["id"], "The bin was not mine")

    after = fixtures.read_resident(resident_id)
    assert after["fines_outstanding_cents"] == before["fines_outstanding_cents"] == 2500
    assert (
        after["fines_assessed_this_period_cents"]
        == before["fines_assessed_this_period_cents"]
        == 2500
    )


# --------------------------------------------------------------------------
# Voiding a tag unwinds the ledger but not the consumed cap headroom
# --------------------------------------------------------------------------
def _two_fined_contaminations(name="Laurel Court"):
    world = _community_with_one_tenant(name)
    first_scan, first_fine = _contamination_fine(world, "2026-09-01")
    second_scan, second_fine = _contamination_fine(world, "2026-09-02")
    world["first"] = (first_scan, first_fine)
    world["second"] = (second_scan, second_fine)
    return world


def test_voiding_a_tag_voids_its_fine_and_unwinds_both_ledgers():
    """The 7500 leaves the resident balance and the community's pending revenue.

    PRD 3.6: "every fine resting on that scan whose `status` is `ASSESSED`,
    `DISPUTED` or `UPHELD` moves to `VOIDED`, and each of those transitions in
    turn subtracts that fine's `amount_cents` from the resident's
    `fines_outstanding_cents` and from the community's
    `pending_fine_revenue_cents`; if the resident's balance thereby falls below
    the delinquency threshold, `collections_status` returns `DELINQUENT →
    CURRENT` and the community's `delinquent_resident_count` drops by one."

    Design: Difficulty/compensating_invariant/void_tag_unwinds_fine_ledger_without_restoring_monthly_cap_headroom
    """
    world = _two_fined_contaminations()
    second_scan, second_fine = world["second"]

    voided_scan = fixtures.void_tag(
        world["property"]["id"], second_scan["id"], "Tagged the wrong door"
    )

    assert voided_scan["tag_status"] == "VOIDED"
    voided_fine = fixtures.read_fine(second_fine["id"])
    assert voided_fine["status"] == "VOIDED"
    assert voided_fine["amount_cents"] == 7500, (
        "the fine keeps the amount it was assessed at; only its status moves"
    )
    resident = fixtures.read_resident(world["residents"][101]["id"])
    assert resident["fines_outstanding_cents"] == 2500
    assert resident["collections_status"] == "CURRENT"
    prop = fixtures.read_property(world["property"]["id"])
    assert prop["pending_fine_revenue_cents"] == 2500
    assert prop["delinquent_resident_count"] == 0


def test_voiding_a_tag_does_not_return_the_monthly_cap_headroom():
    """The period total stays at 10000 so a waiver cannot reset the ceiling.

    PRD 3.6: "`fines_assessed_this_period_cents` is untouched by any of this."

    Design: Difficulty/compensating_invariant/void_tag_unwinds_fine_ledger_without_restoring_monthly_cap_headroom
    """
    world = _two_fined_contaminations()
    first_scan, first_fine = world["first"]
    second_scan, _ = world["second"]

    fixtures.void_tag(world["property"]["id"], second_scan["id"], "Tagged the wrong door")

    resident = fixtures.read_resident(world["residents"][101]["id"])
    assert resident["fines_assessed_this_period_cents"] == 10000
    surviving_scan = fixtures.read_scan(first_scan["id"])
    assert surviving_scan["tag_status"] == "FINED"
    surviving_fine = fixtures.read_fine(first_fine["id"])
    assert surviving_fine["status"] == "ASSESSED"
    assert surviving_fine["amount_cents"] == 2500
