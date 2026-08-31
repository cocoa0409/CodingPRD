"""Pricing resolution, prerequisites, concurrent load and the seat-write version guard."""

from test_helpers import (
    ADMIN,
    COURSE_EXT_050,
    COURSE_EXT_101,
    COURSE_EXT_201,
    REGISTRAR,
    ApiErrorId,
    new_course,
    new_learner,
    read_learner,
    reset_clock,
    setup_fee_tier_boundary_scene,
    setup_issued_completion,
    setup_learner_load_scene,
    setup_open_offering,
    validate_error,
    validate_paginated,
    validate_success,
)


def _register(api, offering_id, learner_id, version):
    return api.create_registration(
        offering_id,
        {"learner_id": learner_id, "expected_offering_version": version},
        REGISTRAR,
    )


class TestFeeBandReadFromSubtotal:
    """The processing-fee band is selected from the subtotal, never from the total."""

    def test_fee_band_selected_from_subtotal_gives_four_percent_at_74000(self, api):
        """PRD 3.5: "Step five selects the processing-fee rate from **that subtotal,
        never from the final amount due**, by taking the highest of the three fee bands
        whose floor the subtotal reaches or exceeds: a subtotal of at least 0 cents but
        below 25,000 cents draws six percent, a subtotal of at least 25,000 cents but
        below 75,000 cents draws four percent, and a subtotal of at least 75,000 cents
        draws two and a half percent."
        PRD 3.5: "Reading the fee band off the final amount due would be circular,
        since the amount due already contains the fee, and is explicitly forbidden."

        Design: Difficulty/combinatorial_formula/fee_tier_read_from_subtotal_not_from_total_due
        """
        reset_clock()
        scene = setup_open_offering(offering_overrides={"tuition_cents": 74000})
        learner = new_learner(email="ada@x.com", full_name="Ada Ito")

        data = validate_success(
            _register(api, scene["offering_id"], learner["id"], scene["version"]), 201
        )
        assert data["processing_fee_cents"] == 2960, (
            f"Subtotal 74000 draws the four percent band: expected 2960, "
            f"got {data['processing_fee_cents']}"
        )
        assert data["total_due_cents"] == 76960
        assert data["processing_fee_cents"] != 1850, (
            "1850 would mean the band was read off total_due_cents"
        )
        assert data["total_due_cents"] != 75850

    def test_pricing_inputs_are_frozen_and_no_seat_is_held(self, api):
        """PRD 3.5: "Step one sets `list_tuition_cents` to the section's
        `tuition_cents` — the course's `list_price_cents` plays no part in the
        arithmetic."
        PRD 3.5: "Step three computes `loyalty_discount_cents` as `list_tuition_cents`
        multiplied by the tier's discount rate — zero percent for `NEW`, five percent
        for `RETURNING`, ten percent for `LOYAL`, and fifteen percent for `CHAMPION` —
        rounded half up to whole cents."
        PRD 3.5: "The registration is created with `enrollment_status` `PENDING` and
        `payment_status` `UNPAID`, holding no seat whatsoever — a pending registration
        is a quotation, not a place in the room — with `voucher_id` and
        `transferred_to_registration_id` both null, `amount_paid_cents` and
        `amount_refunded_cents` both zero, `sessions_attended` at zero, and
        `enrolled_at` null."

        Design: Difficulty/combinatorial_formula/fee_tier_read_from_subtotal_not_from_total_due
        """
        reset_clock()
        scene = setup_open_offering(offering_overrides={"tuition_cents": 74000})
        learner = new_learner(email="ada@x.com", full_name="Ada Ito")

        data = validate_success(
            _register(api, scene["offering_id"], learner["id"], scene["version"]), 201
        )
        assert data["list_tuition_cents"] == 74000
        assert data["loyalty_discount_cents"] == 0, "a NEW-tier learner draws no discount"
        assert data["enrollment_status"] == "PENDING"
        assert data["payment_status"] == "UNPAID"


class TestFeeBandBreakpoint:
    """The band floors are compared inclusively, so one cent of subtotal moves the fee."""

    def test_subtotal_exactly_at_band_floor_draws_the_four_percent_rate(self, api):
        """PRD 3.5: "Step five selects the processing-fee rate from **that subtotal,
        never from the final amount due**, by taking the highest of the three fee bands
        whose floor the subtotal reaches or exceeds: a subtotal of at least 0 cents but
        below 25,000 cents draws six percent, a subtotal of at least 25,000 cents but
        below 75,000 cents draws four percent, and a subtotal of at least 75,000 cents
        draws two and a half percent."
        PRD 3.5: "Step eight sets `total_due_cents` to the subtotal plus
        `processing_fee_cents`."

        Design: Difficulty/boundary_precision_check/fee_tier_breakpoint_is_inclusive_at_exactly_25000
        """
        reset_clock()
        scene = setup_fee_tier_boundary_scene()
        at = validate_success(
            _register(api, scene["at_id"], scene["learner_id"], scene["at_version"]), 201
        )
        assert at["list_tuition_cents"] == 25000
        assert at["processing_fee_cents"] == 1000, (
            f"25000 reaches the 25,000-cent floor: expected 1000, got "
            f"{at['processing_fee_cents']}"
        )
        assert at["total_due_cents"] == 26000

    def test_subtotal_one_cent_below_the_floor_falls_back_to_six_percent(self, api):
        """PRD 3.5: "Step five selects the processing-fee rate from **that subtotal,
        never from the final amount due**, by taking the highest of the three fee bands
        whose floor the subtotal reaches or exceeds: a subtotal of at least 0 cents but
        below 25,000 cents draws six percent, a subtotal of at least 25,000 cents but
        below 75,000 cents draws four percent, and a subtotal of at least 75,000 cents
        draws two and a half percent."
        PRD 3.5: "Step six multiplies the subtotal by the selected rate and rounds half
        up to whole cents to produce a raw fee."

        Design: Difficulty/boundary_precision_check/fee_tier_breakpoint_is_inclusive_at_exactly_25000
        """
        reset_clock()
        scene = setup_fee_tier_boundary_scene()
        below = validate_success(
            _register(api, scene["below_id"], scene["learner_id"], scene["below_version"]),
            201,
        )
        assert below["list_tuition_cents"] == 24999
        assert below["processing_fee_cents"] == 1500, (
            f"24999 falls back to the six percent band: expected 1500, got "
            f"{below['processing_fee_cents']}"
        )
        assert below["total_due_cents"] == 26499


class TestConcurrentCeuLoad:
    """Overlapping sections are summed over closed, endpoint-inclusive windows."""

    def test_touching_windows_push_the_learner_over_the_four_ceu_ceiling(self, api):
        """PRD 3.5: "Take the learner's existing registrations whose
        `enrollment_status` is `PENDING`, `ENROLLED` or `WAITLISTED`, and keep those
        whose section's teaching window overlaps the new section's window."
        PRD 3.5: "Here — unlike the instructor schedule check of §3.2 — the windows are
        treated as **closed** intervals running from `start_date` to `end_date`
        inclusive at both ends, so two sections that merely touch at an endpoint *do*
        overlap."
        PRD 3.5: "Sum the `ceu_units` of the courses behind those overlapping sections,
        add the `ceu_units` of the course behind the new section, and the total must be
        no greater than a concurrent ceiling of 4.0 CEU. Exceeding it yields
        `ERR_LEARNER_LOAD_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/learner_closed_interval_aggregate_ceu_load_cap
        """
        reset_clock()
        scene = setup_learner_load_scene()
        validate_error(
            _register(api, scene["late_id"], scene["learner_id"], scene["late_version"]),
            ApiErrorId.ERR_LEARNER_LOAD_EXCEEDED,
            409,
        )

    def test_load_rejection_creates_no_registration_row(self, api):
        """PRD 3.5: "Sum the `ceu_units` of the courses behind those overlapping
        sections, add the `ceu_units` of the course behind the new section, and the
        total must be no greater than a concurrent ceiling of 4.0 CEU. Exceeding it
        yields `ERR_LEARNER_LOAD_EXCEEDED`."
        PRD 2.3: "Registrations may be filtered by `offering_id`, `learner_id`,
        `voucher_id`, `transferred_to_registration_id`, `enrollment_status` and
        `payment_status`."

        Design: Difficulty/resource_temporal_overlap/learner_closed_interval_aggregate_ceu_load_cap
        """
        reset_clock()
        scene = setup_learner_load_scene()
        _register(api, scene["late_id"], scene["learner_id"], scene["late_version"])

        rows, meta = validate_paginated(
            api.list_registrations(REGISTRAR, params={"learner_id": scene["learner_id"]})
        )
        assert meta["total_count"] == 2, (
            f"the learner keeps only the two standing registrations, got {meta['total_count']}"
        )
        assert {r["enrollment_status"] for r in rows} == {"PENDING"}
        late = validate_success(api.get_offering(scene["late_id"], ADMIN))
        assert late["confirmed_enrollment_count"] == 0


def test_returning_tier_applies_five_percent_loyalty_discount(api):
    """PRD 3.5: "Step two reads the learner's `loyalty_tier` **as stored immediately
    before this pricing call**; the tier is only ever rewritten by the completion-award
    and revocation recompute, never by registering or paying, so a learner who
    registers for three sections in a row is priced at the same tier for all three."
    PRD 3.5: "Step three computes `loyalty_discount_cents` as `list_tuition_cents`
    multiplied by the tier's discount rate — zero percent for `NEW`, five percent for
    `RETURNING`, ten percent for `LOYAL`, and fifteen percent for `CHAMPION` — rounded
    half up to whole cents."
    PRD 3.7: "`loyalty_tier` follows from the count alone, evaluated from the top down:
    `CHAMPION` at 8 or more completions, otherwise `LOYAL` at 4 or more, otherwise
    `RETURNING` at 1 or more, otherwise `NEW`."

    Design: Corner/calculations/returning_tier_applies_five_percent_loyalty_discount_on_next_registration
    """
    reset_clock()
    completed = setup_issued_completion(
        course_spec=COURSE_EXT_050,
        offering_overrides={"session_count": 4, "tuition_cents": 25000},
    )
    learner = read_learner(completed["learner_id"])
    assert learner["loyalty_tier"] == "RETURNING"

    second = setup_open_offering(
        course_spec=COURSE_EXT_101,
        offering_overrides={"tuition_cents": 60000},
        instructor_index=1,
    )
    data = validate_success(
        _register(api, second["offering_id"], completed["learner_id"], second["version"]),
        201,
    )
    assert data["list_tuition_cents"] == 60000
    assert data["loyalty_discount_cents"] == 3000, (
        f"RETURNING draws five percent of 60000: expected 3000, got "
        f"{data['loyalty_discount_cents']}"
    )
    assert data["processing_fee_cents"] == 2280
    assert data["total_due_cents"] == 59280
    assert data["total_due_cents"] != 62400


def test_prerequisite_not_met_blocks_registration(api):
    """PRD 3.5: "Second, if the section's course declares a non-null
    `prerequisite_course_id`, the learner must have satisfied it — either by holding a
    completion record with `status` `ISSUED` whose originating registration sat on a
    section of that prerequisite course, or by holding a credit-for-prior-learning
    petition with `status` `APPROVED` whose `target_course_id` is that prerequisite
    course; failing both, the answer is `ERR_PREREQUISITE_NOT_MET`."

    Design: Corner/validations/prerequisite_not_met_blocks_registration_on_advanced_offering
    """
    reset_clock()
    base = new_course(**COURSE_EXT_101)
    advanced_spec = dict(COURSE_EXT_201)
    advanced_spec["prerequisite_course_id"] = base["id"]
    advanced = new_course(**advanced_spec)
    scene = setup_open_offering(
        course=advanced, offering_overrides={"tuition_cents": 90000}
    )
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")

    validate_error(
        _register(api, scene["offering_id"], learner["id"], scene["version"]),
        ApiErrorId.ERR_PREREQUISITE_NOT_MET,
        422,
    )
    _, meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"offering_id": scene["offering_id"]})
    )
    assert meta["total_count"] == 0
    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["confirmed_enrollment_count"] == 0


def test_stale_offering_version_on_registration_create_returns_412(api):
    """PRD 2.6: "Creating a registration against an offering requires the request to
    carry `expected_offering_version`, a non-optional input field holding the `version`
    of the target `Offering` as the client last observed it."
    PRD 2.6: "If `expected_offering_version` does not equal the offering's current
    stored `version`, the create is refused with `ERR_STALE_VERSION` (HTTP 412) and the
    client must re-read the offering before retrying."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_offering_version_on_registration_create_returns_412
    """
    reset_clock()
    scene = setup_open_offering()
    ada = new_learner(email="ada@x.com", full_name="Ada Ito")
    ben = new_learner(email="ben@x.com", full_name="Ben Osei")

    first = validate_success(
        _register(api, scene["offering_id"], ada["id"], scene["version"]), 201
    )
    validate_error(
        _register(api, scene["offering_id"], ben["id"], scene["version"]),
        ApiErrorId.ERR_STALE_VERSION,
        412,
    )
    _, meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"offering_id": scene["offering_id"]})
    )
    assert meta["total_count"] == 1
    kept = validate_success(api.get_registration(first["id"], REGISTRAR))
    assert kept["enrollment_status"] == "PENDING"
    _, ben_meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"learner_id": ben["id"]})
    )
    assert ben_meta["total_count"] == 0


def test_fresh_offering_version_succeeds_and_bumps_version_by_one(api):
    """PRD 3.5: "Creating a registration also increments the section's `version` by 1,
    which is exactly why a client must re-read the section between successive creates."
    PRD 2.4: "`version` begins at 1 when the resource is created and increments by
    exactly 1 on every mutation of that resource, whether the mutation is driven
    directly by the request or indirectly by a cascade originating elsewhere."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_offering_version_succeeds_and_bumps_version
    """
    reset_clock()
    scene = setup_open_offering()
    ada = new_learner(email="ada@x.com", full_name="Ada Ito")
    ben = new_learner(email="ben@x.com", full_name="Ben Osei")

    v0 = scene["version"]
    validate_success(_register(api, scene["offering_id"], ada["id"], v0), 201)
    v1 = validate_success(api.get_offering(scene["offering_id"], ADMIN))["version"]
    assert v1 == v0 + 1, f"Expected version {v0 + 1} after one create, got {v1}"

    second = validate_success(
        _register(api, scene["offering_id"], ben["id"], v1), 201
    )
    v2 = validate_success(api.get_offering(scene["offering_id"], ADMIN))["version"]
    assert v2 == v1 + 1, f"Expected version {v1 + 1} after the second create, got {v2}"
    assert second["enrollment_status"] == "PENDING"
    _, meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"offering_id": scene["offering_id"]})
    )
    assert meta["total_count"] == 2
