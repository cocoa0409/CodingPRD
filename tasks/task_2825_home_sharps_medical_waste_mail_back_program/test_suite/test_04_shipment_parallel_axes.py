"""A shipment carries two genuinely independent lifecycles. The transport axis walks
to DELIVERED while conformance stays UNSCREENED, then the conformance axis walks on
to REMEDIATED while transport is frozen, and it is the conformance axis that unlocks
certification."""

from test_helpers import (
    INTAKE_TECHNICIAN_USER_ID,
    advance_transport,
    assert_certificate,
    assert_facility_counters,
    assert_kit,
    assert_non_conformance_event,
    assert_patient_risk,
    assert_shipment_axes,
    certify_destruction_for,
    read_first_non_conformance_event,
    read_kit,
    read_non_conformance_event,
    read_patient,
    read_shipment,
    read_treatment_facility,
    remediate_for,
    screen_shipment,
    setup_notified_non_conformance,
    setup_tendered_shipment,
)


def _normalised_instant(value):
    """Split an ISO 8601 UTC instant into its second-precision head and a
    three-digit fractional tail so that an omitted fraction and an explicit `.000`
    compare equal."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    body = value[:-1]
    head, _, fraction = body.partition(".")
    return head, (fraction + "000")[:3]


def test_01_carrier_scans_advance_transport_and_never_touch_conformance(api):
    """Both scans move the transport axis and leave the conformance axis at
    UNSCREENED, and the kit follows the transport axis to RECEIVED.

    PRD 2.8: "`transport_status` tracks where the parcel is — `TENDERED`, `IN_TRANSIT`, `DELIVERED` or `LOST` — and `conformance_status` tracks whether its contents were acceptable — `UNSCREENED`, `CONFORMING`, `NON_CONFORMING` or `REMEDIATED`. No transport event ever writes `conformance_status`, and no conformance operation ever writes `transport_status`."
    PRD 3.6: "The first scan moves the shipment `TENDERED → IN_TRANSIT`, leaves `conformance_status` at `UNSCREENED`, and cascades the kit `SEALED → IN_TRANSIT`; the shipment's `version` and the kit's `version` are each incremented by 1."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_tendered_shipment(api)
    assert_shipment_axes(
        ctx["shipment"], transport_status="TENDERED", conformance_status="UNSCREENED"
    )

    in_transit = advance_transport(api, ctx, "IN_TRANSIT")
    assert_shipment_axes(
        in_transit, transport_status="IN_TRANSIT", conformance_status="UNSCREENED"
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="IN_TRANSIT")

    delivered = advance_transport(api, ctx, "DELIVERED")
    assert_shipment_axes(
        delivered, transport_status="DELIVERED", conformance_status="UNSCREENED"
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED")


def test_02_screening_moves_conformance_while_transport_stays_delivered(api):
    """A rejection writes the conformance axis only; transport remains DELIVERED, so
    the row genuinely holds DELIVERED plus NON_CONFORMING at once.

    PRD 3.7: "A `NON_CONFORMING` screening is a three-hop cascade. First the conformance axis moves `UNSCREENED → NON_CONFORMING` with `observed_gross_weight_grams` and `screened_by_user_id` written exactly as in the conforming case, and `transport_status` again untouched."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_tendered_shipment(api)
    advance_transport(api, ctx, "IN_TRANSIT")
    advance_transport(api, ctx, "DELIVERED")

    screened = screen_shipment(
        api,
        ctx,
        outcome="NON_CONFORMING",
        observed_gross_weight_grams=1520,
        reason_code="WEIGHT_EXCEEDS_SPEC",
    )

    assert_shipment_axes(
        screened,
        transport_status="DELIVERED",
        conformance_status="NON_CONFORMING",
        custody_units=69,
        screened_by_user_id=INTAKE_TECHNICIAN_USER_ID,
    )


def test_03_remediation_advances_conformance_to_remediated_with_transport_frozen(api):
    """Resolving the event moves the conformance axis one step further and the
    transport axis not at all, giving DELIVERED plus REMEDIATED.

    PRD 3.7: "Whichever action is chosen, the event moves `CUSTOMER_NOTIFIED → RESOLVED` with the chosen `remediation_action` stored, the shipment's conformance axis moves `NON_CONFORMING → REMEDIATED` while `transport_status` stays `DELIVERED`, and both records have their `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_notified_non_conformance(
        api, reason_code="WEIGHT_EXCEEDS_SPEC", notification_channel="EMAIL"
    )

    remediate_for(api, ctx, "ON_SITE_REPACK")

    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]),
        transport_status="DELIVERED",
        conformance_status="REMEDIATED",
    )


def test_04_the_resolved_event_records_reason_channel_and_action(api):
    """The event carries the submitted reason code, the notification channel and the
    chosen disposition, and ends in RESOLVED.

    PRD 3.7: "Second, because the shipment became `NON_CONFORMING`, a non-conformance event is opened against it in status `OPEN`, recording the `shipment_id` it belongs to and the submitted `reason_code` — one of `UNAPPROVED_WASTE_TYPE`, `LOOSE_SHARPS_IN_BOX`, `UNSEALED_CONTAINER`, `OVERFILLED_CONTAINER`, `WEIGHT_EXCEEDS_SPEC` or `MISSING_ABSORBENT` — with `notified_at`, `notification_channel` and `remediation_action` all null, and with `notification_deadline_at` set to the event's own `created_at` advanced by the patient's state rule's `notification_deadline_hours`."
    PRD 3.7: "Success moves the event `OPEN → CUSTOMER_NOTIFIED`, sets `notified_at` to the current logical-clock instant, stores the channel, and increments the event's `version` by 1."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_notified_non_conformance(
        api, reason_code="WEIGHT_EXCEEDS_SPEC", notification_channel="EMAIL"
    )
    remediate_for(api, ctx, "ON_SITE_REPACK")

    event = read_non_conformance_event(api, ctx["non_conformance_event"]["id"])
    assert_non_conformance_event(
        event,
        status="RESOLVED",
        reason_code="WEIGHT_EXCEEDS_SPEC",
        notification_channel="EMAIL",
        remediation_action="ON_SITE_REPACK",
    )


def test_05_the_notification_deadline_is_the_state_rule_hours_after_the_event(api):
    """The event opens at 2026-08-01T00:00:00Z under California's 72-hour clock, so
    the deadline is 2026-08-04T00:00:00Z.

    PRD 3.7: "with `notification_deadline_at` set to the event's own `created_at` advanced by the patient's state rule's `notification_deadline_hours`."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_tendered_shipment(api)
    advance_transport(api, ctx, "IN_TRANSIT")
    advance_transport(api, ctx, "DELIVERED")
    screen_shipment(
        api,
        ctx,
        outcome="NON_CONFORMING",
        observed_gross_weight_grams=1520,
        reason_code="WEIGHT_EXCEEDS_SPEC",
    )

    event = read_first_non_conformance_event(api, ctx["shipment"]["id"])
    assert _normalised_instant(event["notification_deadline_at"]) == _normalised_instant(
        "2026-08-04T00:00:00Z"
    )


def test_06_the_rejection_scores_twenty_without_suspending_the_patient(api):
    """WEIGHT_EXCEEDS_SPEC weighs 20, well below the threshold of 60, so the patient
    keeps their ENROLLED status through the whole rejection.

    PRD 3.9: "Each event contributes a weight determined by its `reason_code`: `LOOSE_SHARPS_IN_BOX` weighs 45, `UNAPPROVED_WASTE_TYPE` weighs 40, `UNSEALED_CONTAINER` weighs 30, `OVERFILLED_CONTAINER` weighs 25, `WEIGHT_EXCEEDS_SPEC` weighs 20 and `MISSING_ABSORBENT` weighs 15."
    PRD 3.9: "When a conformance screening recomputes `screening_risk_score` to at least 60 while the patient is `ENROLLED`, the patient is suspended."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_notified_non_conformance(
        api, reason_code="WEIGHT_EXCEEDS_SPEC", notification_channel="EMAIL"
    )
    remediate_for(api, ctx, "ON_SITE_REPACK")

    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=20,
        status="ENROLLED",
    )


def test_07_a_remediated_axis_unlocks_certification_with_the_repack_surcharge(api):
    """REMEDIATED, not CONFORMING, is what satisfies the conformance precondition, and
    the on-site repack adds 500 cents on top of the 1450 base, the 58-cent transport
    component and the 207-cent destruction component, giving 2215.

    PRD 3.8: "The shipment's `transport_status` must be `DELIVERED` and its `conformance_status` must be either `CONFORMING` or `REMEDIATED`, failing which the answer is `ERR_DELIVERY_REQUIRED_BEFORE_DESTRUCTION` (HTTP 409) — waste that is still in the mail, or that has been rejected but not yet remediated, cannot be certified destroyed."
    PRD 3.8: "The surcharge component is 0 when the shipment carries no resolved remediation action or when the resolved action was `RETURN_TO_PATIENT`, 500 cents when it was `ON_SITE_REPACK`, and 900 cents when it was `DISPOSE_AS_RMW`."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_notified_non_conformance(
        api, reason_code="WEIGHT_EXCEEDS_SPEC", notification_channel="EMAIL"
    )
    remediate_for(api, ctx, "ON_SITE_REPACK")

    certificate = certify_destruction_for(api, ctx, destroyed_units=69)

    assert_certificate(
        certificate,
        destroyed_units=69,
        final_kit_cost_cents=2215,
        rebate_pct_applied=0.00,
        status="ISSUED",
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="DESTROYED")


def test_08_certification_moves_the_facility_counters(api):
    """The 69 units leave the pending queue, land in the lifetime destroyed total, and
    the facility's certificate counter reaches 1.

    PRD 3.8: "On the facility, `certificates_issued_count` rises by 1, `pending_intake_units` falls by exactly the shipment's `custody_units`, and `destroyed_units_total` rises by the certificate's `destroyed_units`."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_transport_and_conformance_dimensions_advance_independently
    """
    ctx = setup_notified_non_conformance(
        api, reason_code="WEIGHT_EXCEEDS_SPEC", notification_channel="EMAIL"
    )
    remediate_for(api, ctx, "ON_SITE_REPACK")
    certify_destruction_for(api, ctx, destroyed_units=69)

    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
        destroyed_units_total=69,
        certificates_issued_count=1,
    )
