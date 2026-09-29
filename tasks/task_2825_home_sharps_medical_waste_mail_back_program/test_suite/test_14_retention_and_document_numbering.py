"""Certificate retention arithmetic and the two deterministic document counters
(PRD 3.6, PRD 3.8).

Retention is calendar-year arithmetic over the strictest of three obligations, and
both the tracking number and the certificate number are pure counter arithmetic
with no random component, so each test pins an exact literal string or date.
"""

from test_helpers import (
    acknowledge_kit,
    add_enrolled_patient,
    add_screened_kit_cycle,
    assert_certificate,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_program_balances,
    assert_return_label,
    assert_total_count,
    certificate_void_payload,
    certify_destruction_for,
    create_packaging_spec,
    create_state_rule,
    create_treatment_facility,
    issue_kit_for,
    make_destruction_officer_headers,
    print_label_for,
    read_destruction_certificate,
    read_enrollment,
    read_enrollment_version,
    read_kit,
    read_program,
    read_treatment_facility,
    seal_kit_for,
    set_clock,
    setup_program_foundations,
    validate_success,
)

LEAP_DAY_OFFICER = "officer-12"
SCREENING_TECHNICIAN = "tech-77"


def _normalise_instant(value):
    """Compare ISO 8601 instants without depending on the fractional-second
    width the implementation chooses to serialise."""
    assert isinstance(value, str) and value.endswith("Z"), value
    return value[:-1].split(".")[0] + "Z"


def _cross_state_certifiable_shipment(api):
    """A CA patient's parcel sitting DELIVERED and CONFORMING inside a New York
    facility, ready to certify.

    The patient's state rule retains certificates for 3 years while the facility's
    New York rule retains them for 7, so the two obligations disagree and the
    federal floor of 3 is the weakest of the three.
    """
    ctx = setup_program_foundations(
        api,
        clock="2028-02-20T00:00:00Z",
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        packaging_spec_overrides={
            "spec_code": "MB-4G-STD",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        program_overrides={"per_kit_allowance_cents": 5000},
        with_facility=False,
    )
    ctx["facility_state_rule"] = create_state_rule(
        api,
        state_code="NY",
        household_sharps_classification="REGULATED_MEDICAL_WASTE",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=7,
        notification_deadline_hours=72,
    )
    ctx["treatment_facility"] = create_treatment_facility(
        api,
        ctx["facility_state_rule"]["id"],
        name="Hudson Valley Sharps Treatment",
        permit_number="NY-TF-0007",
        accepted_hazard_classes=["UN3291_SHARPS_ONLY"],
        daily_intake_capacity_units=200,
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={"weekly_sharps_count": 20},
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
    )
    add_screened_kit_cycle(
        api,
        ctx,
        outcome="CONFORMING",
        reason_code=None,
        fill_units=60,
        sealed_gross_weight_grams=1200,
        observed_gross_weight_grams=1200,
        scheduled_intake_date="2028-02-25",
        technician_user_id=SCREENING_TECHNICIAN,
    )
    return ctx


def test_01_leap_day_destruction_takes_the_stricter_state_and_clamps_the_anniversary(
    api
):
    """Certifying on 2028-02-29 picks the facility state's 7-year obligation over
    the patient state's 3 and the federal floor of 3, and the seventh anniversary
    of a leap day clamps down to 2035-02-28 rather than overflowing into March.

PRD 3.8: "A new certificate records the `shipment_id` it certifies, copies `kit_id` and `treatment_facility_id` from that shipment, writes the acting `X-User-ID` into `issued_by_user_id`, and sets `destruction_date` to the UTC calendar date of the logical clock at issuance."
PRD 3.8: "The `retention_until_date` answers the question of how long the certificate must be kept, and it consults exactly two state rules plus a federal floor — the patient's residence state and the treatment facility's state."
PRD 3.8: "The sponsor's state is irrelevant."
PRD 3.8: "Take the `certificate_retention_years` of the patient's state rule, the `certificate_retention_years` of the facility's state rule, and the federal minimum of 3 years, and use the largest of the three."
PRD 3.8: "That number of whole calendar years is then added to `destruction_date`."
PRD 3.8: "The addition is calendar-year arithmetic, not a multiplication by 365 days, and a leap-day anniversary clamps down: a destruction date of 2028-02-29 with a three-year retention obligation yields 2031-02-28."
PRD 3.8: "Its `certificate_number` is the literal text `CERT-`, then the facility's `permit_number`, then a hyphen, then a sequence number zero-padded to five digits, where the sequence number is the facility's `certificates_issued_count` plus one."

    Design: Corner/calculations/retention_deadline_takes_the_stricter_state_and_clamps_the_feb_29_anniversary
    """
    ctx = _cross_state_certifiable_shipment(api)

    set_clock(api, "2028-02-29T10:00:00Z")
    certificate = certify_destruction_for(
        api, ctx, destroyed_units=60, officer_user_id=LEAP_DAY_OFFICER
    )

    assert_certificate(
        certificate,
        certificate_number="CERT-NY-TF-0007-00001",
        destroyed_units=60,
        destruction_date="2028-02-29",
        retention_until_date="2035-02-28",
        issued_by_user_id=LEAP_DAY_OFFICER,
        status="ISSUED",
    )
    # The three-year federal floor is the weakest obligation here, so the
    # 2031-02-28 the PRD uses to illustrate the clamp must not be the answer.
    assert certificate["retention_until_date"] != "2031-02-28"


def test_02_the_final_settlement_of_the_leap_day_certificate_uses_measured_facts(api):
    """The settled figure is the 1450-cent ONE_QUART base plus 46 cents of observed
    transport plus 180 cents of manufacturer destruction, under the 5000-cent
    allowance and inside the lowest rebate tier, so it reads 1676 with no rebate.

PRD 3.8: "The base component is the size catalogue's `unit_cost_cents` for the kit's `container_size` — the same base the provisional figure used."
PRD 3.8: "The transport component takes the shipment's `observed_gross_weight_grams`, multiplies by the transport rate of 38 cents per kilogram, divides by 1000 to convert grams to kilograms, and rounds half up to a whole cent; note that this uses the weight the technician measured, not the capacity-based estimate the reservation used."
PRD 3.8: "The destruction component multiplies the certificate's `destroyed_units` by the sponsor's per-unit destruction rate — 3 cents per unit when the sponsor's `sponsor_type` is `MANUFACTURER` and 2.5 cents per unit when it is `HEALTH_PLAN` — and rounds half up to a whole cent."
PRD 3.8: "The surcharge component is 0 when the shipment carries no resolved remediation action or when the resolved action was `RETURN_TO_PATIENT`, 500 cents when it was `ON_SITE_REPACK`, and 900 cents when it was `DISPOSE_AS_RMW`."
PRD 3.8: "Those four rounded components are added to give a pre-rebate amount, and the pre-rebate amount is then capped: the amount carried forward is the smaller of the program's `per_kit_allowance_cents` and the pre-rebate amount."
PRD 3.8: "The tiers are: a basis from 0 through 14999 cents inclusive gives 0; a basis from 15000 through 29999 cents inclusive gives 0.03; and a basis from 30000 through 100000000 cents inclusive gives 0.06."

    Design: Corner/calculations/retention_deadline_takes_the_stricter_state_and_clamps_the_feb_29_anniversary
    """
    ctx = _cross_state_certifiable_shipment(api)

    set_clock(api, "2028-02-29T10:00:00Z")
    certificate = certify_destruction_for(
        api, ctx, destroyed_units=60, officer_user_id=LEAP_DAY_OFFICER
    )

    assert_certificate(
        certificate,
        final_kit_cost_cents=1676,
        rebate_pct_applied=0,
        status="ISSUED",
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="DESTROYED")


def test_03_a_reissued_certificate_gets_a_fresh_number_and_an_unclamped_anniversary(
    api
):
    """Voiding the leap-day certificate and re-certifying on 2028-03-01 needs no
    clamp, so retention lands on 2035-03-01, and because the facility counter is
    never decremented the corrected certificate is numbered 00002.

PRD 3.8: "A new certificate records the `shipment_id` it certifies, copies `kit_id` and `treatment_facility_id` from that shipment, writes the acting `X-User-ID` into `issued_by_user_id`, and sets `destruction_date` to the UTC calendar date of the logical clock at issuance."
PRD 3.8: "Take the `certificate_retention_years` of the patient's state rule, the `certificate_retention_years` of the facility's state rule, and the federal minimum of 3 years, and use the largest of the three."
PRD 3.8: "That number of whole calendar years is then added to `destruction_date`."
PRD 3.8: "Its `certificate_number` is the literal text `CERT-`, then the facility's `permit_number`, then a hyphen, then a sequence number zero-padded to five digits, where the sequence number is the facility's `certificates_issued_count` plus one."
PRD 3.8: "Because that counter includes voided certificates and is never decremented, a number is never reused: a corrected certificate re-issued for the same shipment always bears a fresh number."
PRD 3.8: "The certificate moves `ISSUED → VOIDED` with `voided_at` set to the current logical-clock instant and the supplied reason stored in `void_reason`."
PRD 3.8: "On the facility, `certificates_issued_count` rises by 1, `pending_intake_units` falls by exactly the shipment's `custody_units`, and `destroyed_units_total` rises by the certificate's `destroyed_units`."
PRD 3.8: "On the facility, `pending_intake_units` rises by exactly the shipment's `custody_units`, `destroyed_units_total` falls by the certificate's `destroyed_units`, and `certificates_issued_count` is deliberately left **unchanged** so that certificate numbers are never reused."

    Design: Corner/calculations/retention_deadline_takes_the_stricter_state_and_clamps_the_feb_29_anniversary
    """
    ctx = _cross_state_certifiable_shipment(api)

    set_clock(api, "2028-02-29T10:00:00Z")
    leap_certificate = certify_destruction_for(
        api, ctx, destroyed_units=60, officer_user_id=LEAP_DAY_OFFICER
    )
    validate_success(
        api.void_destruction_certificate(
            leap_certificate["id"],
            certificate_void_payload("wrong destruction date recorded"),
            make_destruction_officer_headers(LEAP_DAY_OFFICER),
        )
    )

    set_clock(api, "2028-03-01T09:00:00Z")
    march_certificate = certify_destruction_for(
        api, ctx, destroyed_units=60, officer_user_id=LEAP_DAY_OFFICER
    )

    assert_certificate(
        march_certificate,
        certificate_number="CERT-NY-TF-0007-00002",
        destroyed_units=60,
        destruction_date="2028-03-01",
        retention_until_date="2035-03-01",
        issued_by_user_id=LEAP_DAY_OFFICER,
        status="ISSUED",
    )
    assert (
        read_destruction_certificate(api, leap_certificate["id"])["status"] == "VOIDED"
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="DESTROYED")
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
        destroyed_units_total=60,
        certificates_issued_count=2,
        status="ACTIVE",
    )


def _three_sealed_kits_and_two_carriers(api):
    """One enrollment holding three SEALED kits, plus a USPS and a UPS packaging
    specification to draw labels on.

    Each kit is acknowledged and sealed before the next is issued, so no kit is
    ever in ISSUED or ACTIVE_FILLING when the following one is minted and nothing
    is superseded.
    """
    ctx = setup_program_foundations(
        api,
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        packaging_spec_overrides={
            "spec_code": "MB-USPS",
            "postal_service": "USPS_PARCEL_SELECT_MAILBACK",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        facility_overrides={
            "daily_intake_capacity_units": 200,
            "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
        },
        program_overrides={"per_kit_allowance_cents": 5000},
    )
    ctx["packaging_spec_ups"] = create_packaging_spec(
        api,
        spec_code="MB-UPS",
        postal_service="UPS_GROUND_MEDICAL",
        hazard_class="UN3291_SHARPS_ONLY",
        max_gross_weight_grams=9000,
        allowed_container_sizes=["ONE_QUART", "TWO_GALLON"],
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={"weekly_sharps_count": 20},
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
    )
    sealed_kits = []
    versions_before_issue = []
    for _ in range(3):
        versions_before_issue.append(
            read_enrollment_version(api, ctx["enrollment"]["id"])
        )
        kit = issue_kit_for(api, ctx)
        acknowledge_kit(api, ctx, kit=kit)
        sealed_kits.append(
            seal_kit_for(
                api, ctx, kit=kit, fill_units=60, sealed_gross_weight_grams=1200
            )
        )
    ctx["sealed_kits"] = sealed_kits
    ctx["versions_before_issue"] = versions_before_issue
    return ctx


def _print_three_labels(api, ctx):
    """Draw two labels on the USPS specification and the third on the UPS one."""
    first = print_label_for(
        api, ctx, kit=ctx["sealed_kits"][0], packaging_spec=ctx["packaging_spec"]
    )
    second = print_label_for(
        api, ctx, kit=ctx["sealed_kits"][1], packaging_spec=ctx["packaging_spec"]
    )
    third = print_label_for(
        api, ctx, kit=ctx["sealed_kits"][2], packaging_spec=ctx["packaging_spec_ups"]
    )
    return first, second, third


def test_04_the_first_two_usps_labels_take_the_program_wide_counter_in_order(api):
    """The label sequence counts every label in the program, so the first two
    labels drawn on the USPS specification are numbered 00000001 and 00000002 under
    the USPSMB prefix.

PRD 3.6: "Its `tracking_number` is deterministic and contains no random component: it is the carrier prefix, then a hyphen, then a sequence number zero-padded to eight digits."
PRD 3.6: "The prefix is `USPSMB` when the pinned `postal_service` is `USPS_PARCEL_SELECT_MAILBACK` and `UPSGM` when it is `UPS_GROUND_MEDICAL`."
PRD 3.6: "The sequence number is the total count of return labels that exist across the entire program — voided ones included — plus one; voided rows consume their number permanently and it is never reissued."

    Design: Corner/calculations/tracking_and_certificate_numbers_are_pure_counter_arithmetic_with_a_carrier_prefix
    """
    ctx = _three_sealed_kits_and_two_carriers(api)

    first, second, _third = _print_three_labels(api, ctx)

    assert_return_label(
        first,
        status="PRINTED",
        tracking_number="USPSMB-00000001",
        postal_service="USPS_PARCEL_SELECT_MAILBACK",
    )
    assert_return_label(
        second,
        status="PRINTED",
        tracking_number="USPSMB-00000002",
        postal_service="USPS_PARCEL_SELECT_MAILBACK",
    )


def test_05_the_ups_label_continues_the_same_counter_under_its_own_prefix(api):
    """Switching carrier does not restart the counter: the third label in the
    program is numbered 00000003 and carries the UPSGM prefix of its own pinned
    postal service.

PRD 3.6: "Its `tracking_number` is deterministic and contains no random component: it is the carrier prefix, then a hyphen, then a sequence number zero-padded to eight digits."
PRD 3.6: "The prefix is `USPSMB` when the pinned `postal_service` is `USPS_PARCEL_SELECT_MAILBACK` and `UPSGM` when it is `UPS_GROUND_MEDICAL`."
PRD 3.6: "The sequence number is the total count of return labels that exist across the entire program — voided ones included — plus one; voided rows consume their number permanently and it is never reissued."
PRD 3.6: "A printed label records the `kit_id` it belongs to and the `packaging_spec_id` it pinned, copies the specification's `postal_service` onto itself so that the carrier choice survives even if the specification is later retired, and takes status `PRINTED` with `voided_at` and `activated_at` both null."

    Design: Corner/calculations/tracking_and_certificate_numbers_are_pure_counter_arithmetic_with_a_carrier_prefix
    """
    ctx = _three_sealed_kits_and_two_carriers(api)

    _first, _second, third = _print_three_labels(api, ctx)

    assert_return_label(
        third,
        status="PRINTED",
        tracking_number="UPSGM-00000003",
        postal_service="UPS_GROUND_MEDICAL",
        voided_at=None,
        activated_at=None,
    )


def test_06_three_labels_on_different_kits_share_one_window_without_conflicting(
    api, logistics_coordinator_headers
):
    """All three labels are printed at the same clock instant, so all three windows
    run from 2026-08-01T00:00:00Z to 2026-09-15T00:00:00Z; because they belong to
    different kits none of them conflicts and all three survive as PRINTED.

PRD 3.6: "`valid_from` is the logical-clock instant at print time and `valid_until` is that instant advanced by 45 days, computed as exact instant arithmetic."
PRD 3.6: "Labels belonging to other kits never conflict."
PRD 3.6: "The kit itself stays `SEALED`: it does not advance until the carrier's first scan."
PRD 3.4: "If the enrollment already holds a kit in `ISSUED` or `ACTIVE_FILLING`, the most recent such kit by creation time is moved to `VOIDED` with `void_reason` set to `SUPERSEDED_BY_REPLACEMENT`, a `RESERVATION_RELEASE` ledger entry for the negation of that prior kit's `provisional_cost_cents` is appended at the next `sequence_no`, and the program's `reserved_cents` falls by that amount."
PRD 3.4: "*Fifth*, the enrollment's `next_autoship_due_date` is set to the UTC calendar date of `issued_at` advanced by `cadence_days`, its `kits_issued` is recomputed, and its `version` is incremented by 1."
PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
PRD 3.2: "Beyond the reserved/committed/available triple a program maintains five derived counters that a sponsor uses to reconcile: `kits_issued_count`, the number of kits under this program's enrollments whose status is anything other than `VOIDED`; `kits_settled_count`, the number of destruction certificates in status `ISSUED` against this program's kits; `provisional_total_cents`, the sum of `provisional_cost_cents` over this program's kits that carry an `ISSUED` certificate; and `final_total_cents`, the sum of `final_kit_cost_cents` over this program's `ISSUED` certificates."

    Design: Corner/calculations/tracking_and_certificate_numbers_are_pure_counter_arithmetic_with_a_carrier_prefix
    """
    ctx = _three_sealed_kits_and_two_carriers(api)

    labels = _print_three_labels(api, ctx)

    for label in labels:
        assert label["status"] == "PRINTED", label
        assert _normalise_instant(label["valid_from"]) == "2026-08-01T00:00:00Z", label
        assert _normalise_instant(label["valid_until"]) == "2026-09-15T00:00:00Z", label

    for kit in ctx["sealed_kits"]:
        assert_kit(read_kit(api, kit["id"]), status="SEALED", fill_units=60)
    for kit in ctx["sealed_kits"][1:]:
        assert_kit(read_kit(api, kit["id"]), supersedes_kit_id=None)

    enrollment = read_enrollment(api, ctx["enrollment"]["id"])
    assert_enrollment(
        enrollment,
        status="ACTIVE",
        kits_issued=3,
        version=ctx["versions_before_issue"][2] + 1,
    )
    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program,
        reserved_cents=4395,
        committed_cents=0,
        available_cents=495605,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert program["kits_issued_count"] == 3, program["kits_issued_count"]
    assert_total_count(
        api.list_return_labels(
            logistics_coordinator_headers, {"kit_id": ctx["sealed_kits"][0]["id"]}
        ),
        1,
    )
