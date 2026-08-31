"""Prescription resolution, the trim-cycle computation and reliability scoring."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    assert_circuit, assert_outage_record, assert_prescription,
    create_circuit_payload, create_outage_record_payload, create_prescription_payload,
    new_outage, new_prescription, read_circuit, read_prescription,
    read_reliability, setup_circuit,
    validate_error, validate_paginated, validate_success,
)

FORESTER = TEST_USERS["forester_headers"]
PLANNER = TEST_USERS["planner_headers"]


class TestCircuitRegistration:

    def test_circuit_registration_resolves_prescription_and_computes_cycle(self, api):
        """PRD §3.2: "A newly registered circuit starts at `reliability_tier` `TIER_NORMAL`,
        `trim_status` `NOT_SCHEDULED`, `tree_caused_outage_count_36mo` of 0, and both
        `reliability_index_36mo` and `reliability_index_ytd` at 0.00."
        PRD §3.2: "The clamped result is `cycle_months`, and `next_trim_due_on` is
        `last_trim_completed_on` advanced by that many calendar months; when the source day of
        month does not exist in the target month, it is clamped back to the last valid day of
        that month, so 31 January plus one month lands on 29 February in a leap year."

        Design: Corner/entities/corner_circuit_creation_returns_201_with_resolved_cycle_fields
        """
        presc = new_prescription(
            voltage_class="DISTRIBUTION_12KV", growth_zone="RAPID",
            base_cycle_years=4, clearance_radius_ft=10, effective_from="2026-01-01")

        resp = api.create_circuit(create_circuit_payload(
            circuit_code="CKT-A", voltage_class="DISTRIBUTION_12KV", growth_zone="RAPID",
            customer_count=1200, last_trim_completed_on="2024-03-15"), FORESTER)
        circuit = validate_success(resp, 201)

        assert_circuit(circuit)
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        assert circuit["prescription_id"] == presc["id"]
        assert circuit["cycle_months"] == 36, "4 years * 12 * 0.75 (RAPID) * 1.00 clamps to 36"
        assert circuit["next_trim_due_on"] == "2027-03-15"
        assert circuit["reliability_tier"] == "TIER_NORMAL"
        assert circuit["trim_status"] == "NOT_SCHEDULED"
        assert circuit["version"] == 1
        assert circuit["tree_caused_outage_count_36mo"] == 0

    def test_circuit_read_back_returns_the_stored_record(self, api):
        """PRD §2.4: "Every resource carries a server-minted `id`: a UUID string with no type
        prefix of any kind."
        PRD §3.2: "The clamp lifts the value to the floor if it is below it and lowers it to the
        ceiling if it is above it, and the clamp is applied to the rounded value, never to the
        unrounded product."

        Design: Corner/entities/corner_circuit_get_by_id_returns_stored_entity
        """
        world = setup_circuit()
        circuit_id = world["circuit"]["id"]

        stored = validate_success(api.get_circuit(circuit_id, PLANNER), 200)

        assert stored["id"] == circuit_id
        assert stored["circuit_code"] == "CKT-A"
        assert stored["cycle_months"] == 36

    def test_circuit_read_with_unknown_id_is_not_found(self, api):
        """PRD §2.5: "Each entity type has its own not-found code:
        `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_WORK_PLAN_NOT_FOUND`,
        `ERR_WORK_ORDER_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_PRODUCTION_ENTRY_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`,
        `ERR_HAZARD_TREE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND`,
        `ERR_BILLING_LINE_NOT_FOUND` and `ERR_OUTAGE_RECORD_NOT_FOUND`, each returned with
        HTTP 404."

        Design: Corner/entities/corner_circuit_get_unknown_id_not_found
        """
        new_prescription(activate=False)

        resp = api.get_circuit("00000000-0000-4000-8000-000000000000", FORESTER)

        validate_error(resp, ApiErrorId.ERR_CIRCUIT_NOT_FOUND.value)
        assert resp.status_code == 404
        assert resp.json()["response_type"] == "error"

    def test_circuit_with_no_matching_active_prescription_is_rejected(self, api):
        """PRD §3.1: "If the candidate set is empty, the request is rejected with
        `ERR_NO_ACTIVE_PRESCRIPTION` (HTTP 422) and the circuit's `prescription_id` is left
        exactly as it was."
        PRD §3.1: "Prescriptions in `DRAFT` or `SUPERSEDED` are never candidates."

        Design: Corner/validations/corner_circuit_without_active_prescription_is_rejected
        """
        draft = new_prescription(activate=False, voltage_class="DISTRIBUTION_12KV",
                                 growth_zone="RAPID", base_cycle_years=4,
                                 clearance_radius_ft=10, effective_from="2026-01-01")
        new_prescription(voltage_class="DISTRIBUTION_12KV", growth_zone="SLOW",
                         base_cycle_years=6, clearance_radius_ft=10,
                         effective_from="2026-01-01")

        resp = api.create_circuit(create_circuit_payload(
            circuit_code="CKT-A", voltage_class="DISTRIBUTION_12KV", growth_zone="RAPID",
            customer_count=1200, last_trim_completed_on="2024-03-15"), FORESTER)

        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRESCRIPTION.value)
        _, meta = validate_paginated(api.list_circuits(FORESTER))
        assert meta["total_count"] == 0
        assert read_prescription(draft["id"])["status"] == "DRAFT"

    def test_circuit_with_unknown_enum_member_fails_shape_validation_first(self, api):
        """PRD §2.9: "Shape and value validation: required body fields present, enum values
        drawn from their declared sets, numeric fields inside their declared ranges, dates and
        datetimes well formed, and uniqueness respected on `circuit_code` across circuits,
        `crew_code` across crews, `event_code` across storm events, and `premise_code` within
        one span's notifications. Any of these fails with `ERR_VALIDATION` (400)."

        Design: Corner/entities/corner_circuit_invalid_enum_returns_invalid_request
        """
        resp = api.create_circuit({
            "circuit_code": "CKT-BAD", "voltage_class": "DISTRIBUTION_7KV",
            "growth_zone": "RAPID", "customer_count": 1200,
            "last_trim_completed_on": "2024-03-15"}, FORESTER)

        error = validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
        assert resp.status_code == 400
        assert error["error_id"] != ApiErrorId.ERR_NO_ACTIVE_PRESCRIPTION.value


class TestPrescriptionAuthoring:

    def test_optional_switches_take_their_stated_defaults(self, api):
        """PRD §3.1: "Two further switches are optional at authoring time: `ground_to_sky`,
        which declares whether the corridor must be cleared floor to canopy and which defaults
        to false when omitted, and `herbicide_allowed`, which governs whether chemical control
        may be permitted on circuits governed by this prescription and which defaults to true
        when omitted."
        PRD §3.1: "A prescription is born in `DRAFT` and does nothing while it sits there."

        Design: Corner/entities/corner_prescription_defaults_applied_when_optional_flags_omitted
        """
        resp = api.create_prescription(create_prescription_payload(
            voltage_class="TRANSMISSION_115KV", growth_zone="SLOW", base_cycle_years=6,
            clearance_radius_ft=30, effective_from="2026-01-01"), FORESTER)

        presc = validate_success(resp, 201)
        assert_prescription(presc)
        assert presc["ground_to_sky"] is False
        assert presc["herbicide_allowed"] is True
        assert presc["status"] == "DRAFT"

    def test_activation_supersedes_only_the_same_voltage_and_growth_zone_peer(self, api):
        """PRD §3.1: "Activation by a `UtilityForester` moves it `DRAFT → ACTIVE`, and
        activation has a peer-level consequence: any other prescription sharing the same
        `voltage_class` and the same `growth_zone` that was in `ACTIVE` is pushed
        `ACTIVE → SUPERSEDED`, with its own `version` incremented."

        Design: Corner/state_machines/corner_prescription_activate_supersedes_prior_active_peer
        """
        rapid_one = new_prescription(voltage_class="DISTRIBUTION_12KV", growth_zone="RAPID",
                                     base_cycle_years=4, clearance_radius_ft=10,
                                     effective_from="2026-01-01")
        moderate = new_prescription(voltage_class="DISTRIBUTION_12KV", growth_zone="MODERATE",
                                    base_cycle_years=5, clearance_radius_ft=10,
                                    effective_from="2026-01-01")
        rapid_two = new_prescription(activate=False, voltage_class="DISTRIBUTION_12KV",
                                     growth_zone="RAPID", base_cycle_years=3,
                                     clearance_radius_ft=12, effective_from="2026-06-01")

        activated = validate_success(api.activate_prescription(rapid_two["id"], FORESTER), 200)

        assert activated["status"] == "ACTIVE"
        assert read_prescription(rapid_one["id"])["status"] == "SUPERSEDED"
        assert read_prescription(moderate["id"])["status"] == "ACTIVE", \
            "a different growth_zone peer is untouched"
        _, meta = validate_paginated(api.list_prescriptions(
            FORESTER, params={"voltage_class": "DISTRIBUTION_12KV", "status": "ACTIVE"}))
        assert meta["total_count"] == 2

    def test_prescription_list_reports_total_count_and_has_more(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of records matching the
        request's filters before the page window is applied, and `has_more` is true exactly
        when records matching the filters remain beyond the current page."

        Design: Corner/entities/corner_prescriptions_list_paginates_with_total_count_and_has_more
        """
        for zone, years in (("RAPID", 4), ("MODERATE", 5), ("SLOW", 6)):
            new_prescription(activate=False, voltage_class="DISTRIBUTION_12KV",
                             growth_zone=zone, base_cycle_years=years,
                             clearance_radius_ft=10, effective_from="2026-01-01")

        resp = api.list_prescriptions(FORESTER, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(resp)

        assert resp.json()["response_type"] == "array"
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        rows2, meta2 = validate_paginated(
            api.list_prescriptions(FORESTER, params={"limit": 2, "offset": 2}))
        assert len(rows2) == 1
        assert meta2["has_more"] is False

    def test_pagination_limit_above_the_maximum_is_rejected(self, api):
        """PRD §2.3: "A `limit` outside the inclusive range 1 through 100, a negative `offset`,
        or a non-integer value for either is rejected with `ERR_PAGINATION_INVALID`
        (HTTP 400)."

        Design: Corner/validations/corner_pagination_limit_above_max_returns_invalid_request
        """
        setup_circuit()

        resp = api.list_circuits(FORESTER, params={"limit": 101, "offset": 0})

        validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)
        assert resp.status_code == 400

        rows, meta = validate_paginated(api.list_circuits(FORESTER, params={"limit": 100}))
        assert meta["total_count"] == 1


def _circuit_with_three_tree_outages():
    """CKT-A (12kV / RAPID, 1200 customers) carrying three qualifying outages."""
    world = setup_circuit()
    circuit_id = world["circuit"]["id"]
    for at, cause in (("2024-09-10T00:00:00Z", "TREE_GROWN_IN"),
                      ("2025-05-20T00:00:00Z", "TREE_FELL_ON"),
                      ("2026-02-11T00:00:00Z", "TREE_GROWN_IN")):
        new_outage(circuit_id, outage_at=at, cause_code=cause,
                   customers_affected=300, customer_minutes=1500)
    return world


class TestReliabilityWindows:

    def test_reliability_read_reports_both_window_variants_side_by_side(self, api):
        """PRD §3.2: "The rolling window runs from the instant 36 calendar months before the
        logical clock through the logical clock, with both ends inclusive, and its result is
        stored as `reliability_index_36mo`."
        PRD §3.2: "The program-year-to-date window runs from midnight UTC on 1 January of the
        logical clock's calendar year through the logical clock, again with both ends
        inclusive, and its result is stored as `reliability_index_ytd`; because it starts
        later, it yields a strictly smaller numerator whenever any qualifying outage predates
        that 1 January, and it never influences the tier."

        Design: Difficulty/dual_variant_calc/reliability_index_rolling36_vs_program_ytd_diverge
        """
        world = _circuit_with_three_tree_outages()
        circuit_id = world["circuit"]["id"]
        new_outage(circuit_id, outage_at="2026-03-01T00:00:00Z", cause_code="NON_TREE",
                   customers_affected=900, customer_minutes=9000)
        new_outage(circuit_id, outage_at="2026-07-01T00:00:00Z", cause_code="TREE_FELL_ON",
                   customers_affected=300, customer_minutes=1500)

        report = validate_success(api.get_circuit_reliability(circuit_id, FORESTER), 200)

        assert report["circuit_id"] == circuit_id
        assert report["rolling_36_month_index"] == pytest.approx(5.00, abs=0.001)
        assert report["program_year_to_date_index"] == pytest.approx(2.50, abs=0.001)
        assert report["tree_caused_outage_count_36mo"] == 4
        assert report["reliability_tier"] == "TIER_ELEVATED"

    def test_stored_reliability_indices_carry_both_variants_and_exclude_non_tree(self, api):
        """PRD §3.2: "Only tree causes count: a record whose `cause_code` is `TREE_GROWN_IN` or
        `TREE_FELL_ON` qualifies, and a `NON_TREE` record never enters either window even
        though it is stored and returned like any other."
        PRD §3.2: "The reliability index over a window is the sum of `customer_minutes` across
        the circuit's qualifying records whose `outage_at` falls inside the window, divided by
        the circuit's `customer_count` — or by 1 if the circuit serves zero customers, so the
        division is always defined — and rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/reliability_index_rolling36_vs_program_ytd_diverge
        """
        world = _circuit_with_three_tree_outages()
        circuit_id = world["circuit"]["id"]
        non_tree = new_outage(circuit_id, outage_at="2026-03-01T00:00:00Z",
                              cause_code="NON_TREE", customers_affected=900,
                              customer_minutes=9000)
        new_outage(circuit_id, outage_at="2026-07-01T00:00:00Z", cause_code="TREE_FELL_ON",
                   customers_affected=300, customer_minutes=1500)

        circuit = read_circuit(circuit_id)

        assert_outage_record(non_tree)
        assert circuit["reliability_index_36mo"] == pytest.approx(5.00, abs=0.001)
        assert circuit["reliability_index_ytd"] == pytest.approx(2.50, abs=0.001)
        assert circuit["tree_caused_outage_count_36mo"] == 4, \
            "the NON_TREE record must not be counted"
        assert circuit["reliability_tier"] == "TIER_ELEVATED"

    def test_three_tree_outages_leave_the_cycle_at_tier_normal(self, api):
        """PRD §3.2: "The tier is read off that count: six or more qualifying outages in the
        rolling window puts the circuit at `TIER_CRITICAL`, four or five puts it at
        `TIER_ELEVATED`, and anything below four leaves it at `TIER_NORMAL`."
        PRD §3.2: "Multiply again by the reliability factor for the circuit's current
        `reliability_tier` — 1.00 at `TIER_NORMAL`, 0.80 at `TIER_ELEVATED`, and 0.60 at
        `TIER_CRITICAL`."

        Design: Difficulty/combinatorial_formula/trim_cycle_months_nested_clamp_over_growth_and_tier_factors
        """
        world = _circuit_with_three_tree_outages()

        circuit = read_circuit(world["circuit"]["id"])

        assert circuit["reliability_tier"] == "TIER_NORMAL"
        assert circuit["cycle_months"] == 36, "4 * 12 * 0.75 * 1.00 = 36 inside [24, 72]"
        assert circuit["next_trim_due_on"] == "2027-03-15"

    def test_fourth_tree_outage_elevates_the_tier_and_shortens_the_cycle(self, api):
        """PRD §3.2: "When the tier changes, `cycle_months` and `next_trim_due_on` are
        recomputed on the spot with the new reliability factor; either way, filing an outage
        increments the circuit's `version` by 1."
        PRD §3.2: "Round that product half-up to a whole number of months, and only then clamp
        it into the band the voltage class permits."

        Design: Difficulty/combinatorial_formula/trim_cycle_months_nested_clamp_over_growth_and_tier_factors
        """
        world = _circuit_with_three_tree_outages()
        circuit_id = world["circuit"]["id"]

        resp = api.create_outage_record(create_outage_record_payload(
            circuit_id, outage_at="2026-07-01T00:00:00Z", cause_code="TREE_FELL_ON",
            customers_affected=300, customer_minutes=1500), FORESTER)
        validate_success(resp, 201)

        circuit = read_circuit(circuit_id)
        assert circuit["reliability_tier"] == "TIER_ELEVATED"
        assert circuit["cycle_months"] == 29, "4 * 12 * 0.75 * 0.80 = 28.8 rounds half-up to 29"
        assert circuit["next_trim_due_on"] == "2026-08-15"

    def test_sixth_tree_outage_drives_critical_tier_and_clamps_to_the_voltage_floor(self, api):
        """PRD §3.2: "The floor is 24 months for `DISTRIBUTION_4KV` and `DISTRIBUTION_12KV`,
        30 months for `DISTRIBUTION_35KV`, and 36 months for `SUBTRANSMISSION_69KV` and
        `TRANSMISSION_115KV`."
        PRD §3.2: "The tier is read off that count: six or more qualifying outages in the
        rolling window puts the circuit at `TIER_CRITICAL`, four or five puts it at
        `TIER_ELEVATED`, and anything below four leaves it at `TIER_NORMAL`."

        Design: Corner/calculations/corner_reliability_critical_tier_clamps_cycle_to_voltage_floor
        """
        world = setup_circuit()
        circuit_id = world["circuit"]["id"]
        for at in ("2024-09-10T00:00:00Z", "2025-05-20T00:00:00Z", "2026-02-11T00:00:00Z",
                   "2026-03-11T00:00:00Z", "2026-04-11T00:00:00Z"):
            new_outage(circuit_id, outage_at=at, cause_code="TREE_GROWN_IN",
                       customers_affected=300, customer_minutes=1500)
        before = read_circuit(circuit_id)
        assert before["reliability_tier"] == "TIER_ELEVATED" and before["cycle_months"] == 29

        new_outage(circuit_id, outage_at="2026-07-01T00:00:00Z", cause_code="TREE_FELL_ON",
                   customers_affected=300, customer_minutes=1500)

        circuit = read_circuit(circuit_id)
        assert circuit["tree_caused_outage_count_36mo"] == 6
        assert circuit["reliability_tier"] == "TIER_CRITICAL"
        assert circuit["cycle_months"] == 24, "4 * 12 * 0.75 * 0.60 = 21.6 -> 22, lifted to the floor"
        assert circuit["next_trim_due_on"] == "2026-03-15"
        assert read_reliability(circuit_id)["reliability_tier"] == "TIER_CRITICAL"


class TestOutageAttribution:

    def test_non_tree_outage_may_not_carry_an_attributed_span(self, api):
        """PRD §3.2: "Two attribution rules are enforced together and rejected with
        `ERR_OUTAGE_CAUSE_INVALID` (HTTP 422): an outage whose `cause_code` is `NON_TREE` may
        not carry a `work_order_id` at all, and an outage that does carry one must name a span
        whose owning plan covers the same circuit as the outage's `circuit_id`."

        Design: Corner/validations/corner_non_tree_outage_with_span_is_rejected
        """
        from test_helpers import setup_completed_span
        world = setup_completed_span()
        circuit_id = world["circuit"]["id"]

        bad = api.create_outage_record(create_outage_record_payload(
            circuit_id, outage_at="2026-07-01T00:00:00Z", cause_code="NON_TREE",
            customers_affected=100, customer_minutes=900,
            work_order_id=world["span"]["id"]), FORESTER)
        validate_error(bad, ApiErrorId.ERR_OUTAGE_CAUSE_INVALID.value)
        assert bad.status_code == 422

        ok = api.create_outage_record(create_outage_record_payload(
            circuit_id, outage_at="2026-07-01T00:00:00Z", cause_code="NON_TREE",
            customers_affected=100, customer_minutes=900), FORESTER)
        validate_success(ok, 201)

        circuit = read_circuit(circuit_id)
        assert circuit["tree_caused_outage_count_36mo"] == 0
        assert circuit["reliability_index_36mo"] == pytest.approx(0.00, abs=0.001)
        assert circuit["reliability_tier"] == "TIER_NORMAL"
