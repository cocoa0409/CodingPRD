"""Facility partnership scoring, the grace-credit cycle break and the posture cascade.

The scoring quantities are mutually dependent, so these scenarios pin which tier
the grace credit reads, how far a downward posture transition reaches, and what it
deliberately leaves alone.
"""

from test_helpers import fixtures as fx
from test_helpers import validate_success

EARLIER_AT = "2026-07-20T08:00:00Z"
LATEST_AT = "2026-07-28T08:00:00Z"


def _facility_with_five_clean_referrals(api):
    """Five in-window referrals carrying no missed treatments at all.

    Every intermediate evaluation therefore scores 100, which is what walks the
    facility from its seeded SILVER tier up to GOLD before the trigger.
    """
    center = fx.seed_center(api)
    access = fx.seed_access(api, center["patient_id"])
    referrals = [
        fx.seed_referral(
            api, access["id"], center["facility_id"], missed_treatment_count=0
        )
        for _ in range(5)
    ]
    return center, access, referrals


def _same_day_referral(api, center, access=None, missed_treatment_count=1):
    """A referral triaged SAME_DAY on a declining IN_USE access.

    The 1000 -> 700 decline contributes 36 trend points, the latest flow of 700 adds
    12, the venous pressure of 160 adds 15 and the recirculation of 12.0 adds 10, so
    a single missed treatment carries the total to 79.
    """
    if access is None:
        access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        EARLIER_AT,
        access_flow_ml_min=1000,
        venous_pressure_mmhg=120,
        recirculation_pct=4.0,
    )
    fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        LATEST_AT,
        access_flow_ml_min=700,
        venous_pressure_mmhg=160,
        recirculation_pct=12.0,
    )
    referral = fx.seed_referral(
        api,
        access["id"],
        center["facility_id"],
        missed_treatment_count=missed_treatment_count,
    )
    return access, fx.triage(api, referral["id"])


def test_01_the_grace_credit_reads_the_tier_the_previous_evaluation_persisted(api):
    """The score is 52, not 48, because the grace rate comes from the stored GOLD tier.

    The PRD states: "That circle is broken by reading the tier that the **previous**
    evaluation persisted."

    It also states: "The tier to be used for the grace credit is read out of the
    facility's currently stored `partnership_tier` *before any field is written*."

    With a volume of 5 and the stored GOLD rate of one fifth, the grace credit is
    floor(5 * 0.20) = 1, so 13 raw misses become 12 adjusted misses and the score is
    100 - 4 * 12 = 52. Re-reading the WATCH tier this very evaluation writes would
    give a grace of 0, 13 adjusted misses and a score of 48.

    Design: Difficulty/combinatorial_formula/partnership_score_breaks_its_own_cycle_by_reading_the_previously_persisted_tier
    """
    center, _access, referrals = _facility_with_five_clean_referrals(api)

    before = fx.read_facility(api, center["facility_id"])
    assert before["partnership_score"] == 100
    assert before["partnership_tier"] == "GOLD"
    assert before["referral_volume_window"] == 5
    assert before["raw_missed_count_window"] == 0
    assert before["same_day_honored_window"] == 0

    fx.update_missed_treatments(api, referrals[4]["id"], 13)

    after = fx.read_facility(api, center["facility_id"])
    assert after["referral_volume_window"] == 5
    assert after["raw_missed_count_window"] == 13
    assert after["grace_credit_window"] == 1
    assert after["adjusted_missed_count_window"] == 12
    assert after["same_day_honored_window"] == 0
    assert after["partnership_score"] == 52
    assert after["partnership_tier"] == "WATCH"
    assert after["contract_status"] == "PROBATION"


def test_02_the_probation_drop_holds_every_open_referral_in_a_single_pass(api):
    """All five referrals are held, and the score is not recomputed against them.

    The PRD states: "**On a drop to `PROBATION`**, every referral of that facility
    whose `status` is `SUBMITTED` or `TRIAGED` is moved to `INFO_REQUESTED` with
    `hold_reason` set to `FACILITY_POSTURE_HOLD`, its `info_request_count` increased
    by one, and its `triage_score`, `triage_variant`, `urgency` and `triaged_at`
    cleared back to null — a held referral has lost its triage and must earn it
    again."

    It also states: "Only **one** pass is made."

    The derived rates are integer-scaled: 13 * 100 / 5 is exactly 260, and the
    same-day honour rate is reported as 0 because no in-window referral is SAME_DAY.

    Design: Difficulty/combinatorial_formula/partnership_score_breaks_its_own_cycle_by_reading_the_previously_persisted_tier
    """
    center, _access, referrals = _facility_with_five_clean_referrals(api)

    fx.update_missed_treatments(api, referrals[4]["id"], 13)

    for referral in referrals:
        held = fx.read_referral(api, referral["id"])
        assert held["status"] == "INFO_REQUESTED"
        assert held["hold_reason"] == "FACILITY_POSTURE_HOLD"
        assert held["info_request_count"] == 1

    metrics = validate_success(
        api.get_facility_partnership_metrics(center["facility_id"], fx.ADMIN)
    )
    assert metrics["facility_id"] == center["facility_id"]
    assert metrics["missed_treatments_per_referral_x100"] == 260
    assert metrics["same_day_honor_rate_pct"] == 0
    assert metrics["referral_volume_window"] == 5
    assert metrics["grace_credit_window"] == 1

    # A second pass would have read the WATCH tier it just wrote and landed on 48.
    settled = fx.read_facility(api, center["facility_id"])
    assert settled["partnership_score"] == 52
    assert settled["contract_status"] == "PROBATION"
    assert settled["referral_volume_window"] == 5


def _same_day_case_with_reservation(api):
    """A SAME_DAY case scheduled for the triage date, holding two balloons."""
    center = fx.seed_center(api)
    access, referral = _same_day_referral(api, center, missed_treatment_count=1)
    assert referral["urgency"] == "SAME_DAY"
    assert referral["triage_score"] == 79

    procedure = fx.book_case(
        api,
        referral["id"],
        center["room_id"],
        center["operator_id"],
        referral["version"],
    )
    lot = fx.seed_lot(api, "BALLOON", received_quantity=10)
    usage = fx.reserve_units(api, procedure["id"], lot, 2)
    return center, access, referral, procedure, lot, usage


def test_03_a_suspension_holds_the_referral_and_cancels_the_case_beneath_it(api):
    """One missed-treatment update reaches four hops down from the facility.

    The PRD states: "**On a drop to `SUSPENDED`**, the same hold applies but the
    eligible set widens to include `SCHEDULED` referrals, and two further hops follow."

    It also states: "Every procedure beneath a just-held referral whose
    `clinical_status` is `SCHEDULED` is moved to `CANCELLED` with `cancel_reason` set
    to `FACILITY_POSTURE_HOLD`; and every `RESERVED` device usage on each of those
    cancelled procedures is moved to `RELEASED`, restoring the owning lot's
    `quantity_reserved` while leaving its `quantity_on_hand` untouched."

    Against a volume of 1 the GOLD grace rate yields floor(1 * 0.20) = 0, so fifteen
    raw misses stay fifteen adjusted misses and the score falls from 96 to
    100 - 4 * 15 = 40.

    Design: Difficulty/transitive_cascade/facility_posture_five_hop_chain_holds_referral_cancels_case_and_releases_stock
    """
    center, _access, referral, procedure, _lot, _usage = _same_day_case_with_reservation(api)

    before = fx.read_facility(api, center["facility_id"])
    assert before["partnership_score"] == 96
    assert before["partnership_tier"] == "GOLD"
    assert before["contract_status"] == "ACTIVE"
    assert fx.read_referral(api, referral["id"])["status"] == "SCHEDULED"

    fx.update_missed_treatments(api, referral["id"], 15, center["facility_headers"])

    # Hops 1 and 2: the rescore and the posture drop.
    facility = fx.read_facility(api, center["facility_id"])
    assert facility["referral_volume_window"] == 1
    assert facility["raw_missed_count_window"] == 15
    assert facility["grace_credit_window"] == 0
    assert facility["adjusted_missed_count_window"] == 15
    assert facility["partnership_score"] == 40
    assert facility["partnership_tier"] == "WATCH"
    assert facility["contract_status"] == "SUSPENDED"

    # Hop 3: the hold, which is a hold and not a return to TRIAGED.
    held = fx.read_referral(api, referral["id"])
    assert held["status"] == "INFO_REQUESTED"
    assert held["hold_reason"] == "FACILITY_POSTURE_HOLD"
    assert held["info_request_count"] == 1
    assert held["triage_score"] is None
    assert held["triage_variant"] is None
    assert held["urgency"] is None
    assert held["triaged_at"] is None
    assert held["missed_treatment_count"] == 15

    # Hop 4: the cancellation, attributed to the posture and not to a coordinator.
    cancelled = fx.read_procedure(api, procedure["id"])
    assert cancelled["clinical_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "FACILITY_POSTURE_HOLD"
    assert cancelled["discharged_at"] is None
    assert cancelled["allowed_amount_cents"] == 0


def test_04_the_release_hop_restores_reservations_without_touching_the_shelf(api):
    """The fifth hop is asymmetric, and the chain stops there.

    The PRD states: "Counting from the rescoring itself, that is a five-hop chain:
    rescore, posture drop, referral hold, procedure cancellation, device release."

    A release restores only what was promised, so `quantity_reserved` returns to 0
    while `quantity_on_hand` stays at the ten units received and the lot stays
    AVAILABLE. The chain also stops at the device: the access the referral named keeps
    the DYSFUNCTIONAL status its triage gave it, and the score stays at 40 because the
    referral's own departure from SCHEDULED does not re-run the calculation.

    Design: Difficulty/transitive_cascade/facility_posture_five_hop_chain_holds_referral_cancels_case_and_releases_stock
    """
    center, access, referral, _procedure, lot, usage = _same_day_case_with_reservation(api)

    reserved_lot = fx.read_lot(api, lot["id"])
    assert reserved_lot["quantity_on_hand"] == 10
    assert reserved_lot["quantity_reserved"] == 2
    assert fx.read_usage(api, usage["id"])["state"] == "RESERVED"

    fx.update_missed_treatments(api, referral["id"], 15, center["facility_headers"])

    released = fx.read_usage(api, usage["id"])
    assert released["state"] == "RELEASED"
    assert released["released_at"] is not None
    assert released["consumed_at"] is None
    assert released["quantity"] == 2

    settled_lot = fx.read_lot(api, lot["id"])
    assert settled_lot["quantity_reserved"] == 0
    assert settled_lot["quantity_on_hand"] == 10
    assert settled_lot["status"] == "AVAILABLE"

    assert fx.read_access(api, access["id"])["status"] == "DYSFUNCTIONAL"

    settled = fx.read_facility(api, center["facility_id"])
    assert settled["referral_volume_window"] == 1
    assert settled["partnership_score"] == 40
    assert settled["contract_status"] == "SUSPENDED"
