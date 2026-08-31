"""Carrier compliance: insurance, findings, suspension, reinstatement and scoring."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_safety_finding,
    build_network,
    compile_statement,
    create_haul_contractor,
    dispatch_load,
    depart_load,
    file_all_coverages,
    list_certificates,
    list_findings,
    read_certificate,
    read_haul_contractor,
    read_load,
    read_mill_contract,
    read_truck,
    revoke_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheTwoScoringWindows:
    def test_the_rolling_window_ignores_a_finding_older_than_one_hundred_eighty_days(
        self, api, safety_headers
    ):
        """PRD §3.2: "From that base the system subtracts the sum of `points` over
        every safety finding on the carrier whose `occurred_on` falls inside the
        scoring window, both endpoints inclusive; subtracts 25 points for each of the
        three required coverage types that has no certificate deriving `ACTIVE` at the
        clock date; and subtracts 3 points for each load of that carrier whose
        `dispatch_status` is `REJECTED` and whose `rejected_on` falls inside the
        scoring window, again with both endpoints inclusive."
        PRD §3.2: "The **rolling window** runs from 180 days before the clock date
        through the clock date, both endpoints inclusive, with missing coverage
        assessed at the clock date; this is the variant written to the carrier's
        `compliance_score` field and the variant consulted at the dispatch gate, where
        a score below 70 refuses the load with `ERR_COMPLIANCE_SCORE_TOO_LOW`."
        PRD §3.2: "A `MINOR` finding costs points but changes no status."

        Design: Difficulty/dual_variant_calc/rolling_180_day_versus_period_to_date_compliance_score_on_one_carrier
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])

        validate_success(
            api.create_safety_finding(
                carrier["id"],
                {
                    "severity": "MINOR",
                    "points": 20,
                    "occurred_on": "2026-01-20",
                    "note": "unsecured wrapper",
                },
                safety_headers,
            ),
            201,
        )
        validate_success(
            api.create_safety_finding(
                carrier["id"],
                {
                    "severity": "MINOR",
                    "points": 10,
                    "occurred_on": "2026-07-15",
                    "note": "log bunk wear",
                },
                safety_headers,
            ),
            201,
        )

        row = read_haul_contractor(carrier["id"])
        assert row["compliance_score"] == 90, (
            "the 2026-01-20 finding falls outside the rolling 180-day window"
        )
        assert row["compliance_status"] == "COMPLIANT"

    def test_the_period_to_date_window_scores_the_same_history_differently(
        self, api, safety_headers
    ):
        """PRD §3.2: "The **period-to-date window** runs from a settlement statement's
        `period_start` through its `period_end`, both endpoints inclusive, with missing
        coverage still assessed at the clock date; this is the variant frozen onto a
        statement as `compliance_score_at_compile` and the only variant the
        insurance-holdback tier reads."
        PRD §3.9: "A `holdback_pct` is selected from that frozen score: nothing at all
        when the score is 90 or above, 2 percent when it is at least 80 but below 90, 5
        percent when it is at least 70 but below 80, and 10 percent below 70."

        Design: Difficulty/dual_variant_calc/rolling_180_day_versus_period_to_date_compliance_score_on_one_carrier
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])
        scn = {"hc_id": carrier["id"]}

        validate_success(
            api.create_safety_finding(
                carrier["id"],
                {
                    "severity": "MINOR",
                    "points": 20,
                    "occurred_on": "2026-01-20",
                    "note": "unsecured wrapper",
                },
                safety_headers,
            ),
            201,
        )
        validate_success(
            api.create_safety_finding(
                carrier["id"],
                {
                    "severity": "MINOR",
                    "points": 10,
                    "occurred_on": "2026-07-15",
                    "note": "log bunk wear",
                },
                safety_headers,
            ),
            201,
        )

        statement = compile_statement(
            scn, period_start="2026-01-01", period_end="2026-08-31"
        )

        assert statement["compliance_score_at_compile"] == 70
        assert statement["holdback_pct"] == pytest.approx(0.05)
        assert (
            statement["compliance_score_at_compile"]
            != read_haul_contractor(carrier["id"])["compliance_score"]
        ), "the two windows deliberately score the same history differently"
        assert statement["gross_pay_cents"] == 0
        assert len(statement["lines"]) == 0


class TestInsuranceCascade:
    def test_revoking_a_required_coverage_suspends_the_carrier_and_its_fleet(self, api):
        """PRD §3.2: "A certificate's `status` is derived, in this order of precedence:
        it is `REVOKED` if `revoked_at` is not null; otherwise `PENDING` if the clock
        date falls before `effective_on`; otherwise `EXPIRED` if the clock date falls
        after `expires_on`; otherwise `ACTIVE`."
        PRD §3.2: "If that revocation leaves any of the three required coverage types
        with no `ACTIVE` certificate, the four-hop insurance cascade runs: the carrier's
        `compliance_status` becomes `SUSPENDED`; because the carrier is suspended, every
        truck it owns derives `OUT_OF_SERVICE`; because those trucks are out of service,
        every load on them whose `dispatch_status` is `DISPATCHED`, `IN_TRANSIT` or
        `AT_MILL` moves to `CANCELLED`; and because those loads were cancelled, each
        affected mill contract loses that load's `estimated_net_tons` from
        `reserved_tons`, recomputes `available_tons`, and returns from `FILLED` to
        `OPEN` if the recomputed figure rose above zero."

        Design: Difficulty/transitive_cascade/insurance_revocation_cascade_carrier_truck_load_contract
        """
        scn = build_network()
        dispatch_load(scn)

        revoke_certificate(scn["cert_gl_id"], reason="policy cancelled for non-payment")

        assert (
            read_certificate(scn["hc_id"], scn["cert_gl_id"])["status"] == "REVOKED"
        )
        carrier = read_haul_contractor(scn["hc_id"])
        assert carrier["compliance_status"] == "SUSPENDED"
        assert carrier["compliance_score"] == 75
        assert read_truck(scn["hc_id"], scn["truck_id"])["status"] == "OUT_OF_SERVICE"

    def test_the_revocation_cancels_the_in_flight_load_and_frees_its_reservation(
        self, api
    ):
        """PRD §3.2: "If that revocation leaves any of the three required coverage types
        with no `ACTIVE` certificate, the four-hop insurance cascade runs: the carrier's
        `compliance_status` becomes `SUSPENDED`; because the carrier is suspended, every
        truck it owns derives `OUT_OF_SERVICE`; because those trucks are out of service,
        every load on them whose `dispatch_status` is `DISPATCHED`, `IN_TRANSIT` or
        `AT_MILL` moves to `CANCELLED`; and because those loads were cancelled, each
        affected mill contract loses that load's `estimated_net_tons` from
        `reserved_tons`, recomputes `available_tons`, and returns from `FILLED` to
        `OPEN` if the recomputed figure rose above zero."

        Design: Difficulty/transitive_cascade/insurance_revocation_cascade_carrier_truck_load_contract
        """
        scn = build_network()
        load = dispatch_load(scn)
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            26.50, abs=0.005
        )

        revoke_certificate(scn["cert_gl_id"], reason="policy cancelled for non-payment")

        assert read_load(load["id"])["dispatch_status"] == "CANCELLED"
        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(500.00, abs=0.005)
        assert contract["status"] == "OPEN"


class TestSafetyFindingsAndReinstatement:
    def test_a_safety_finding_is_an_append_only_record_without_version(
        self, api, safety_headers
    ):
        """PRD §2.4: "One entity is the exception: a safety finding is an immutable
        audit record, so a `SafetyFinding` carries only `id` and `created_at` — it has
        neither `updated_at` nor `version`, and neither field appears in its
        representation."
        PRD §3.2: "Findings may be listed for a carrier with a filter on `severity`."
        PRD §3.2: "A `MINOR` finding costs points but changes no status."

        Design: Corner/entities/safety_finding_is_immutable_and_carries_no_version_field
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])

        finding = validate_success(
            api.create_safety_finding(
                carrier["id"],
                {
                    "severity": "MINOR",
                    "points": 5,
                    "occurred_on": "2026-07-30",
                    "note": "tarp strap frayed",
                },
                safety_headers,
            ),
            201,
        )

        assert_safety_finding(finding)
        assert finding["points"] == 5
        assert finding["occurred_on"] == "2026-07-30"
        assert "version" not in finding
        assert "updated_at" not in finding

        listed = list_findings(carrier["id"])
        assert [row["id"] for row in listed] == [finding["id"]]
        assert read_haul_contractor(carrier["id"])["compliance_score"] == 95

    def test_a_critical_finding_drives_the_same_four_hop_suspension_cascade(
        self, api, safety_headers
    ):
        """PRD §3.2: "A `CRITICAL` finding recorded against a carrier that is
        `COMPLIANT` or `WARNED` drives the same four-hop suspension cascade as an
        insurance revocation: `compliance_status` becomes `SUSPENDED` and the score is
        recomputed, the carrier's trucks derive `OUT_OF_SERVICE`, their non-terminal
        loads move to `CANCELLED`, and the affected mill contracts release reserved
        tons with a `FILLED` contract returning to `OPEN`."

        Design: Corner/state_machines/critical_safety_finding_suspends_the_carrier_and_cancels_its_in_flight_load
        """
        scn = build_network()
        load = dispatch_load(scn)
        depart_load(scn, load["id"])

        validate_success(
            api.create_safety_finding(
                scn["hc_id"],
                {
                    "severity": "CRITICAL",
                    "points": 40,
                    "occurred_on": "2026-08-01",
                    "note": "brake system out of adjustment",
                },
                safety_headers,
            ),
            201,
        )

        carrier = read_haul_contractor(scn["hc_id"])
        assert carrier["compliance_status"] == "SUSPENDED"
        assert carrier["compliance_score"] == 60
        assert read_truck(scn["hc_id"], scn["truck_id"])["status"] == "OUT_OF_SERVICE"
        assert read_load(load["id"])["dispatch_status"] == "CANCELLED"

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(500.00, abs=0.005)

    def test_reinstating_a_carrier_whose_coverage_is_revoked_is_refused(
        self, api, safety_headers
    ):
        """PRD §3.2: "A `SafetyOfficer` may return a `SUSPENDED` carrier to
        `COMPLIANT`, supplying an optional `note`, but only when each of
        `GENERAL_LIABILITY`, `AUTO_LIABILITY` and `WORKERS_COMP` has at least one
        certificate deriving `ACTIVE`; attempting it while any required coverage is
        uncovered is refused with `ERR_INSURANCE_COVERAGE_INCOMPLETE`."

        Design: Corner/validations/reinstating_a_carrier_with_a_revoked_coverage_is_rejected
        """
        scn = build_network()
        revoke_certificate(scn["cert_gl_id"], reason="policy cancelled")

        response = api.reinstate_haul_contractor(
            scn["hc_id"], {"note": "carrier claims coverage restored"}, safety_headers
        )
        validate_error(
            response, ApiErrorId.ERR_INSURANCE_COVERAGE_INCOMPLETE.value, 422
        )

        assert read_certificate(scn["hc_id"], scn["cert_gl_id"])["status"] == "REVOKED"
        carrier = read_haul_contractor(scn["hc_id"])
        assert carrier["compliance_status"] == "SUSPENDED"
        assert carrier["compliance_score"] == 75
        assert read_truck(scn["hc_id"], scn["truck_id"])["status"] == "OUT_OF_SERVICE"

    def test_the_carrier_subresource_lists_all_three_active_coverages(
        self, api, safety_headers
    ):
        """PRD §3.2: "Three coverage types are required of every carrier:
        `GENERAL_LIABILITY`, `AUTO_LIABILITY` and `WORKERS_COMP`."
        PRD §3.2: "Certificates may be listed for a carrier with filters on
        `coverage_type` and `status`."
        PRD §3.2: "Filing a certificate recomputes the carrier's `compliance_score` and
        increments the carrier's `version` by 1 — which matters, because that `version`
        is the one a settlement compile must pin."

        Design: Corner/endpoints/insurance_certificate_subresource_lists_all_three_coverages
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])

        rows, meta = validate_paginated(
            api.list_insurance_certificates(
                carrier["id"], safety_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3
        assert all(row["status"] == "ACTIVE" for row in rows)
        assert {row["coverage_type"] for row in rows} == {
            "GENERAL_LIABILITY",
            "AUTO_LIABILITY",
            "WORKERS_COMP",
        }

        final = read_haul_contractor(carrier["id"])
        assert final["compliance_score"] == 100
        assert final["compliance_status"] == "COMPLIANT"
