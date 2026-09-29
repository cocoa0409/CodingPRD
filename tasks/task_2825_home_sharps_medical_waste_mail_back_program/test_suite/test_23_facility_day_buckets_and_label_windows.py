"""Two overlap geometries over the same tender path: a shared calendar-day intake
bucket at one facility, and the continuous closed instant interval a return label
claims on a single kit."""

from test_helpers import (
    LOGISTICS,
    acknowledge_kit,
    activate_label_for,
    assert_facility_counters,
    assert_return_label,
    assert_shipment_axes,
    assert_total_count,
    get_success_data,
    issue_kit_for,
    label_activation_payload,
    label_void_payload,
    print_label_for,
    read_kit,
    read_return_label,
    read_shipment,
    read_treatment_facility,
    return_label_payload,
    seal_kit_for,
    set_clock,
    setup_sealed_kit,
    setup_two_patient_program,
    validate_error,
    validate_success,
)

_SMALL_FACILITY = {
    "name": "Coastal Small-Lot Sharps Treatment",
    "permit_number": "CA-TF-SMALL",
    "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
    "daily_intake_capacity_units": 100,
}


def _normalised_instant(value):
    """Split an ISO 8601 UTC instant into its whole-second head and a
    three-digit fraction so that equality does not depend on how many
    fractional digits the serialiser chose to print."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    head, _, fraction = value[:-1].partition(".")
    return head, (fraction + "000")[:3]


# --------------------------------------------------------------------------
# Two 69-unit parcels aimed at one 100-unit facility day
# --------------------------------------------------------------------------
def _two_parcels_bound_for_one_small_facility(api):
    """Dana and Ray are funded by the same program and both seal a 69-unit
    ONE_QUART container. Dana's parcel is already tendered for a 2026-09-10
    intake at the 100-unit facility, booking 69 of its 100 units. Ray's label is
    printed but not yet activated."""
    ctx = setup_two_patient_program(api, facility_overrides=_SMALL_FACILITY)

    kit_a = issue_kit_for(api, ctx, enrollment=ctx["enrollment_a"])
    acknowledge_kit(api, ctx, kit=kit_a, patient=ctx["patient_a"])
    ctx["kit_a"] = seal_kit_for(api, ctx, kit=kit_a, patient=ctx["patient_a"])
    ctx["label_a"] = print_label_for(api, ctx, kit=ctx["kit_a"])
    ctx["shipment_a"] = activate_label_for(
        api, ctx, return_label=ctx["label_a"], scheduled_intake_date="2026-09-10"
    )

    kit_b = issue_kit_for(api, ctx, enrollment=ctx["enrollment_b"])
    acknowledge_kit(api, ctx, kit=kit_b, patient=ctx["patient_b"])
    ctx["kit_b"] = seal_kit_for(api, ctx, kit=kit_b, patient=ctx["patient_b"])
    ctx["label_b"] = print_label_for(api, ctx, kit=ctx["kit_b"])
    return ctx


def _attempt_second_activation(api, ctx, scheduled_intake_date):
    return api.activate_return_label(
        ctx["label_b"]["id"],
        label_activation_payload(
            ctx["treatment_facility"]["id"],
            scheduled_intake_date=scheduled_intake_date,
            declared_gross_weight_grams=1400,
        ),
        LOGISTICS,
    )


def test_01_two_individually_small_parcels_blow_through_one_day_s_capacity(api):
    """Each parcel is 69 units against a 100-unit ceiling, so neither is oversized on
    its own, yet 69 already booked plus 69 more is 138 and strictly greater than 100.

    PRD 3.6: "The capacity check is not a per-parcel size test; each individual parcel can sit comfortably under the ceiling while the day's total blows through it."
    PRD 3.6: "If the sum of the already-booked units and the new units is strictly greater than the facility's `daily_intake_capacity_units`, the activation is refused; landing on exactly the capacity figure is allowed."

    Design: Difficulty/resource_temporal_overlap/facility_daily_intake_capacity_exceeded_by_aggregate_units_on_same_intake_date
    """
    ctx = _two_parcels_bound_for_one_small_facility(api)

    response = _attempt_second_activation(api, ctx, "2026-09-10")

    validate_error(response, "ERR_FACILITY_INTAKE_CAPACITY_EXCEEDED", expected_status=409)


def test_02_the_capacity_refusal_tenders_nothing_at_all(api, logistics_coordinator_headers):
    """The refused activation leaves Ray's label `PRINTED` with a null `activated_at`,
    creates no shipment, and leaves the facility's booking at Dana's 69 units alone.

    PRD 3.6: "The label moves `PRINTED → ACTIVATED` with `activated_at` set to the current logical-clock instant and its `version` incremented by 1."
    PRD 3.6: "The destination facility's `pending_intake_units` rises by the new shipment's `custody_units`."

    Design: Difficulty/resource_temporal_overlap/facility_daily_intake_capacity_exceeded_by_aggregate_units_on_same_intake_date
    """
    ctx = _two_parcels_bound_for_one_small_facility(api)

    _attempt_second_activation(api, ctx, "2026-09-10")

    assert_return_label(
        read_return_label(api, ctx["label_b"]["id"]), status="PRINTED", activated_at=None
    )
    facility = read_treatment_facility(api, ctx["treatment_facility"]["id"])
    assert_facility_counters(facility, pending_intake_units=69)
    assert facility["daily_intake_capacity_units"] == 100
    assert_total_count(
        api.list_shipments(
            logistics_coordinator_headers,
            {"treatment_facility_id": ctx["treatment_facility"]["id"]},
        ),
        1,
    )


def test_03_the_very_next_intake_date_is_a_separate_bucket_and_admits_the_parcel(api):
    """Moving the booking one day forward puts the parcel in a different half-open UTC
    day bucket, where nothing is booked yet, so the identical 69 units are accepted.

    PRD 3.6: "The intake date defines a half-open day bucket running from midnight UTC on that date up to, but not including, midnight UTC on the following date."
    PRD 3.6: "The measure is the sum of `custody_units` over every shipment routed to that same facility with that exact same `scheduled_intake_date` that is still **open**, where a shipment counts as open when its `transport_status` is anything other than `LOST`, no destruction certificate in status `ISSUED` exists for it, and it does not carry a resolved non-conformance event whose `remediation_action` was `RETURN_TO_PATIENT`."

    Design: Difficulty/resource_temporal_overlap/facility_daily_intake_capacity_exceeded_by_aggregate_units_on_same_intake_date
    """
    ctx = _two_parcels_bound_for_one_small_facility(api)

    shipment = validate_success(
        _attempt_second_activation(api, ctx, "2026-09-11"), expected_status=201
    )

    assert shipment["scheduled_intake_date"] == "2026-09-11"
    assert_shipment_axes(
        shipment, transport_status="TENDERED", conformance_status="UNSCREENED", custody_units=69
    )
    assert_return_label(read_return_label(api, ctx["label_b"]["id"]), status="ACTIVATED")


def test_04_the_facility_wide_booking_may_exceed_a_single_day_s_capacity(api):
    """`pending_intake_units` is a whole-facility custody total, not a per-day figure, so
    the two parcels aggregate to 138 while the daily ceiling stays 100 — the capacity
    test is scoped to one `scheduled_intake_date`, not to the facility as a whole.

    PRD 3.6: "The measure is the sum of `custody_units` over every shipment routed to that same facility with that exact same `scheduled_intake_date` that is still **open**, where a shipment counts as open when its `transport_status` is anything other than `LOST`, no destruction certificate in status `ISSUED` exists for it, and it does not carry a resolved non-conformance event whose `remediation_action` was `RETURN_TO_PATIENT`."
    PRD 3.1: "Registration also initialises three counters to 0: `pending_intake_units`, which tracks the units currently inside the facility's custody chain; `destroyed_units_total`, the lifetime units destroyed under certificates that have not been voided; and `certificates_issued_count`, the count of certificates ever minted at the facility including voided ones, which drives the certificate numbering sequence."

    Design: Difficulty/resource_temporal_overlap/facility_daily_intake_capacity_exceeded_by_aggregate_units_on_same_intake_date
    """
    ctx = _two_parcels_bound_for_one_small_facility(api)

    _attempt_second_activation(api, ctx, "2026-09-11")

    facility = read_treatment_facility(api, ctx["treatment_facility"]["id"])
    assert_facility_counters(facility, pending_intake_units=138)
    assert facility["daily_intake_capacity_units"] == 100


def test_05_dana_s_earlier_booking_is_untouched_and_the_two_days_list_apart(api, logistics_coordinator_headers):
    """Dana's frozen 69 units and her 2026-09-10 date survive Ray's refused and then
    redirected tender, and the `scheduled_intake_date` filter separates the buckets.

    PRD 3.6: "freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit"
    PRD 3.6: "Shipments are readable individually and as a list filtered by `kit_id`, `return_label_id`, `treatment_facility_id`, `transport_status`, `conformance_status` or `scheduled_intake_date`."

    Design: Difficulty/resource_temporal_overlap/facility_daily_intake_capacity_exceeded_by_aggregate_units_on_same_intake_date
    """
    ctx = _two_parcels_bound_for_one_small_facility(api)

    _attempt_second_activation(api, ctx, "2026-09-10")
    _attempt_second_activation(api, ctx, "2026-09-11")

    dana_shipment = read_shipment(api, ctx["shipment_a"]["id"])
    assert dana_shipment["scheduled_intake_date"] == "2026-09-10"
    assert_shipment_axes(dana_shipment, custody_units=69)

    facility_id = ctx["treatment_facility"]["id"]
    assert_total_count(
        api.list_shipments(logistics_coordinator_headers, {"treatment_facility_id": facility_id}), 2
    )
    assert_total_count(
        api.list_shipments(
            logistics_coordinator_headers,
            {"treatment_facility_id": facility_id, "scheduled_intake_date": "2026-09-10"},
        ),
        1,
    )


# --------------------------------------------------------------------------
# One kit, one live 45-day label window, then a 24-hour void quarantine
# --------------------------------------------------------------------------
def _kit_with_one_live_printed_label(api):
    """Dana seals a 69-unit ONE_QUART container and one label is printed for it at
    2026-08-01T00:00:00Z. The label is never activated, so it stays `PRINTED` and
    keeps its interval live for the whole 45 days."""
    ctx = setup_sealed_kit(api)
    ctx["label_1"] = print_label_for(api, ctx)
    return ctx


def _attempt_print(api, ctx):
    return api.print_return_label(
        ctx["kit"]["id"], return_label_payload(ctx["packaging_spec"]["id"]), LOGISTICS
    )


def test_06_the_label_claims_a_forty_five_day_closed_interval_from_its_print_instant(api):
    """Printed at 2026-08-01T00:00:00Z, the label's window runs to exactly
    2026-09-15T00:00:00Z by instant arithmetic, and it is live with both of its
    lifecycle instants still null.

    PRD 3.6: "`valid_from` is the logical-clock instant at print time and `valid_until` is that instant advanced by 45 days, computed as exact instant arithmetic."
    PRD 3.6: "A printed label records the `kit_id` it belongs to and the `packaging_spec_id` it pinned, copies the specification's `postal_service` onto itself so that the carrier choice survives even if the specification is later retired, and takes status `PRINTED` with `voided_at` and `activated_at` both null."

    Design: Difficulty/resource_temporal_overlap/second_return_label_rejected_when_window_touches_live_label_and_during_void_quarantine
    """
    ctx = _kit_with_one_live_printed_label(api)

    label = read_return_label(api, ctx["label_1"]["id"])
    assert_return_label(label, status="PRINTED", voided_at=None, activated_at=None)
    assert _normalised_instant(label["valid_from"]) == _normalised_instant("2026-08-01T00:00:00Z")
    assert _normalised_instant(label["valid_until"]) == _normalised_instant("2026-09-15T00:00:00Z")


def test_07_a_new_window_that_merely_touches_the_live_one_is_a_conflict(api):
    """At 2026-09-15T00:00:00Z the new window's `valid_from` lands exactly on the live
    label's `valid_until`, and a closed interval treats that touch as an overlap.

    PRD 3.6: "That interval is treated as **closed on both ends** for conflict purposes."
    PRD 3.6: "Adjacency counts as a conflict: an instant exactly equal to a live label's `valid_until` conflicts, while one second later does not."
    PRD 3.6: "Last comes the occupancy check described below, whose refusal is `ERR_LABEL_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/second_return_label_rejected_when_window_touches_live_label_and_during_void_quarantine
    """
    ctx = _kit_with_one_live_printed_label(api)
    set_clock(api, "2026-09-15T00:00:00Z")

    validate_error(_attempt_print(api, ctx), "ERR_LABEL_WINDOW_CONFLICT", expected_status=409)


def test_08_a_conflicting_label_keeps_blocking_for_a_second_short_of_its_quarantine(api):
    """Voiding label 1 at 2026-09-15T00:00:00Z does not free the kit: one second before
    `voided_at` plus 24 hours the clock is still strictly inside the quarantine.

    PRD 3.6: "Separately, voiding a label does not immediately free the kit."
    PRD 3.6: "A `VOIDED` label of the same kit continues to block for a 24-hour quarantine measured from its `voided_at`; a print attempt is refused while the current logical-clock instant is strictly before `voided_at` plus 24 hours, and is allowed once the clock reaches exactly that boundary."

    Design: Difficulty/resource_temporal_overlap/second_return_label_rejected_when_window_touches_live_label_and_during_void_quarantine
    """
    ctx = _kit_with_one_live_printed_label(api)
    set_clock(api, "2026-09-15T00:00:00Z")
    _attempt_print(api, ctx)
    get_success_data(api.void_return_label(ctx["label_1"]["id"], label_void_payload(), LOGISTICS))

    set_clock(api, "2026-09-15T23:59:59Z")

    validate_error(_attempt_print(api, ctx), "ERR_LABEL_WINDOW_CONFLICT", expected_status=409)


def test_09_the_quarantine_boundary_itself_frees_the_kit_and_opens_a_fresh_window(api):
    """At exactly `voided_at` plus 24 hours the print is allowed, and the replacement
    label opens its own 45-day interval from that instant: 2026-09-16T00:00:00Z through
    2026-10-31T00:00:00Z.

    PRD 3.6: "A `VOIDED` label of the same kit continues to block for a 24-hour quarantine measured from its `voided_at`; a print attempt is refused while the current logical-clock instant is strictly before `voided_at` plus 24 hours, and is allowed once the clock reaches exactly that boundary."
    PRD 3.6: "`valid_from` is the logical-clock instant at print time and `valid_until` is that instant advanced by 45 days, computed as exact instant arithmetic."

    Design: Difficulty/resource_temporal_overlap/second_return_label_rejected_when_window_touches_live_label_and_during_void_quarantine
    """
    ctx = _kit_with_one_live_printed_label(api)
    set_clock(api, "2026-09-15T00:00:00Z")
    get_success_data(api.void_return_label(ctx["label_1"]["id"], label_void_payload(), LOGISTICS))
    set_clock(api, "2026-09-16T00:00:00Z")

    label_3 = validate_success(_attempt_print(api, ctx), expected_status=201)

    assert_return_label(label_3, status="PRINTED", voided_at=None, activated_at=None)
    assert _normalised_instant(label_3["valid_from"]) == _normalised_instant("2026-09-16T00:00:00Z")
    assert _normalised_instant(label_3["valid_until"]) == _normalised_instant(
        "2026-10-31T00:00:00Z"
    )


def test_10_the_dead_label_keeps_its_frozen_window_and_its_row(api, logistics_coordinator_headers):
    """Label 1 ends `VOIDED` with `voided_at` at the instant it was killed and its own
    window unchanged, the kit is still `SEALED` — which is exactly why the third print
    was legal at all — and two label rows now exist for that one kit.

    PRD 3.6: "The transition `PRINTED → VOIDED` sets `voided_at` to the current logical-clock instant — which is what starts the 24-hour quarantine on the kit — and increments the label's `version` by 1."
    PRD 3.6: "The kit must be `SEALED`; from any other kit state the answer is `ERR_INVALID_KIT_STATE`."
    PRD 3.6: "Labels are readable individually and as a list filtered by `kit_id`, `packaging_spec_id` or `status`."

    Design: Difficulty/resource_temporal_overlap/second_return_label_rejected_when_window_touches_live_label_and_during_void_quarantine
    """
    ctx = _kit_with_one_live_printed_label(api)
    set_clock(api, "2026-09-15T00:00:00Z")
    _attempt_print(api, ctx)
    get_success_data(api.void_return_label(ctx["label_1"]["id"], label_void_payload(), LOGISTICS))
    set_clock(api, "2026-09-15T23:59:59Z")
    _attempt_print(api, ctx)
    set_clock(api, "2026-09-16T00:00:00Z")
    _attempt_print(api, ctx)

    label_1 = read_return_label(api, ctx["label_1"]["id"])
    assert_return_label(label_1, status="VOIDED")
    assert _normalised_instant(label_1["voided_at"]) == _normalised_instant("2026-09-15T00:00:00Z")
    assert _normalised_instant(label_1["valid_from"]) == _normalised_instant("2026-08-01T00:00:00Z")
    assert _normalised_instant(label_1["valid_until"]) == _normalised_instant(
        "2026-09-15T00:00:00Z"
    )

    assert read_kit(api, ctx["kit"]["id"])["status"] == "SEALED"
    assert_total_count(
        api.list_return_labels(logistics_coordinator_headers, {"kit_id": ctx["kit"]["id"]}), 2
    )
