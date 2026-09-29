"""Conditionally required activation fields and the two inclusive deadline
boundaries (PRD 3.6, PRD 3.7).

The manifest and absorbent gates are configuration-driven, so each test seeds one
rule and one specification that demand the field and one pair that does not. The
expiry and notification deadlines are both inclusive, so each test drives the
logical clock to the last legal instant and then one second past it.
"""

from test_helpers import (
    acknowledge_kit,
    activate_label_for,
    add_enrolled_patient,
    assert_facility_counters,
    assert_kit,
    assert_non_conformance_event,
    assert_patient_risk,
    assert_return_label,
    assert_shipment_axes,
    assert_total_count,
    create_packaging_spec,
    create_state_rule,
    deliver_shipment,
    issue_kit_for,
    label_activation_payload,
    make_intake_technician_headers,
    notify_customer_payload,
    print_label_for,
    read_first_non_conformance_event,
    read_kit,
    read_patient,
    read_return_label,
    read_treatment_facility,
    screen_shipment,
    seal_kit_for,
    set_clock,
    setup_program_foundations,
    validate_error,
    validate_success,
)

SCREENING_TECHNICIAN = "tech-77"
WASHINGTON_MANIFEST_NUMBER = "WA-MAN-4471"


def _normalise_instant(value):
    """Compare ISO 8601 instants without depending on the fractional-second
    width the implementation chooses to serialise."""
    assert isinstance(value, str) and value.endswith("Z"), value
    return value[:-1].split(".")[0] + "Z"


def _sealed_kit_with_label(api, ctx, key, packaging_spec):
    """Issue, acknowledge, seal and label one kit for the named patient."""
    kit = issue_kit_for(api, ctx, enrollment=ctx[f"enrollment_{key}"])
    acknowledge_kit(api, ctx, kit=kit, patient=ctx[f"patient_{key}"])
    seal_kit_for(
        api,
        ctx,
        kit=kit,
        patient=ctx[f"patient_{key}"],
        fill_units=60,
        sealed_gross_weight_grams=1200,
    )
    ctx[f"kit_{key}"] = read_kit(api, kit["id"])
    ctx[f"label_{key}"] = print_label_for(
        api, ctx, kit=kit, packaging_spec=packaging_spec
    )
    return ctx[f"label_{key}"]


def _two_states_and_two_specifications(api):
    """Two households whose configuration demands different activation fields.

    Wanda lives in a state whose rule sets `requires_state_manifest`, and her kit is
    labelled on a specification that sets `requires_absorbent`; Cora's state rule
    and specification both leave those flags at their defaults.
    """
    ctx = setup_program_foundations(
        api,
        state_rule_overrides={
            "household_sharps_classification": "HOUSEHOLD_EXEMPT",
            "requires_state_manifest": False,
        },
        packaging_spec_overrides={
            "spec_code": "MB-PLAIN",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
            "requires_absorbent": False,
        },
        facility_overrides={
            "daily_intake_capacity_units": 200,
            "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
        },
        program_overrides={"per_kit_allowance_cents": 5000},
    )
    ctx["manifest_state_rule"] = create_state_rule(
        api,
        state_code="WA",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=3,
        requires_state_manifest=True,
        notification_deadline_hours=72,
    )
    ctx["packaging_spec_absorbent"] = create_packaging_spec(
        api,
        spec_code="MB-ABS",
        postal_service="USPS_PARCEL_SELECT_MAILBACK",
        hazard_class="UN3291_SHARPS_ONLY",
        max_gross_weight_grams=8000,
        allowed_container_sizes=["ONE_QUART", "TWO_GALLON"],
        requires_absorbent=True,
    )
    terms = {"cadence_days": 30, "kits_authorized": 2}
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Wanda Lee",
            "weekly_sharps_count": 20,
            "contact_email": "wanda@example.com",
        },
        enrollment_overrides=terms,
        state_rule_id=ctx["manifest_state_rule"]["id"],
        key="wanda",
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Cora Diaz",
            "weekly_sharps_count": 20,
            "contact_email": "cora@example.com",
        },
        enrollment_overrides=terms,
        key="cora",
    )
    _sealed_kit_with_label(api, ctx, "wanda", ctx["packaging_spec_absorbent"])
    _sealed_kit_with_label(api, ctx, "cora", ctx["packaging_spec"])
    return ctx


def _activation(api, ctx, label, headers, **extra):
    """Attempt one activation against the seeded facility, returning the raw
    response so that both refusals and successes can be inspected."""
    return api.activate_return_label(
        label["id"],
        label_activation_payload(
            ctx["treatment_facility"]["id"],
            scheduled_intake_date="2026-08-05",
            declared_gross_weight_grams=1200,
            **extra,
        ),
        headers,
    )


def test_01_absorbent_gate_is_reported_before_the_equally_missing_manifest(
    api, logistics_coordinator_headers
):
    """Wanda's specification demands absorbent and her state rule demands a
    manifest; with both optional fields omitted the absorbent gate answers first.

    PRD 3.6: "Neither is universally required; each becomes mandatory only when a rule elsewhere in the configuration says so, which is exactly the kind of coupling that makes activation the most heavily gated call in the API."
    PRD 3.6: "Then the constraint band, in sequence: `declared_gross_weight_grams` must not exceed the pinned specification's `max_gross_weight_grams`, otherwise `ERR_POSTAL_WEIGHT_EXCEEDED` (HTTP 422); if the pinned specification's `requires_absorbent` is true then `absorbent_declared` must be present and true, and if it is absent or false the answer is `ERR_ABSORBENT_MATERIAL_REQUIRED` (HTTP 422); if the patient's state rule has `requires_state_manifest` true then `state_manifest_number` must be present and non-empty, failing which `ERR_STATE_MANIFEST_REQUIRED` (HTTP 422); the destination facility's `accepted_hazard_classes` must include the pinned specification's `hazard_class`, otherwise `ERR_FACILITY_NOT_PERMITTED` (HTTP 422); the destination facility's `status` must be `ACTIVE`, otherwise `ERR_INVALID_FACILITY_STATE` (HTTP 409); and the facility's intake booking for that date must accommodate the parcel, failing which `ERR_FACILITY_INTAKE_CAPACITY_EXCEEDED` (HTTP 409)."
    Design: Corner/validations/manifest_and_absorbent_gates_fire_only_for_the_rule_and_spec_that_demand_them
    """
    ctx = _two_states_and_two_specifications(api)

    response = _activation(
        api, ctx, ctx["label_wanda"], logistics_coordinator_headers
    )

    validate_error(response, "ERR_ABSORBENT_MATERIAL_REQUIRED", 422)


def test_02_manifest_gate_fires_once_absorbent_is_declared_and_then_clears(
    api, logistics_coordinator_headers
):
    """Declaring the absorbent uncovers the manifest requirement, and supplying
    both fields tenders the parcel with the manifest number stored on it.

    PRD 3.6: "Then the constraint band, in sequence: `declared_gross_weight_grams` must not exceed the pinned specification's `max_gross_weight_grams`, otherwise `ERR_POSTAL_WEIGHT_EXCEEDED` (HTTP 422); if the pinned specification's `requires_absorbent` is true then `absorbent_declared` must be present and true, and if it is absent or false the answer is `ERR_ABSORBENT_MATERIAL_REQUIRED` (HTTP 422); if the patient's state rule has `requires_state_manifest` true then `state_manifest_number` must be present and non-empty, failing which `ERR_STATE_MANIFEST_REQUIRED` (HTTP 422); the destination facility's `accepted_hazard_classes` must include the pinned specification's `hazard_class`, otherwise `ERR_FACILITY_NOT_PERMITTED` (HTTP 422); the destination facility's `status` must be `ACTIVE`, otherwise `ERR_INVALID_FACILITY_STATE` (HTTP 409); and the facility's intake booking for that date must accommodate the parcel, failing which `ERR_FACILITY_INTAKE_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD 3.6: "A shipment is created, copying `kit_id` from the label's kit and recording `return_label_id` as the label whose activation produced it, storing the submitted `treatment_facility_id`, `scheduled_intake_date`, `declared_gross_weight_grams` and `state_manifest_number`, freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit — and setting `tendered_at` to the current logical-clock instant."
    PRD 3.6: "The label moves `PRINTED → ACTIVATED` with `activated_at` set to the current logical-clock instant and its `version` incremented by 1."
    PRD 2.3: "Four pagination fields appear in the `meta` object of every list response: `limit` and `offset` echo the effective values used to build the page, `total_count` reports the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records matching the filters remain beyond the current page."
    Design: Corner/validations/manifest_and_absorbent_gates_fire_only_for_the_rule_and_spec_that_demand_them
    """
    ctx = _two_states_and_two_specifications(api)
    label = ctx["label_wanda"]

    missing_manifest = _activation(
        api, ctx, label, logistics_coordinator_headers, absorbent_declared=True
    )
    validate_error(missing_manifest, "ERR_STATE_MANIFEST_REQUIRED", 422)

    accepted = _activation(
        api,
        ctx,
        label,
        logistics_coordinator_headers,
        absorbent_declared=True,
        state_manifest_number=WASHINGTON_MANIFEST_NUMBER,
    )
    shipment = validate_success(accepted, expected_status=201)

    assert shipment["state_manifest_number"] == WASHINGTON_MANIFEST_NUMBER, (
        f"Expected the submitted manifest number to be stored, got "
        f"{shipment['state_manifest_number']!r}"
    )
    assert_shipment_axes(
        shipment, transport_status="TENDERED", conformance_status="UNSCREENED"
    )
    assert_return_label(read_return_label(api, label["id"]), status="ACTIVATED")
    assert_total_count(
        api.list_shipments(
            logistics_coordinator_headers, {"return_label_id": label["id"]}
        ),
        1,
    )


def test_03_plain_configuration_activates_with_both_optional_fields_omitted(
    api, logistics_coordinator_headers
):
    """Cora's rule and specification set neither flag, so the identical payload
    shape that Wanda was refused for succeeds and leaves the manifest null.

    PRD 3.6: "Neither is universally required; each becomes mandatory only when a rule elsewhere in the configuration says so, which is exactly the kind of coupling that makes activation the most heavily gated call in the API."
    PRD 3.6: "A shipment is created, copying `kit_id` from the label's kit and recording `return_label_id` as the label whose activation produced it, storing the submitted `treatment_facility_id`, `scheduled_intake_date`, `declared_gross_weight_grams` and `state_manifest_number`, freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit — and setting `tendered_at` to the current logical-clock instant."
    PRD 3.6: "The label moves `PRINTED → ACTIVATED` with `activated_at` set to the current logical-clock instant and its `version` incremented by 1."
    PRD 3.6: "The destination facility's `pending_intake_units` rises by the new shipment's `custody_units`."
    Design: Corner/validations/manifest_and_absorbent_gates_fire_only_for_the_rule_and_spec_that_demand_them
    """
    ctx = _two_states_and_two_specifications(api)

    wanda_shipment = validate_success(
        _activation(
            api,
            ctx,
            ctx["label_wanda"],
            logistics_coordinator_headers,
            absorbent_declared=True,
            state_manifest_number=WASHINGTON_MANIFEST_NUMBER,
        ),
        expected_status=201,
    )
    cora_shipment = validate_success(
        _activation(api, ctx, ctx["label_cora"], logistics_coordinator_headers),
        expected_status=201,
    )

    assert cora_shipment["state_manifest_number"] is None, (
        f"Expected no manifest number on the plain parcel, got "
        f"{cora_shipment['state_manifest_number']!r}"
    )
    assert_shipment_axes(cora_shipment, transport_status="TENDERED", custody_units=60)
    assert_shipment_axes(wanda_shipment, custody_units=60)
    assert_return_label(
        read_return_label(api, ctx["label_cora"]["id"]), status="ACTIVATED"
    )
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=120,
    )


def _three_labels_printed_on_one_window(api):
    """One household with three sealed kits, each labelled at the baseline clock
    so that all three validity windows are identical."""
    ctx = setup_program_foundations(
        api,
        state_rule_overrides={
            "household_sharps_classification": "HOUSEHOLD_EXEMPT",
            "notification_deadline_hours": 72,
        },
        packaging_spec_overrides={
            "spec_code": "MB-USPS",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        facility_overrides={
            "daily_intake_capacity_units": 200,
            "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
        },
        program_overrides={"per_kit_allowance_cents": 5000},
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Dana Reyes",
            "weekly_sharps_count": 20,
            "contact_email": "dana@example.com",
        },
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
    )
    kits = []
    labels = []
    for _ in range(3):
        kit = issue_kit_for(api, ctx)
        acknowledge_kit(api, ctx, kit=kit)
        seal_kit_for(api, ctx, kit=kit, fill_units=60, sealed_gross_weight_grams=1200)
        kits.append(read_kit(api, kit["id"]))
        labels.append(print_label_for(api, ctx, kit=kit))
    ctx["sealed_kits"] = kits
    ctx["labels"] = labels
    return ctx


def _tender_at_the_last_legal_instant(api, ctx, label):
    """Activate one parcel at exactly the shared `valid_until` instant."""
    set_clock(api, "2026-09-15T00:00:00Z")
    return activate_label_for(
        api,
        ctx,
        return_label=label,
        scheduled_intake_date="2026-09-20",
        declared_gross_weight_grams=1200,
    )


def _two_rejected_parcels_screened_one_second_later(api):
    """Tender two parcels at the last legal instant, then deliver and screen both
    as non-conforming one second later so their events share a deadline."""
    ctx = _three_labels_printed_on_one_window(api)
    set_clock(api, "2026-09-15T00:00:00Z")
    for label in (ctx["labels"][0], ctx["labels"][2]):
        activate_label_for(
            api,
            ctx,
            return_label=label,
            scheduled_intake_date="2026-09-20",
            declared_gross_weight_grams=1200,
        )
    first, second = ctx["shipments"][0], ctx["shipments"][1]
    set_clock(api, "2026-09-15T00:00:01Z")
    for shipment in (first, second):
        deliver_shipment(api, ctx, shipment=shipment)
        screen_shipment(
            api,
            ctx,
            shipment=shipment,
            outcome="NON_CONFORMING",
            reason_code="MISSING_ABSORBENT",
            observed_gross_weight_grams=1200,
            technician_user_id=SCREENING_TECHNICIAN,
        )
    ctx["shipment_a"], ctx["shipment_b"] = first, second
    ctx["event_a"] = read_first_non_conformance_event(api, first["id"])
    ctx["event_b"] = read_first_non_conformance_event(api, second["id"])
    return ctx


def test_04_activation_at_exactly_valid_until_is_still_accepted(api):
    """The label window runs 45 days from the print instant, and tendering at the
    closing instant itself is legal.

    PRD 3.6: "`valid_from` is the logical-clock instant at print time and `valid_until` is that instant advanced by 45 days, computed as exact instant arithmetic."
    PRD 3.6: "Activating at the instant exactly equal to `valid_until` is still permitted."
    PRD 3.6: "A shipment is created, copying `kit_id` from the label's kit and recording `return_label_id` as the label whose activation produced it, storing the submitted `treatment_facility_id`, `scheduled_intake_date`, `declared_gross_weight_grams` and `state_manifest_number`, freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit — and setting `tendered_at` to the current logical-clock instant."
    Design: Corner/validations/label_expiry_and_notification_deadline_are_both_inclusive_on_the_last_legal_instant
    """
    ctx = _three_labels_printed_on_one_window(api)
    label = ctx["labels"][0]
    assert _normalise_instant(label["valid_until"]) == "2026-09-15T00:00:00Z", (
        f"Expected the window to close at 2026-09-15T00:00:00Z, got "
        f"{label['valid_until']!r}"
    )

    shipment = _tender_at_the_last_legal_instant(api, ctx, label)

    assert _normalise_instant(shipment["tendered_at"]) == "2026-09-15T00:00:00Z", (
        f"Expected tendered_at at the closing instant, got "
        f"{shipment['tendered_at']!r}"
    )
    assert_shipment_axes(shipment, transport_status="TENDERED", custody_units=60)


def test_05_activation_one_second_past_valid_until_is_refused(
    api, logistics_coordinator_headers
):
    """One second beyond the window the temporal band refuses the activation and
    nothing downstream is created.

    PRD 3.6: "Only after all of those does the temporal band run: the current logical-clock instant must be at or before the label's `valid_until`, and an activation attempted later is refused with `ERR_LABEL_EXPIRED` (HTTP 422)."
    PRD 3.6: "The kit itself stays `SEALED`: it does not advance until the carrier's first scan."
    PRD 2.3: "Four pagination fields appear in the `meta` object of every list response: `limit` and `offset` echo the effective values used to build the page, `total_count` reports the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records matching the filters remain beyond the current page."
    Design: Corner/validations/label_expiry_and_notification_deadline_are_both_inclusive_on_the_last_legal_instant
    """
    ctx = _three_labels_printed_on_one_window(api)
    _tender_at_the_last_legal_instant(api, ctx, ctx["labels"][0])
    expired_label = ctx["labels"][1]

    set_clock(api, "2026-09-15T00:00:01Z")
    response = api.activate_return_label(
        expired_label["id"],
        label_activation_payload(
            ctx["treatment_facility"]["id"],
            scheduled_intake_date="2026-09-20",
            declared_gross_weight_grams=1200,
        ),
        logistics_coordinator_headers,
    )

    validate_error(response, "ERR_LABEL_EXPIRED", 422)
    assert_return_label(
        read_return_label(api, expired_label["id"]),
        status="PRINTED",
        activated_at=None,
    )
    assert_kit(read_kit(api, ctx["sealed_kits"][1]["id"]), status="SEALED", fill_units=60)
    assert_total_count(
        api.list_shipments(
            logistics_coordinator_headers, {"return_label_id": expired_label["id"]}
        ),
        0,
    )


def test_06_notification_at_exactly_the_deadline_instant_is_accepted(api):
    """The event's deadline is its own creation instant plus the state rule's 72
    hours, and notifying at that instant is still permitted.

    PRD 3.7: "Second, because the shipment became `NON_CONFORMING`, a non-conformance event is opened against it in status `OPEN`, recording the `shipment_id` it belongs to and the submitted `reason_code` — one of `UNAPPROVED_WASTE_TYPE`, `LOOSE_SHARPS_IN_BOX`, `UNSEALED_CONTAINER`, `OVERFILLED_CONTAINER`, `WEIGHT_EXCEEDS_SPEC` or `MISSING_ABSORBENT` — with `notified_at`, `notification_channel` and `remediation_action` all null, and with `notification_deadline_at` set to the event's own `created_at` advanced by the patient's state rule's `notification_deadline_hours`."
    PRD 3.7: "The event must be `OPEN`, otherwise `ERR_INVALID_NONCONFORMANCE_STATE`, and the current logical-clock instant must be at or before the event's `notification_deadline_at` — a notification recorded after that instant is refused with `ERR_NOTIFICATION_DEADLINE_PASSED` (HTTP 422), and recording it at the instant exactly equal to the deadline is still permitted."
    PRD 3.7: "Success moves the event `OPEN → CUSTOMER_NOTIFIED`, sets `notified_at` to the current logical-clock instant, stores the channel, and increments the event's `version` by 1."
    Design: Corner/validations/label_expiry_and_notification_deadline_are_both_inclusive_on_the_last_legal_instant
    """
    ctx = _two_rejected_parcels_screened_one_second_later(api)
    event = ctx["event_a"]
    deadline = _normalise_instant(event["notification_deadline_at"])
    assert deadline == "2026-09-18T00:00:01Z", (
        f"Expected the deadline 72 hours after 2026-09-15T00:00:01Z, got "
        f"{event['notification_deadline_at']!r}"
    )

    set_clock(api, "2026-09-18T00:00:01Z")
    notified = validate_success(
        api.notify_customer(
            event["id"],
            notify_customer_payload("EMAIL"),
            make_intake_technician_headers(SCREENING_TECHNICIAN),
        ),
        expected_status=200,
    )

    assert_non_conformance_event(
        notified,
        status="CUSTOMER_NOTIFIED",
        reason_code="MISSING_ABSORBENT",
        notification_channel="EMAIL",
    )
    assert _normalise_instant(notified["notified_at"]) == "2026-09-18T00:00:01Z", (
        f"Expected notified_at at the deadline instant, got "
        f"{notified['notified_at']!r}"
    )


def test_07_notification_one_second_past_the_deadline_is_refused(api):
    """One second past the deadline the notification is refused and the event is
    left untouched, while the two fresh rejections stand at their full weight.

    PRD 3.7: "The event must be `OPEN`, otherwise `ERR_INVALID_NONCONFORMANCE_STATE`, and the current logical-clock instant must be at or before the event's `notification_deadline_at` — a notification recorded after that instant is refused with `ERR_NOTIFICATION_DEADLINE_PASSED` (HTTP 422), and recording it at the instant exactly equal to the deadline is still permitted."
    PRD 3.9: "Each event contributes a weight determined by its `reason_code`: `LOOSE_SHARPS_IN_BOX` weighs 45, `UNAPPROVED_WASTE_TYPE` weighs 40, `UNSEALED_CONTAINER` weighs 30, `OVERFILLED_CONTAINER` weighs 25, `WEIGHT_EXCEEDS_SPEC` weighs 20 and `MISSING_ABSORBENT` weighs 15."
    PRD 3.9: "An event aged at most 90 days contributes its full weight; an event aged from 91 through 180 days inclusive contributes half its weight; an event aged more than 180 days contributes nothing."
    PRD 3.7: "The patient's `screening_risk_score` is then recomputed over the enlarged event set."
    PRD 3.6: "The destination facility's `pending_intake_units` rises by the new shipment's `custody_units`."
    Design: Corner/validations/label_expiry_and_notification_deadline_are_both_inclusive_on_the_last_legal_instant
    """
    ctx = _two_rejected_parcels_screened_one_second_later(api)

    set_clock(api, "2026-09-18T00:00:02Z")
    response = api.notify_customer(
        ctx["event_b"]["id"],
        notify_customer_payload("EMAIL"),
        make_intake_technician_headers(SCREENING_TECHNICIAN),
    )

    validate_error(response, "ERR_NOTIFICATION_DEADLINE_PASSED", 422)
    assert_non_conformance_event(
        read_first_non_conformance_event(api, ctx["shipment_b"]["id"]),
        status="OPEN",
        reason_code="MISSING_ABSORBENT",
        notified_at=None,
        notification_channel=None,
    )
    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=30,
        status="ENROLLED",
    )
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=120,
    )
