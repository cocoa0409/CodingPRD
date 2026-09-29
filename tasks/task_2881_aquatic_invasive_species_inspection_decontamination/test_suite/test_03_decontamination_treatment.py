"""Hot-water treatment: instrument thresholds, technician standing and bay capacity."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_decon_order,
    assert_instant_equals,
    fetch_decon_order,
    fetch_record,
    make_decon_technician_headers,
    move_inspector,
    set_clock,
    setup_decon_order,
    treat_order,
    treatment_payload,
    validate_error,
    validate_success,
)


def _order_ready_for_treatment(*, decon_bay_count=1, seal_stock_initial_count=2):
    """A HIGH-band record dispositioned DECON with one ORDERED decontamination order.

    The clock is left at 2026-08-05T09:00:00Z, the instant every treatment in
    this module starts from.
    """
    ctx = setup_decon_order(
        decon_bay_count=decon_bay_count,
        seal_stock_initial_count=seal_stock_initial_count,
    )
    set_clock("2026-08-05T09:00:00Z")
    ctx["clock"] = "2026-08-05T09:00:00Z"
    return ctx


def _treat(order_id, technician_id, water_temp_f=140, pressure_psi=3000,
           dwell_seconds=120):
    return api_client.treat_decon_order(
        order_id, treatment_payload(water_temp_f, pressure_psi, dwell_seconds),
        make_decon_technician_headers(technician_id),
    )


class TestTreatmentFactorThresholds:
    """The temperature, pressure and dwell factors are inclusive at the top."""

    def test_readings_exactly_at_the_high_thresholds_score_one_hundred(self):
        """140 degrees, 3,000 PSI and the band's exact dwell give full effectiveness.

        PRD: "A temperature factor of 0.5 applies when `water_temp_f` is below
        140 degrees and 1.0 from 140 degrees upward. A pressure factor of 0.6
        applies when `pressure_psi` is below 3,000 and 1.0 from 3,000 upward. A
        dwell factor is the recorded `dwell_seconds` divided by the band's
        required dwell seconds, capped at 1.0 so that over-dwelling earns no
        bonus."  PRD: "Both factor thresholds are inclusive at the top: exactly
        140 degrees gives a temperature factor of 1.0, and exactly 3,000 PSI
        gives a pressure factor of 1.0."

        Design: Difficulty/boundary_precision_check/treatment_factors_exactly_at_their_high_thresholds
        """
        ctx = _order_ready_for_treatment()

        order = validate_success(
            _treat(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 140, 3000, 120),
            200,
        )

        assert_decon_order(order)
        assert float(order["treatment_effectiveness_pct"]) == 100.00
        assert order["base_dry_hours"] == 72
        assert order["required_dry_hours"] == 18
        assert order["attempt_count"] == 1
        assert order["status"] == "TREATED"
        assert_instant_equals(order["treated_at"], "2026-08-05T09:02:00Z", "treated_at")
        assert_instant_equals(order["dry_until"], "2026-08-06T03:02:00Z", "dry_until")
        assert_instant_equals(
            order["bay_released_at"], "2026-08-05T09:32:00Z", "bay_released_at"
        )

    def test_one_degree_below_the_threshold_halves_the_score_and_is_still_accepted(self):
        """139 degrees clears the 120-degree minimum but only earns a 0.5 factor.

        PRD: "The readings must meet the program minimums: `water_temp_f` of at
        least 120 degrees, `pressure_psi` of at least 1,500, and `dwell_seconds`
        of at least the band's required dwell, which is 30 seconds for `LOW`, 60
        seconds for `MODERATE`, 120 seconds for `HIGH` and 180 seconds for
        `EXTREME` as keyed on `band_at_order`; a reading exactly equal to a
        minimum is accepted, and anything below is `ERR_TREATMENT_BELOW_MINIMUM`."

        Design: Difficulty/boundary_precision_check/treatment_factors_exactly_at_their_high_thresholds
        """
        ctx = _order_ready_for_treatment()

        order = validate_success(
            _treat(ctx["decon_order"]["id"], ctx["inspector_b"]["id"], 139, 3000, 120),
            200,
        )

        assert float(order["treatment_effectiveness_pct"]) == 50.00
        assert order["required_dry_hours"] == 45
        assert_instant_equals(order["dry_until"], "2026-08-07T06:02:00Z", "dry_until")

    @pytest.mark.parametrize(
        "water_temp_f,pressure_psi,dwell_seconds",
        [
            (119, 3000, 120),
            (140, 3000, 119),
        ],
    )
    def test_readings_below_a_program_minimum_are_refused(self, water_temp_f,
                                                          pressure_psi, dwell_seconds):
        """A sub-minimum temperature or a sub-minimum dwell is a 422.

        PRD: "19. The treatment measurements meet the band minimums — otherwise
        `ERR_TREATMENT_BELOW_MINIMUM` (422). Applies to treatment."

        Design: Difficulty/boundary_precision_check/treatment_factors_exactly_at_their_high_thresholds
        """
        ctx = _order_ready_for_treatment()

        response = _treat(
            ctx["decon_order"]["id"], ctx["inspector_b"]["id"],
            water_temp_f, pressure_psi, dwell_seconds,
        )

        validate_error(response, ApiErrorId.ERR_TREATMENT_BELOW_MINIMUM)
        order = fetch_decon_order(ctx["decon_order"]["id"])
        assert order["status"] == "ORDERED"
        assert order["attempt_count"] == 0


class TestTreatmentRequiresACertifiedActiveTechnician:
    """Treatment reads the technician's certification and their standing."""

    def test_a_level_one_inspector_may_not_record_a_treatment(self):
        """A LEVEL_1 inspector acting as DeconTechnician is a 403, and nothing moves.

        PRD: "The second is **certification**. A `DeconTechnician` recording a
        treatment must hold certification level `DECON_CERTIFIED` and must have
        the decontamination endorsement on file; a `ReleaseVerifier` signing a
        dry verification or verifying a quarantine release must hold
        certification level `LEVEL_2` or `DECON_CERTIFIED`. Failing either test
        yields `ERR_INSPECTOR_NOT_CERTIFIED` (HTTP 403), and the guard applies
        to exactly three operations: recording a treatment, recording a dry
        verification, and verifying a quarantine release."

        Design: Difficulty/cross_entity_state_dependency/treatment_depends_on_the_technicians_certification_and_status
        """
        ctx = _order_ready_for_treatment()

        response = _treat(ctx["decon_order"]["id"], ctx["inspector_a"]["id"])

        validate_error(response, ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED)
        order = fetch_decon_order(ctx["decon_order"]["id"])
        assert order["status"] == "ORDERED"
        assert order["attempt_count"] == 0
        assert order["treatment_started_at"] is None
        assert order["treatment_effectiveness_pct"] is None
        record = fetch_record(ctx["record"]["id"])
        assert record["decon_fee_cents"] == 0
        assert record["total_fee_cents"] == 2500

    def test_a_decon_certified_technician_may_record_the_treatment(self):
        """The same order treated by the DECON_CERTIFIED technician is accepted.

        PRD: "A `DeconTechnician` recording a treatment must hold certification
        level `DECON_CERTIFIED` and must have the decontamination endorsement on
        file"

        Design: Difficulty/cross_entity_state_dependency/treatment_depends_on_the_technicians_certification_and_status
        """
        ctx = _order_ready_for_treatment()

        order = validate_success(
            _treat(ctx["decon_order"]["id"], ctx["inspector_b"]["id"]), 200
        )

        assert order["status"] == "TREATED"
        assert float(order["treatment_effectiveness_pct"]) == 100.00

    def test_a_suspended_technician_is_refused_on_standing(self):
        """Suspending the certified technician makes the next treatment a 409.

        PRD: "any inspector referenced by a request — the acting principal, and
        any inspector named by an identifier in the body — must be in `ACTIVE`
        standing at the moment the request is processed, or the request is
        rejected with `ERR_INSPECTOR_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/treatment_depends_on_the_technicians_certification_and_status
        """
        ctx = _order_ready_for_treatment()
        setup_decon_order(ctx)
        move_inspector(ctx["inspector_b"]["id"], "SUSPENDED")

        response = _treat(ctx["decon_order"]["id"], ctx["inspector_b"]["id"])

        validate_error(response, ApiErrorId.ERR_INSPECTOR_NOT_ACTIVE)
        order = fetch_decon_order(ctx["decon_order"]["id"])
        assert order["status"] == "ORDERED"
        assert order["attempt_count"] == 0


def _two_orders_at_one_station(*, decon_bay_count=1):
    """Two vessels at the same station, each with its own ORDERED decon order.

    Both orders exist before any treatment runs, so the first treatment proves
    that an untreated order occupies no bay.
    """
    ctx = setup_decon_order(decon_bay_count=decon_bay_count)
    first = ctx["decon_order"]
    first_record = ctx["record"]
    setup_decon_order(ctx)
    return ctx, first, first_record, ctx["decon_order"], ctx["record"]


class TestDeconBayOccupationIsClosedAndAggregate:
    """Bay occupation is a closed interval counted against `decon_bay_count`."""

    def test_a_proposal_touching_the_release_instant_exhausts_the_single_bay(self):
        """Starting exactly at the busy order's bay_released_at still collides.

        PRD: "The occupation this treatment would take is the closed interval
        beginning at the current logical time and ending at the current logical
        time plus `dwell_seconds` plus a 30-minute turnaround buffer. Against
        it, the service counts the *other* decontamination orders at the same
        station — the order being treated is always excluded from its own
        collision count — that have a non-null `treatment_started_at` and a
        `status` of either `TREATED` or `RETREAT_REQUIRED`, and whose own closed
        occupation interval from `treatment_started_at` to `bay_released_at`
        intersects the proposed one. Intervals that touch at a single instant do
        intersect."

        Design: Difficulty/resource_temporal_overlap/decon_bay_occupation_is_closed_and_aggregate_against_bay_count
        """
        ctx, first, _first_record, second, second_record = _two_orders_at_one_station()
        set_clock("2026-08-05T09:00:00Z")
        busy = treat_order(first["id"], ctx["inspector_b"]["id"])
        assert_instant_equals(
            busy["bay_released_at"], "2026-08-05T09:32:00Z", "bay_released_at"
        )
        set_clock("2026-08-05T09:32:00Z")

        response = _treat(second["id"], ctx["inspector_b"]["id"])

        validate_error(response, ApiErrorId.ERR_DECON_BAY_UNAVAILABLE)
        blocked = fetch_decon_order(second["id"])
        assert blocked["status"] == "ORDERED"
        assert blocked["attempt_count"] == 0
        assert blocked["treatment_started_at"] is None
        assert blocked["bay_released_at"] is None
        record = fetch_record(second_record["id"])
        assert record["decon_fee_cents"] == 0
        assert record["total_fee_cents"] == 2500

    def test_one_second_after_the_release_instant_the_bay_is_free(self):
        """A proposal starting one second later no longer intersects.

        PRD: "That count must be strictly less than the station's
        `decon_bay_count`; when it has reached the bay count, the treatment is
        rejected with `ERR_DECON_BAY_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/decon_bay_occupation_is_closed_and_aggregate_against_bay_count
        """
        ctx, first, _first_record, second, _second_record = _two_orders_at_one_station()
        set_clock("2026-08-05T09:00:00Z")
        treat_order(first["id"], ctx["inspector_b"]["id"])
        set_clock("2026-08-05T09:32:01Z")

        order = validate_success(_treat(second["id"], ctx["inspector_b"]["id"]), 200)

        assert order["status"] == "TREATED"
        assert_instant_equals(order["treated_at"], "2026-08-05T09:34:01Z", "treated_at")
        assert_instant_equals(
            order["bay_released_at"], "2026-08-05T10:04:01Z", "bay_released_at"
        )

    def test_a_second_bay_absorbs_the_touching_proposal(self):
        """With two bays the collision count of one is still below capacity.

        PRD: "**Bay capacity** is evaluated as an interval-overlap count against
        the station's physical bays."

        Design: Difficulty/resource_temporal_overlap/decon_bay_occupation_is_closed_and_aggregate_against_bay_count
        """
        ctx, first, _first_record, second, _second_record = _two_orders_at_one_station(
            decon_bay_count=2
        )
        set_clock("2026-08-05T09:00:00Z")
        treat_order(first["id"], ctx["inspector_b"]["id"])
        set_clock("2026-08-05T09:32:00Z")

        order = validate_success(_treat(second["id"], ctx["inspector_b"]["id"]), 200)

        assert order["status"] == "TREATED"
        assert_instant_equals(order["treated_at"], "2026-08-05T09:34:00Z", "treated_at")

    def test_an_untreated_order_occupies_no_bay(self):
        """A sibling order still ORDERED has a null treatment_started_at and is not counted.

        PRD: "the service counts the *other* decontamination orders at the same
        station — the order being treated is always excluded from its own
        collision count — that have a non-null `treatment_started_at` and a
        `status` of either `TREATED` or `RETREAT_REQUIRED`"

        Design: Difficulty/resource_temporal_overlap/decon_bay_occupation_is_closed_and_aggregate_against_bay_count
        """
        ctx, first, _first_record, second, _second_record = _two_orders_at_one_station()
        assert fetch_decon_order(second["id"])["treatment_started_at"] is None
        set_clock("2026-08-05T09:00:00Z")

        order = validate_success(_treat(first["id"], ctx["inspector_b"]["id"]), 200)

        assert order["status"] == "TREATED"
        assert_decon_order(order)
