"""Two chains where each link is caused by the previous link rather than by the
originating call: a dispense that drains a shelf and ends up freezing a
different fitter's reservation, and a supplier quality flag that reaches an
encounter through its fabrication order.
"""

from test_helpers import (
    add_patient,
    add_product,
    add_shelf,
    assert_clinic_posture,
    assert_shelf,
    attest_standards,
    build_practice,
    read_clinic,
    read_encounter,
    read_fab_order,
    read_shelf,
)
from test_helpers import factories as f

COVERED = {"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}


def _three_shelf_clinic(api):
    """One clinic with three spine shelves: two single-unit shelves whose par
    minimum is 1 unit, and a well-stocked third shelf whose par minimum is 4.

    The second shelf has already been emptied by a delivered encounter, so the
    clinic sits at a restricted posture with one stocked-out shelf, and a third
    encounter is reserved against the untouched shelf.
    """
    practice = build_practice(api, par_level={"par_min_qty": 1}, received_qty=1)
    product_two = add_product(
        practice,
        f.product_payload(
            practice.supplier_id,
            hcpcs_code="L0464",
            description="TLSO brace, prefabricated",
            same_or_similar_group="TLSO_BRACE",
            allowed_amount_cents=30000,
            cash_price_cents=18000,
            unit_cost_cents=9000,
        ),
    )
    shelf_two = add_shelf(practice, product_two["id"], received_qty=1, par_min_qty=1)
    product_three = add_product(
        practice, f.cervical_collar_product_payload(practice.supplier_id)
    )
    shelf_three = add_shelf(practice, product_three["id"], received_qty=10, par_min_qty=4)
    patient_two = add_patient(practice, full_name="Joel Pike")
    patient_three = add_patient(practice, full_name="Nia Frost")

    assert_clinic_posture(
        read_clinic(api, practice.clinic_id), dispensing_status="ACTIVE", stockout_par_level_count=0
    )

    encounter_two = practice.delivered_encounter(
        coverage=COVERED,
        par_level_id=shelf_two["id"],
        product_id=product_two["id"],
        patient_id=patient_two["id"],
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status="RESTRICTED",
        stockout_par_level_count=1,
    )

    encounter_three = practice.reserved_encounter(
        coverage=COVERED,
        par_level_id=shelf_three["id"],
        product_id=product_three["id"],
        patient_id=patient_three["id"],
    )
    reserved = read_encounter(api, encounter_three)
    assert reserved["clinical_status"] == "RESERVED"
    assert reserved["compliance_hold"] is False

    encounter_one = practice.fitted_encounter(
        coverage=COVERED,
        start_at="2026-08-01T11:00:00Z",
        end_at="2026-08-01T11:30:00Z",
    )
    assert read_shelf(api, practice.par_level_id)["stock_posture"] == "OK"
    return practice, {
        "one": encounter_one,
        "two": encounter_two,
        "three": encounter_three,
        "shelf_two": shelf_two["id"],
        "shelf_three": shelf_three["id"],
    }


def test_dispense_empties_a_shelf_and_the_chain_reaches_a_sibling_reservation(api):
    """Draining the second single-unit shelf takes that shelf to a stockout, the
    stockout recount takes the clinic to a suspended posture, and the suspension
    is what places the hold on another fitter's reserved encounter.

    PRD: "Fourth, a clinic transition into `SUSPENDED` sets `compliance_hold` to
    true and `hold_reason` to `CLINIC_SUSPENDED` on every **other** encounter of
    that clinic whose `clinical_status` is `RESERVED` — this is the intended
    serialisation point between one fitter emptying a shelf and another fitter's
    in-flight reservation, and each affected encounter has its own `version`
    advanced."

    Design: Difficulty/transitive_cascade/dispense_drains_shelf_cascades_par_posture_clinic_suspension_sibling_hold
    """
    practice, ids = _three_shelf_clinic(api)

    practice.dispense(ids["one"])

    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=0,
        reserved_qty=0,
        stock_posture="STOCKOUT",
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status="SUSPENDED",
        stockout_par_level_count=2,
    )
    held = read_encounter(api, ids["three"])
    assert held["compliance_hold"] is True
    assert held["hold_reason"] == "CLINIC_SUSPENDED"
    assert held["clinical_status"] == "RESERVED"


def test_the_suspension_hold_reaches_only_reserved_siblings(api):
    """The last link of the chain is scoped: the delivered encounters keep a clear
    compliance flag and the untouched third shelf keeps its stock and its posture.

    PRD: "`CLINIC_SUSPENDED` is stamped when the encounter's clinic falls into a
    suspended dispensing posture: the suspension sets `compliance_hold` to true and
    `hold_reason` to `CLINIC_SUSPENDED` on every **other** encounter of that clinic
    whose clinical dimension currently sits at `RESERVED`."

    Design: Difficulty/transitive_cascade/dispense_drains_shelf_cascades_par_posture_clinic_suspension_sibling_hold
    """
    practice, ids = _three_shelf_clinic(api)

    delivered = practice.dispense(ids["one"])

    assert delivered["compliance_hold"] is False
    assert delivered["patient_responsibility_cents"] == 10300
    assert read_encounter(api, ids["two"])["compliance_hold"] is False
    assert_shelf(
        read_shelf(api, ids["shelf_three"]),
        on_hand_qty=10,
        reserved_qty=1,
        stock_posture="OK",
    )
    assert read_shelf(api, ids["shelf_two"])["stock_posture"] == "STOCKOUT"


def _order_in_fabrication(api):
    """A custom fabrication order accepted into fabrication for an encounter that
    is awaiting its device, with the supplier off quality hold."""
    practice = build_practice(api, product_factory=f.custom_afo_product_payload, with_shelf=False)
    encounter_id = practice.documented_encounter()
    order = practice.place_fab_order(encounter_id)
    accepted = practice.fabrication_event(order["id"], "ACCEPT_ORDER")
    assert accepted["status"] == "IN_FABRICATION"
    assert read_encounter(api, encounter_id)["compliance_hold"] is False
    return practice, encounter_id, order["id"]


def test_raising_a_supplier_quality_hold_reaches_the_encounter_through_its_order(api):
    """Raising the flag on the supplier moves its in-fabrication order into a
    supplier hold, and it is that order's status change that places the hold on
    the order's encounter.

    PRD: "`SUPPLIER_QUALITY_HOLD` is stamped through the fabrication chain: raising
    a supplier's quality hold moves every one of that supplier's fabrication orders
    that is currently submitted, in fabrication, or awaiting an adjustment into a
    supplier-hold state, and each such order in turn sets `compliance_hold` to true
    and `hold_reason` to `SUPPLIER_QUALITY_HOLD` on its own encounter."

    Design: Difficulty/transitive_cascade/supplier_quality_hold_cascades_fab_order_hold_then_encounter_compliance_hold
    """
    practice, encounter_id, order_id = _order_in_fabrication(api)

    supplier = attest_standards(api, practice.supplier_id, attested=True, quality_hold=True)

    assert supplier["quality_hold"] is True
    assert supplier["dmepos_standards_attested"] is True
    assert read_fab_order(api, order_id)["status"] == "SUPPLIER_HOLD"
    held = read_encounter(api, encounter_id)
    assert held["compliance_hold"] is True
    assert held["hold_reason"] == "SUPPLIER_QUALITY_HOLD"
    assert held["clinical_status"] == "AWAITING_DEVICE"


def test_clearing_the_supplier_quality_hold_runs_the_same_chain_backwards(api):
    """Clearing the flag returns the order to fabrication and clears the hold that
    the flag had placed on the encounter, without disturbing the order's rework
    count or its delivery stamp.

    PRD: "Both chains reverse: an improvement in the clinic's posture clears
    `compliance_hold` and `hold_reason` on that clinic's encounters whose reason was
    `CLINIC_SUSPENDED`, and clearing a supplier's quality hold returns its held
    orders to fabrication and clears `compliance_hold` where the reason was
    `SUPPLIER_QUALITY_HOLD`."

    Design: Difficulty/transitive_cascade/supplier_quality_hold_cascades_fab_order_hold_then_encounter_compliance_hold
    """
    practice, encounter_id, order_id = _order_in_fabrication(api)
    attest_standards(api, practice.supplier_id, attested=True, quality_hold=True)
    assert read_fab_order(api, order_id)["status"] == "SUPPLIER_HOLD"

    supplier = attest_standards(api, practice.supplier_id, attested=True, quality_hold=False)

    assert supplier["quality_hold"] is False
    assert supplier["dmepos_standards_attested"] is True
    order = read_fab_order(api, order_id)
    assert order["status"] == "IN_FABRICATION"
    assert order["adjustment_rounds"] == 0
    assert order["first_delivered_at"] is None
    cleared = read_encounter(api, encounter_id)
    assert cleared["compliance_hold"] is False
    assert cleared["hold_reason"] is None
