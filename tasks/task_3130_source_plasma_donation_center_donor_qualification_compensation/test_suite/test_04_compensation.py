"""Compensation: dual-variant reconciliation, tiers, promo, abort, ytd, 1099."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_center_with_schedule,
    make_cleared_screening,
    make_donation,
    make_donor,
    record_pass_sub_record,
    run_completed_donation,
    set_clock,
    validate_paginated,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import get_payment
from test_helpers.test_users import make_recorder_headers, make_screener_headers


def _setup_one_completed_with_promo(promo_overrides):
    """Center with a promo schedule; donor with one completed donation and a
    second donation visit scheduled for 09-04, clock at 09-04 09:30."""
    set_clock("2026-09-01T09:00:00Z")
    center, schedule = make_center_with_schedule(**promo_overrides)
    donor = make_donor(center)
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    set_clock("2026-09-04T09:00:00Z")
    s2 = make_cleared_screening(donor, center, "2026-09-04T08:00:00Z")
    dv2 = make_donation(donor, center, s2, "2026-09-04T09:30:00Z")
    set_clock("2026-09-04T09:30:00Z")
    return center, schedule, donor, dv2


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc:
# promo_optimistic_vs_pessimistic_variant_divergence (2 tests)
# ---------------------------------------------------------------------------

def test_promo_provisional_variant_is_optimistic(api):
    """PRD §3.8: "In the `PROVISIONAL` variant, `promo_cents` equals
    `promo_bonus_cents` when the count of in-window completions excluding this
    visit, plus one for this visit, is at least
    `promo_qualifying_donation_count` **and** no other CompensationPayment for
    this donor on the same `schedule_id` is already `FINALIZED` with a
    positive `promo_cents`." and "The provisional variant is deliberately
    optimistic — it assumes the qualifying count will be reached".

    Design: Difficulty/dual_variant_calc/promo_optimistic_vs_pessimistic_variant_divergence
    """
    center, _, donor, dv2 = _setup_one_completed_with_promo(
        {
            "promo_code": "OCTBOOST",
            "promo_bonus_cents": 2000,
            "promo_qualifying_donation_count": 2,
        }
    )
    get_success_data(api.check_in(dv2["id"], TEST_USERS["phlebotomist_headers"]))
    payment = get_payment(dv2["id"])
    assert payment["variant"] == "PROVISIONAL"
    assert payment["payment_status"] == "PROVISIONAL"
    # window excluding this visit = 1, +1 = 2 >= qualifying count 2
    assert payment["promo_cents"] == 2000
    assert payment["base_cents"] == 2500, "ordinal 1 -> base_cents_second_donation"
    assert payment["net_cents"] == 4500


def test_promo_final_variant_collapses_to_zero_on_abort(api):
    """PRD §3.8: "the final variant is pessimistic and requires the actual
    count" and "`promo_cents` is always 0 for an aborted visit, and
    `net_cents` equals the abort amount". PRD §3.8: "If `actual_volume_ml`
    is null — meaning the reaction occurred while the visit was still
    `IN_PROGRESS` before any collection was recorded — the abort amount is
    0." and "The payment's `payment_status` transitions to `FINALIZED` with
    that net, and `variant` transitions to `FINAL`."

    Design: Difficulty/dual_variant_calc/promo_optimistic_vs_pessimistic_variant_divergence
    """
    center, _, donor, dv2 = _setup_one_completed_with_promo(
        {
            "promo_code": "OCTBOOST",
            "promo_bonus_cents": 2000,
            "promo_qualifying_donation_count": 2,
        }
    )
    get_success_data(api.check_in(dv2["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api.record_adverse_reaction(
            dv2["id"],
            {
                "severity": "MILD",
                "reaction_code": "VASOVAGAL",
                "observed_at": "2026-09-04T09:30:00Z",
                "notes": "mild vasovagal before needle insert",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    payment = get_payment(dv2["id"])
    assert payment["variant"] == "FINAL"
    assert payment["payment_status"] == "FINALIZED"
    assert payment["promo_cents"] == 0
    # abort before any collection: actual_volume_ml null -> abort amount 0
    assert payment["net_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc:
# plasma_volume_snapshot_vs_live_weight_divergence (2 tests)
# ---------------------------------------------------------------------------

def test_programmed_volume_snapshot_frozen_at_check_in(api):
    """PRD §3.4: "Once written, `programmed_volume_ml` is **frozen** for the
    life of the visit: a subsequent physical exam that updates `weight_kg`
    does not retroactively alter the visit's programmed volume."

    Design: Difficulty/dual_variant_calc/plasma_volume_snapshot_vs_live_weight_divergence
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    checked = get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked["programmed_volume_ml"] == 690, "72.5 kg in [68.0, 79.0) band"

    # A later screening refreshes the donor's weight to 80.0 kg.
    s2 = get_success_data(
        api.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-04T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    from test_helpers.factories import physical_exam_payload
    get_success_data(
        api.record_sub_record(
            s2["id"], {"record_type": "IDENTITY", "payload": {"document_number": "TXDL-883491"}},
            make_recorder_headers("rec-01"),
        )
    )
    get_success_data(
        api.record_sub_record(
            s2["id"],
            {"record_type": "PHYSICAL_EXAM", "payload": physical_exam_payload(weight_kg=80.0)},
            make_recorder_headers("rec-01"),
        )
    )
    after = get_success_data(api.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert after["programmed_volume_ml"] == 690, "snapshot stays frozen after re-weigh"
    assert after["visit_status"] == "IN_PROGRESS"


def test_live_weight_refreshed_by_later_exam_diverges_from_snapshot(api):
    """PRD §3.4: "A physical-exam write has the additional side effect of
    refreshing the donor's `weight_kg` from the exam's payload value" (§3.3)
    and "a distinct hypothetical variant — computed on the fly from the
    donor's current `weight_kg` whenever a client asks what a new visit would
    program — legitimately diverges from the snapshot variant when weight has
    moved since the older visit's check-in" (§3.4).

    Design: Difficulty/dual_variant_calc/plasma_volume_snapshot_vs_live_weight_divergence
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    checked = get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    assert checked["programmed_volume_ml"] == 690

    s2 = get_success_data(
        api.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-04T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    from test_helpers.factories import physical_exam_payload
    get_success_data(
        api.record_sub_record(
            s2["id"],
            {"record_type": "PHYSICAL_EXAM", "payload": physical_exam_payload(weight_kg=80.0)},
            make_recorder_headers("rec-01"),
        )
    )
    d = get_success_data(api.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["weight_kg"] == 80.0, "live weight moved with the new exam"
    # Per the PRD band rule (79.0 <= 80.0 < 110.0), a NEW visit would program
    # 825 mL now — the hypothetical variant diverges from the frozen 690.
    assert 825 != checked["programmed_volume_ml"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc:
# base_compensation_provisional_vs_final_cross_visit_divergence (2 tests)
# ---------------------------------------------------------------------------

def _setup_cross_visit_race():
    """dvA and dvB both checked in (beds 0/1) with PROVISIONAL base 3000;
    B then completes before A."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    s_a = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z", recorder_id="rec-01")
    dv_a = make_donation(donor, center, s_a, "2026-09-01T09:30:00Z")
    s_b = make_cleared_screening(donor, center, "2026-09-01T08:30:00Z", recorder_id="rec-02")
    dv_b = make_donation(donor, center, s_b, "2026-09-01T10:00:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(dv_a["id"], TEST_USERS["phlebotomist_headers"]))
    prov_a = get_payment(dv_a["id"])
    set_clock("2026-09-01T10:00:00Z")
    get_success_data(api_client.check_in(dv_b["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api_client.complete_collection(dv_b["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]))
    set_clock("2026-09-01T10:16:00Z")
    get_success_data(api_client.discharge(dv_b["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api_client.complete_collection(dv_a["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]))
    set_clock("2026-09-01T10:32:00Z")
    get_success_data(api_client.discharge(dv_a["id"], TEST_USERS["phlebotomist_headers"]))
    return donor, dv_a, dv_b, prov_a


def test_final_base_drops_one_tier_after_intervening_completion(api):
    """PRD §3.8: "they can diverge if another visit for the same donor
    completes in between this visit's check-in and completion, in which case
    the final base can be higher than the provisional base" — the final
    ordinal counts the intervening completion, so the tier reselection at
    FINAL time is driven by the shifted ordinal. "ordinal 0 yields
    `base_cents_first_donation`, ordinal 1 yields `base_cents_second_donation`".

    Design: Difficulty/dual_variant_calc/base_compensation_provisional_vs_final_cross_visit_divergence
    """
    donor, dv_a, dv_b, prov_a = _setup_cross_visit_race()
    assert prov_a["base_cents"] == 3000 and prov_a["net_cents"] == 3000, (
        "provisional ordinal 0 at A's check-in"
    )
    fin_b = get_payment(dv_b["id"])
    assert fin_b["base_cents"] == 3000 and fin_b["net_cents"] == 3000, (
        "B completed first: ordinal 0"
    )
    fin_a = get_payment(dv_a["id"])
    assert fin_a["variant"] == "FINAL"
    assert fin_a["base_cents"] == 2500, (
        "A's FINAL ordinal counts B's intervening completion"
    )
    assert fin_a["net_cents"] == 2500
    assert fin_a["net_cents"] != prov_a["net_cents"], "provisional != final for identical visit-A inputs"


def test_ytd_accumulates_final_nets_only_after_cross_visit_race(api):
    """PRD §3.8: "the donor's `ytd_compensation_cents` accumulates only the
    final `net_cents`" and "The donor's `ytd_compensation_cents` is recomputed
    on every finalize and every claw-back as the sum of `net_cents` over all
    CompensationPayment rows for this donor whose `payment_status` is
    `FINALIZED`".

    Design: Difficulty/dual_variant_calc/base_compensation_provisional_vs_final_cross_visit_divergence
    """
    donor, dv_a, dv_b, prov_a = _setup_cross_visit_race()
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 5500, "3000 (B final) + 2500 (A final)"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula:
# tiered_monthly_ordinal_base_rate_selection (2 tests)
# ---------------------------------------------------------------------------

def _setup_three_completions():
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    dv1 = run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    # Screening s3 is created while the clock is still on 09-01 (before the
    # 09-04 jump) so the logical clock never moves backward; its sub-records
    # are recorded after the 09-17 clock set, inside its 24h window.
    # Completions land on 09-01, 09-04, 09-17 — all in September, each more
    # than seven days after the previous so the rolling frequency cap (two
    # completions per trailing seven days) is never tripped.
    s3 = get_success_data(
        api_client.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-17T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    set_clock("2026-09-04T09:00:00Z")
    dv2 = run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-04T08:00:00Z",
        checkin_time="2026-09-04T09:30:00Z",
        discharge_time="2026-09-04T09:46:00Z",
    )
    set_clock("2026-09-17T09:30:00Z")
    from test_helpers.fixtures import check_in as _check_in, complete_collection as _cc, discharge as _dc
    from test_helpers.test_users import make_screener_headers as _ms
    for rt in ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM", "VIRAL_MARKER"):
        record_pass_sub_record(s3["id"], rt, "rec-01")
    get_success_data(api_client.clear_screening(s3["id"], _ms("ms-01")))
    dv3 = get_success_data(
        api_client.schedule_donation(
            donor["id"],
            {
                "center_id": center["id"],
                "screening_visit_id": s3["id"],
                "scheduled_for": "2026-09-17T10:00:00Z",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    _check_in(dv3["id"])
    _cc(dv3["id"], 690)
    set_clock("2026-09-17T10:16:00Z")
    dv3 = _dc(dv3["id"])
    return center, donor, dv1, dv2, dv3


def test_tiered_monthly_ordinal_base_rate_selection(api):
    """PRD §3.8: "The base amount is then selected from the pinned schedule:
    ordinal 0 yields `base_cents_first_donation`, ordinal 1 yields
    `base_cents_second_donation`, ordinal 2 or higher yields
    `base_cents_subsequent_donation`."

    Design: Difficulty/combinatorial_formula/tiered_monthly_ordinal_base_rate_selection
    """
    _, donor, dv1, dv2, dv3 = _setup_three_completions()
    assert get_payment(dv1["id"])["net_cents"] == 3000, "tier 1 (ordinal 0)"
    assert get_payment(dv2["id"])["net_cents"] == 2500, "tier 2 (ordinal 1)"
    assert get_payment(dv3["id"])["net_cents"] == 2000, "tier 3 (ordinal >= 2)"


def test_tiered_monthly_ordinal_ytd_and_qualification(api):
    """PRD §3.8: "The donor's `ytd_compensation_cents` is recomputed on every
    finalize and every claw-back as the sum of `net_cents` over all
    CompensationPayment rows for this donor whose `payment_status` is
    `FINALIZED` and whose `payment_issued_on` falls within the calendar year
    of the logical clock."
    PRD §3.7: "If, after this completion, the donor is still `APPLICANT`
    **and** the donor's lifetime completion count is at least 2 **and** the
    elapsed time between `applicant_window_started_on` and the current
    instant is at most 180 days (that is, 180 times 24 hours), the donor is
    promoted to `QUALIFIED`."

    Design: Difficulty/combinatorial_formula/tiered_monthly_ordinal_base_rate_selection
    """
    _, donor, dv1, dv2, dv3 = _setup_three_completions()
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 7500, "3000 + 2500 + 2000"
    assert d["donor_status"] == "QUALIFIED", "second completion within 180 days promotes"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula:
# abort_payout_multiply_then_floor_then_minfloor_rounding_order (2 tests)
# ---------------------------------------------------------------------------

def test_abort_payout_multiply_then_floor(api):
    """PRD §3.8: "Otherwise, the fraction collected is `actual_volume_ml`
    divided by `programmed_volume_ml`, and the abort amount is the
    final-variant `base_cents` (computed under the final-ordinal rule)
    multiplied by that fraction and rounded down to a whole cent." — the
    multiply-first-then-floor order yields floor(3000 * 200/690) = 869.
    PRD §3.8: "`promo_cents` is always 0 for an aborted visit".

    Design: Difficulty/combinatorial_formula/abort_payout_multiply_then_floor_then_minfloor_rounding_order
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api.complete_collection(donation["id"], {"actual_volume_ml": 200}, TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api.record_adverse_reaction(
            donation["id"],
            {
                "severity": "MODERATE",
                "reaction_code": "HEMATOMA",
                "observed_at": "2026-09-01T09:30:00Z",
                "notes": "hematoma formed during observation",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    payment = get_payment(donation["id"])
    # floor(3000 * 200/690) = floor(869.565...) = 869
    assert payment["net_cents"] == 869
    assert payment["promo_cents"] == 0
    assert payment["payment_status"] == "FINALIZED"


def test_abort_payout_minimum_floor_applied_after_flooring(api):
    """PRD §3.8: "When the result is positive but below 500 cents ($5), it is
    raised to the 500-cent minimum floor. The rounding order is fixed:
    multiply first, then floor, then apply the minimum." floor(3000 *
    100/690) = 434 < 500, so the floor lifts the payout to 500.

    Design: Difficulty/combinatorial_formula/abort_payout_multiply_then_floor_then_minfloor_rounding_order
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api.complete_collection(donation["id"], {"actual_volume_ml": 100}, TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api.record_adverse_reaction(
            donation["id"],
            {
                "severity": "MILD",
                "reaction_code": "CITRATE",
                "observed_at": "2026-09-01T09:30:00Z",
                "notes": "mild citrate reaction observed now",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    payment = get_payment(donation["id"])
    # floor(3000 * 100/690) = 434 -> raised to the 500-cent minimum floor
    assert payment["net_cents"] == 500
    assert payment["payment_status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula:
# promo_once_per_schedule_evaluation_order_resolution (2 tests)
# ---------------------------------------------------------------------------

def _setup_promo_race():
    """Schedule with qualifying count 1; dvA and dvB both checked in; B
    completes first, then A."""
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        promo_code="FALLPLUS", promo_bonus_cents=2000, promo_qualifying_donation_count=1,
    )
    donor = make_donor(center)
    s_a = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z", recorder_id="rec-01")
    dv_a = make_donation(donor, center, s_a, "2026-09-01T09:30:00Z")
    s_b = make_cleared_screening(donor, center, "2026-09-01T08:30:00Z", recorder_id="rec-02")
    dv_b = make_donation(donor, center, s_b, "2026-09-01T10:00:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api_client.check_in(dv_a["id"], TEST_USERS["phlebotomist_headers"]))
    prov_a = get_payment(dv_a["id"])
    set_clock("2026-09-01T10:00:00Z")
    get_success_data(api_client.check_in(dv_b["id"], TEST_USERS["phlebotomist_headers"]))
    prov_b = get_payment(dv_b["id"])
    get_success_data(api_client.complete_collection(dv_b["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]))
    set_clock("2026-09-01T10:16:00Z")
    get_success_data(api_client.discharge(dv_b["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api_client.complete_collection(dv_a["id"], {"actual_volume_ml": 690}, TEST_USERS["phlebotomist_headers"]))
    set_clock("2026-09-01T10:32:00Z")
    get_success_data(api_client.discharge(dv_a["id"], TEST_USERS["phlebotomist_headers"]))
    return donor, dv_a, dv_b, prov_a, prov_b


def test_promo_provisionals_both_optimistic_then_once_per_schedule(api):
    """PRD §3.8: "The no-prior-finalized clause makes the promo a
    once-per-schedule-per-donor payout." and "In the `PROVISIONAL` variant,
    `promo_cents` equals `promo_bonus_cents` when the count of in-window
    completions excluding this visit, plus one for this visit, is at least
    `promo_qualifying_donation_count`".

    Design: Difficulty/combinatorial_formula/promo_once_per_schedule_evaluation_order_resolution
    """
    donor, dv_a, dv_b, prov_a, prov_b = _setup_promo_race()
    assert prov_a["promo_cents"] == 2000 and prov_b["promo_cents"] == 2000
    assert prov_a["net_cents"] == 5000 and prov_b["net_cents"] == 5000
    fin_b = get_payment(dv_b["id"])
    assert fin_b["promo_cents"] == 2000, "first to complete banks the promo"
    assert fin_b["base_cents"] == 3000
    assert fin_b["net_cents"] == 5000


def test_promo_second_completion_excluded_by_pinned_evaluation_order(api):
    """PRD §3.8: "In the `FINAL` variant, `promo_cents` equals
    `promo_bonus_cents` when the in-window completed count including this
    visit is at least `promo_qualifying_donation_count` and the same
    no-prior-finalized-promo clause holds." — the second completion's FINAL
    recomputation sees the first completion's FINALIZED promo on the same
    schedule and yields 0. "the donor's `ytd_compensation_cents` accumulates
    only the final `net_cents`."

    Design: Difficulty/combinatorial_formula/promo_once_per_schedule_evaluation_order_resolution
    """
    donor, dv_a, dv_b, prov_a, prov_b = _setup_promo_race()
    fin_a = get_payment(dv_a["id"])
    assert fin_a["promo_cents"] == 0, "B's FINALIZED promo already exists on this schedule"
    assert fin_a["base_cents"] == 2500, "A's final base dropped one tier"
    assert fin_a["net_cents"] == 2500
    d = get_success_data(api_client.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["ytd_compensation_cents"] == 7500, "5000 (B final) + 2500 (A final)"


# ---------------------------------------------------------------------------
# Corner/state_machines: aborts
# ---------------------------------------------------------------------------

def test_abort_in_progress_creates_no_unit_and_zero_payment(api):
    """PRD §3.9: "When `actual_volume_ml` is null (a reaction in
    `IN_PROGRESS` before collection completed), no unit is created."
    PRD §3.8: "If `actual_volume_ml` is null — meaning the reaction occurred
    while the visit was still `IN_PROGRESS` before any collection was recorded
    — the abort amount is 0."

    Design: Corner/state_machines/abort_in_progress_creates_no_unit_and_zero_payment
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api.record_adverse_reaction(
            donation["id"],
            {
                "severity": "MILD",
                "reaction_code": "VASOVAGAL",
                "observed_at": "2026-09-01T09:30:00Z",
                "notes": "fainted before venipuncture",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    after = get_success_data(api.get_donation(donation["id"], TEST_USERS["admin_headers"]))
    assert after["visit_status"] == "ABORTED_REACTION"
    assert after["actual_volume_ml"] is None
    udata, umeta = validate_paginated(
        api.list_units(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert umeta["total_count"] == 0
    payment = get_payment(donation["id"])
    assert payment["payment_status"] == "FINALIZED"
    assert payment["net_cents"] == 0
    d = get_success_data(api.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d["lifetime_donation_count"] == 0
    assert d["ytd_compensation_cents"] == 0


def test_abort_in_observation_creates_partial_unit(api):
    """PRD §3.9: "When `actual_volume_ml` was already recorded and is greater
    than 0 — which is always the case for a reaction in `OBSERVATION`,
    because complete-collection has already run — a DonationUnit is created
    in `QUARANTINED` status with `volume_ml` set to `actual_volume_ml`."
    PRD §3.8: "Otherwise, the fraction collected is `actual_volume_ml`
    divided by `programmed_volume_ml`, and the abort amount is the
    final-variant `base_cents` (computed under the final-ordinal rule)
    multiplied by that fraction and rounded down to a whole cent" — yielding
    floor(3000 * 400/690) = 1739 for a 400-of-690 collection.

    Design: Corner/state_machines/abort_in_observation_creates_partial_unit
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule()
    donor = make_donor(center)
    screening = make_cleared_screening(donor, center, "2026-09-01T08:00:00Z")
    donation = make_donation(donor, center, screening, "2026-09-01T09:30:00Z")
    set_clock("2026-09-01T09:30:00Z")
    get_success_data(api.check_in(donation["id"], TEST_USERS["phlebotomist_headers"]))
    get_success_data(api.complete_collection(donation["id"], {"actual_volume_ml": 400}, TEST_USERS["phlebotomist_headers"]))
    get_success_data(
        api.record_adverse_reaction(
            donation["id"],
            {
                "severity": "MODERATE",
                "reaction_code": "HEMATOMA",
                "observed_at": "2026-09-01T09:30:00Z",
                "notes": "hematoma during observation period",
            },
            TEST_USERS["phlebotomist_headers"],
        )
    )
    udata, umeta = validate_paginated(
        api.list_units(TEST_USERS["admin_headers"], params={"donor_id": donor["id"]})
    )
    assert umeta["total_count"] == 1
    assert udata[0]["unit_status"] == "QUARANTINED"
    assert udata[0]["volume_ml"] == 400
    payment = get_payment(donation["id"])
    # floor(3000 * 400/690) = floor(1739.13) = 1739
    assert payment["net_cents"] == 1739
    assert payment["payment_status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Corner/calculations: ytd year scope and 1099 threshold
# ---------------------------------------------------------------------------

def test_ytd_accumulator_year_scoped_reset(api):
    """PRD §3.8: "The accumulator is year-scoped: payments issued in a prior
    calendar year do not roll forward." and "The base amount is then selected
    from the pinned schedule: ordinal 0 yields `base_cents_first_donation`"
    for a January completion with zero prior January completions.

    Design: Corner/calculations/ytd_accumulator_year_scoped_reset
    """
    set_clock("2026-12-20T09:00:00Z")
    center, _ = make_center_with_schedule(
        effective_from="2026-11-01T00:00:00Z", effective_to="2027-03-01T00:00:00Z",
    )
    donor = make_donor(center)
    dv1 = run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-12-20T08:00:00Z",
        checkin_time="2026-12-20T09:30:00Z",
        discharge_time="2026-12-20T09:46:00Z",
    )
    d1 = get_success_data(api.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d1["ytd_compensation_cents"] == 3000

    set_clock("2027-01-10T09:00:00Z")
    dv2 = run_completed_donation(
        donor, center,
        screening_scheduled_for="2027-01-10T08:00:00Z",
        checkin_time="2027-01-10T09:30:00Z",
        discharge_time="2027-01-10T09:46:00Z",
    )
    d2 = get_success_data(api.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    # December's 3000-cent payment is outside the 2027 input set; January's
    # completion is ordinal 0 in January -> base_cents_first_donation 3000.
    assert d2["ytd_compensation_cents"] == 3000
    assert d2["lifetime_donation_count"] == 2, "lifetime count is NOT year-scoped"


def test_requires_1099_threshold_exactly_60000(api):
    """PRD §3.8: "After every accumulator update the `requires_1099` flag is
    recomputed: it is true when the accumulator has reached 60000 cents
    ($600)." PRD §2.6: "The tax-reporting threshold that governs the donor's
    `requires_1099` flag is fixed at 60000 cents (i.e., $600 of compensation
    within a single calendar year)."

    Design: Corner/calculations/requires_1099_threshold_exactly_60000
    """
    set_clock("2026-09-01T09:00:00Z")
    center, _ = make_center_with_schedule(
        base_cents_first_donation=30000, base_cents_second_donation=30000,
    )
    donor = make_donor(center)
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-01T08:00:00Z",
        checkin_time="2026-09-01T09:30:00Z",
        discharge_time="2026-09-01T09:46:00Z",
    )
    d1 = get_success_data(api.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d1["ytd_compensation_cents"] == 30000
    assert d1["requires_1099"] is False

    set_clock("2026-09-04T09:00:00Z")
    run_completed_donation(
        donor, center,
        screening_scheduled_for="2026-09-04T08:00:00Z",
        checkin_time="2026-09-04T09:30:00Z",
        discharge_time="2026-09-04T09:46:00Z",
    )
    d2 = get_success_data(api.get_donor(donor["id"], TEST_USERS["admin_headers"]))
    assert d2["ytd_compensation_cents"] == 60000, "exactly at threshold"
    assert d2["requires_1099"] is True, ">= semantics at exactly 60000"
