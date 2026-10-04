"""Purchaser networks, grade utilisation and benefit-window containment."""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_employer_payload,
    employer_with_mixed_graded_network,
    and_instant_equal,
    make_purchaser_headers,
    register_employer,
    register_hospital,
    relist_employer,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["rating_admin_headers"]
READER = TEST_USERS["reader_headers"]
PURCHASER = TEST_USERS["purchaser_headers"]


class TestEmployerRegistration:

    def test_invalid_minimum_letter_is_refused_and_creates_nothing(self):
        """PRD §3.8: "the minimum letter must be one of the four permitted
        values, or it is refused with `ERR_INVALID_MINIMUM_LETTER`."
        PRD §5: "| `ERR_INVALID_MINIMUM_LETTER` | 400 |"

        Design: Corner/errors/invalid_minimum_letter_error_is_triggerable
        """
        response = api_client.create_employer(
            {
                "name": "Bad Letter Trust",
                "purchaser_type": "COALITION",
                "minimum_acceptable_letter": "E",
                "benefit_window_from": "2026-01-01T00:00:00Z",
                "benefit_window_to": "2026-12-31T00:00:00Z",
                "network_hospital_ids": [],
            },
            {"X-User-ID": "emp-bad", "X-User-Role": "PurchaserAdmin",
             "Content-Type": "application/json"},
        )
        validate_error(response, "ERR_INVALID_MINIMUM_LETTER", 400)
        rows, _meta = validate_paginated(api_client.list_employers(READER))
        assert rows == []


class TestBenefitWindowContainment:

    def test_strict_containment_is_refused_while_touching_windows_are_allowed(self):
        """PRD §3.8: "A benefit-design window that strictly contains another
        employer's window inside the same combination of `purchaser_type` and
        `minimum_acceptable_letter` is refused with
        `ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT`; windows that merely touch —
        one's `benefit_window_to` equalling the other's `benefit_window_from` —
        are accepted."

        Design: Difficulty/resource_temporal_overlap/employer_benefit_window_strict_containment
        """
        hospital = register_hospital()
        incumbent = register_employer(
            [hospital["id"]], name="E1 Benefits Trust",
            benefit_window_from="2026-01-01T00:00:00Z",
            benefit_window_to="2026-12-31T00:00:00Z")

        contained = api_client.create_employer(
            create_employer_payload(
                [hospital["id"]], name="E2 Benefits Trust",
                benefit_window_from="2026-03-01T00:00:00Z",
                benefit_window_to="2026-09-30T00:00:00Z"),
            make_purchaser_headers("emp-e2"))
        validate_error(contained, "ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT", 409)

        touching = register_employer(
            [hospital["id"]], name="E3 Benefits Trust",
            benefit_window_from="2026-12-31T00:00:00Z",
            benefit_window_to="2027-06-30T00:00:00Z")
        assert and_instant_equal(touching["benefit_window_from"], "2026-12-31T00:00:00Z")

        coincident = api_client.create_employer(
            create_employer_payload(
                [hospital["id"]], name="E4 Benefits Trust",
                benefit_window_from="2026-01-01T00:00:00Z",
                benefit_window_to="2026-12-31T00:00:00Z"),
            make_purchaser_headers("emp-e4"))
        validate_error(coincident, "ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT", 409)

        unchanged = validate_success(api_client.get_employer(incumbent["id"], READER))
        assert and_instant_equal(unchanged["benefit_window_from"], "2026-01-01T00:00:00Z")
        assert and_instant_equal(unchanged["benefit_window_to"], "2026-12-31T00:00:00Z")
        assert unchanged["network_hospital_count"] == 1

    def test_containment_is_scoped_to_the_same_purchaser_type_and_letter(self):
        """PRD §3.8: "A benefit-design window that strictly contains another
        employer's window inside the same combination of `purchaser_type` and
        `minimum_acceptable_letter` is refused with
        `ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/employer_benefit_window_strict_containment
        """
        hospital = register_hospital()
        incumbent = register_employer(
            [hospital["id"]], name="E1 Benefits Trust",
            purchaser_type="SELF_INSURED_EMPLOYER", minimum_acceptable_letter="B",
            benefit_window_from="2026-01-01T00:00:00Z",
            benefit_window_to="2026-12-31T00:00:00Z")

        nested_same_scope = api_client.create_employer(
            create_employer_payload(
                [hospital["id"]], name="E1a Benefits Trust",
                purchaser_type="SELF_INSURED_EMPLOYER", minimum_acceptable_letter="B",
                benefit_window_from="2026-02-01T00:00:00Z",
                benefit_window_to="2026-11-30T00:00:00Z"),
            make_purchaser_headers("emp-e1a"))
        validate_error(nested_same_scope, "ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT", 409)

        other_letter = register_employer(
            [hospital["id"]], name="E1b Benefits Trust",
            purchaser_type="SELF_INSURED_EMPLOYER", minimum_acceptable_letter="A",
            benefit_window_from="2026-02-01T00:00:00Z",
            benefit_window_to="2026-11-30T00:00:00Z")
        assert other_letter["minimum_acceptable_letter"] == "A"

        still = validate_success(api_client.get_employer(incumbent["id"], READER))
        assert still["network_hospital_count"] == 1


class TestNetworkListing:

    def test_referential_tier_precedes_the_temporal_tier_on_a_listing(self):
        """PRD §3.8: "Every entry of `network_hospital_ids` must resolve to an
        existing hospital, or the call is refused with `ERR_HOSPITAL_NOT_FOUND`."
        PRD §3.8: "A benefit-design window that strictly contains another
        employer's window inside the same combination of `purchaser_type` and
        `minimum_acceptable_letter` is refused with
        `ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT`"

        Design: Difficulty/priority_pair_validation_conflict/referential_tier_precedes_temporal_tier_on_network_listing
        """
        hospital = register_hospital()
        employer = register_employer(
            [hospital["id"]], name="E1 Benefits Trust",
            benefit_window_from="2026-01-01T00:00:00Z",
            benefit_window_to="2026-12-31T00:00:00Z")

        unknown = "00000000-0000-4000-8000-000000000099"
        both_faults = api_client.set_network_listing(
            employer["id"],
            {"network_hospital_ids": [hospital["id"], unknown],
             "minimum_acceptable_letter": "B",
             "benefit_window_from": "2026-03-01T00:00:00Z",
             "benefit_window_to": "2026-09-30T00:00:00Z"},
            make_purchaser_headers(employer["id"]))
        error_data = validate_error(both_faults, "ERR_HOSPITAL_NOT_FOUND", 404)
        assert error_data["error_id"] != "ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT"

        unchanged = validate_success(api_client.get_employer(employer["id"], READER))
        assert unchanged["network_hospital_count"] == 1

        # The temporal tier is reachable once every id resolves: a new employer
        # whose window contains the incumbent's violates PRD §3.8's
        # no-containment rule and is refused with the containment conflict.
        only_temporal = api_client.create_employer(
            create_employer_payload(
                [hospital["id"]], name="E2 Benefits Trust",
                benefit_window_from="2025-06-01T00:00:00Z",
                benefit_window_to="2027-06-01T00:00:00Z"),
            make_purchaser_headers("emp-e2"))
        validate_error(only_temporal, "ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT", 409)

    def test_an_unresolvable_id_is_reported_even_beside_a_containment_clash(self):
        """PRD §3.8: "Every entry of `network_hospital_ids` must resolve to an
        existing hospital, or the call is refused with `ERR_HOSPITAL_NOT_FOUND`."

        Design: Difficulty/priority_pair_validation_conflict/referential_tier_precedes_temporal_tier_on_network_listing
        """
        hospital = register_hospital()
        employer = register_employer(
            [hospital["id"]], name="E1 Benefits Trust",
            benefit_window_from="2026-01-01T00:00:00Z",
            benefit_window_to="2026-12-31T00:00:00Z")

        response = api_client.set_network_listing(
            employer["id"],
            {"network_hospital_ids": [hospital["id"],
                                      "00000000-0000-4000-8000-000000000097"],
             "minimum_acceptable_letter": "B",
             "benefit_window_from": "2026-04-01T00:00:00Z",
             "benefit_window_to": "2026-08-31T00:00:00Z"},
            make_purchaser_headers(employer["id"]))
        validate_error(response, "ERR_HOSPITAL_NOT_FOUND", 404)
        unchanged = validate_success(api_client.get_employer(employer["id"], READER))
        assert unchanged["network_hospital_count"] == 1
        # PRD §2.2: server-generated instants are "ISO 8601 UTC timestamp[s]
        # with three fractional digits", so an unchanged window round-trips to
        # the same instant rather than the bare-seconds form.
        assert and_instant_equal(unchanged["benefit_window_from"], "2026-01-01T00:00:00Z")

    def test_relisting_is_a_conserved_hospital_count(self):
        """PRD §3.8: "Duplicate entries collapse to their first occurrence, so
        the effective network is order-insensitive and the
        `network_hospital_count` is the count of distinct hospital identifiers
        after that collapse."

        Design: Difficulty/compensating_invariant/employer_network_relisting_restores_hospital_count
        """
        hospitals = [register_hospital() for _ in range(4)]
        employer = register_employer([hospitals[0]["id"], hospitals[1]["id"], hospitals[2]["id"]])
        assert employer["network_hospital_count"] == 3

        forward = relist_employer(
            employer["id"],
            [hospitals[0]["id"], hospitals[1]["id"], hospitals[2]["id"],
             hospitals[3]["id"], hospitals[3]["id"]])
        assert forward["network_hospital_count"] == 4, (
            "the duplicated id collapses to a single addition")

        back = relist_employer(
            employer["id"], [hospitals[0]["id"], hospitals[1]["id"], hospitals[2]["id"]])
        assert back["network_hospital_count"] == 3, "the count returns exactly to the baseline"

        refused = api_client.set_network_listing(
            employer["id"],
            {"network_hospital_ids": [hospitals[0]["id"],
                                      "00000000-0000-4000-8000-000000000098"],
             "minimum_acceptable_letter": "B",
             "benefit_window_from": "2026-01-01T00:00:00Z",
             "benefit_window_to": "2026-12-31T00:00:00Z"},
            make_purchaser_headers(employer["id"]))
        validate_error(refused, "ERR_HOSPITAL_NOT_FOUND", 404)
        unchanged = validate_success(api_client.get_employer(employer["id"], READER))
        assert unchanged["network_hospital_count"] == 3


class TestUtilizationIndex:

    def test_every_distinct_listed_hospital_is_counted_once(self):
        """PRD §3.8: "the `network_hospital_count` is the count of distinct
        hospital identifiers after that collapse."

        Design: Difficulty/combinatorial_formula/employer_propensity_frozen_candidate_set_order
        """
        ctx = employer_with_mixed_graded_network(extra_ungraded=2)
        employer = validate_success(api_client.get_employer(ctx.employer["id"], READER))
        assert employer["network_hospital_count"] == 4
        assert employer["eligible_hospital_count"] == 1, (
            "only the high-scoring hospital's published letter ranks at or above the floor")
        assert employer["utilization_index"] == pytest.approx(0.5000)
        assert employer["utilization_index"] != pytest.approx(0.2500), (
            "the two ungraded hospitals are excluded from the denominator rather than lowering it")

    def test_denominator_counts_only_the_graded_network_hospitals(self):
        """PRD §3.8: "The `utilization_index` is that eligible count divided by
        the number of distinct network hospitals that carry any grade row at
        all, rounded half up to four decimal places; the denominator
        deliberately excludes hospitals in the listed network with no grade, so
        a network in which every graded hospital clears the floor reports an
        index of `1.0000` regardless of how many ungraded hospitals are also
        listed."

        Design: Difficulty/combinatorial_formula/employer_propensity_frozen_candidate_set_order
        """
        ctx = employer_with_mixed_graded_network(extra_ungraded=2)
        employer = validate_success(api_client.get_employer(ctx.employer["id"], READER))
        assert employer["network_hospital_count"] == 4
        assert employer["eligible_hospital_count"] == 1
        assert employer["utilization_index"] == pytest.approx(0.5000)

        # A second read returns the same index: the counted set is not
        # re-selected after the indicator is known.
        again = validate_success(api_client.get_employer(ctx.employer["id"], READER))
        assert again["utilization_index"] == pytest.approx(0.5000)

    def test_utilization_index_carries_four_decimal_places(self):
        """PRD §2.6: "Reliability weights, sample rates, comparability indices,
        safe-practice credits, verification completeness values and purchaser
        utilization indices are expressed to four decimal places, round half up."

        Design: Corner/calculations/employer_index_precision_to_four_decimals
        """
        # PRD §3.8: the index "is that eligible count divided by the number of
        # distinct network hospitals that carry any grade row at all". The two
        # graded hospitals score 80.00 (letter B) and 5.00 (letter F) against a
        # floor of C, so exactly one of the two clears the floor and the index
        # is 1 / 2 = 0.5000 — carried to four decimal places.
        ctx = employer_with_mixed_graded_network(extra_ungraded=0)
        employer = validate_success(api_client.get_employer(ctx.employer["id"], READER))
        assert employer["utilization_index"] == pytest.approx(0.5000)
        assert round(employer["utilization_index"], 4) == employer["utilization_index"]

    def test_raising_the_minimum_letter_moves_the_eligible_set(self):
        """PRD §3.8: "The `eligible_hospital_count` is the number of distinct
        network hospitals whose grade carries a letter whose rank is at or above
        that floor."

        Design: Corner/state_machines/employer_network_listing_recomputes_utilization_and_regrades_by_letter
        """
        from test_helpers import published_cycle_with_grades

        ctx = published_cycle_with_grades(grades_spec=[80.0, 5.0],
                                          minimum_acceptable_letter="C")
        at_c = validate_success(api_client.get_employer(ctx.employer["id"], READER))
        assert at_c["eligible_hospital_count"] == 1

        at_b = relist_employer(
            ctx.employer["id"], [h["id"] for h in ctx.hospitals],
            minimum_acceptable_letter="B")
        assert at_b["eligible_hospital_count"] == 1
        assert at_b["utilization_index"] == pytest.approx(0.5000)

        at_a = relist_employer(
            ctx.employer["id"], [h["id"] for h in ctx.hospitals],
            minimum_acceptable_letter="A")
        assert at_a["eligible_hospital_count"] == 1, (
            "the hospital already ranks at A, so raising the floor to A does not shrink the set")