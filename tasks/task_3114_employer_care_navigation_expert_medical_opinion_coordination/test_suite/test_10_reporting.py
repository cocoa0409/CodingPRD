"""Employer reporting: steerage savings variants and utilization aggregation
status filters."""
from test_helpers import (
    validate_success,
    create_member_payload, create_quality_snapshot_payload,
    set_clock, setup_employer_with_member,
    setup_provider, setup_provider_with_snapshot, grant_consent,
    setup_navigation_case, setup_closed_navigation_case,
    setup_booked_appointment,
    setup_billing_case_error_identified, claim_line,
)
from test_helpers.test_users import (
    make_member_headers,
    make_employer_admin_headers,
    make_billing_advocate_headers,
)


class TestSteerageVariants:
    def test_steerage_savings_naive_vs_counterfactual_on_same_bookings(
            self, api):
        """PRD §3.10: "The naive view, `steerage_naive_cents`, credits every
        such appointment: the count of the base set times the employer's
        `avg_in_out_cost_delta_cents`. The counterfactual view,
        `steerage_counterfactual_cents`, credits only genuine redirections: the
        count of base-set appointments with `redirected_from_out_of_network`
        true, times the same delta."

        Design: Difficulty/dual_variant_calc/steerage_savings_naive_vs_counterfactual_on_same_bookings
        """
        set_clock()
        emp, member = setup_employer_with_member(
            employer_overrides={"name": "BetaWorks",
                                "avg_in_out_cost_delta_cents": 300000})
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider, _ = setup_provider_with_snapshot(
            {"name": "HeartFirst Clinic", "specialty": "CARDIOLOGY"},
            create_quality_snapshot_payload())
        nc = setup_navigation_case(
            member, {"question_type": "COST", "estimated_cost_cents": 100000})

        for day, redirected in (("2026-09-10", True), ("2026-09-11", True),
                                ("2026-09-12", False)):
            setup_booked_appointment(
                member, provider,
                f"{day}T09:00:00Z", f"{day}T09:30:00Z",
                navigation_case_id=nc["id"],
                redirected_from_out_of_network=redirected)

        report = validate_success(api.get_utilization_report(
            emp["id"], make_employer_admin_headers("ea-1")))
        assert report["steerage_naive_cents"] == 900000
        assert report["steerage_counterfactual_cents"] == 600000
        assert report["steerage_naive_cents"] != report["steerage_counterfactual_cents"]

    def test_steerage_variants_equal_when_all_bookings_are_redirections(
            self, api):
        """PRD §3.10: "The two differ whenever any in-network navigation-booked
        appointment was not a redirection, and both are reported side by side."

        Design: Difficulty/dual_variant_calc/steerage_savings_naive_vs_counterfactual_on_same_bookings
        """
        set_clock()
        emp, member = setup_employer_with_member(
            employer_overrides={"name": "AllRedirectCo",
                                "avg_in_out_cost_delta_cents": 300000})
        grant_consent(member, "APPOINTMENT_BOOKING")
        provider, _ = setup_provider_with_snapshot(
            {"name": "HeartFirst Clinic", "specialty": "CARDIOLOGY"},
            create_quality_snapshot_payload())
        nc = setup_navigation_case(
            member, {"question_type": "COST", "estimated_cost_cents": 100000})

        for day in ("2026-09-10", "2026-09-11"):
            setup_booked_appointment(
                member, provider,
                f"{day}T09:00:00Z", f"{day}T09:30:00Z",
                navigation_case_id=nc["id"],
                redirected_from_out_of_network=True)

        report = validate_success(api.get_utilization_report(
            emp["id"], make_employer_admin_headers("ea-1")))
        assert report["steerage_naive_cents"] == 600000
        assert report["steerage_counterfactual_cents"] == 600000


class TestUtilizationAggregation:
    def test_utilization_report_aggregation_status_filters(
            self, api, platform_admin_headers):
        """PRD §3.10: "It reports `members_active`, the count of the employer's
        members whose `eligibility_status` is `ACTIVE`;
        `navigation_cases_total`, all navigation cases of the employer's
        members in any status; `navigation_cases_closed`, those in `CLOSED`;
        and `emos_delivered`, the count of expert opinion cases in
        `DELIVERED`."
        PRD §3.10: "Finally, `total_attributed_savings_cents` is the sum of
        `billing_savings_final_cents` and `steerage_counterfactual_cents`."

        Design: Corner/calculations/utilization_report_aggregation_status_filters
        """
        set_clock()
        emp, ma = setup_employer_with_member(
            employer_overrides={"name": "ReportCo",
                                "avg_in_out_cost_delta_cents": 200000},
            member_overrides={"external_member_ref": "RC-1"})
        mb = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="Rep B", external_member_ref="RC-2"),
            platform_admin_headers), expected_status=201)
        validate_success(api.deactivate_member(
            mb["id"], platform_admin_headers))

        grant_consent(ma, "APPOINTMENT_BOOKING")
        grant_consent(ma, "BILLING_ADVOCACY")

        setup_closed_navigation_case(ma, navigator_id="adv-1")
        nc2 = setup_navigation_case(ma, {"question_type": "BENEFIT"})

        provider = setup_provider(name="Report Clinic")
        setup_booked_appointment(
            ma, provider, "2026-09-10T09:00:00Z", "2026-09-10T09:30:00Z",
            navigation_case_id=nc2["id"],
            redirected_from_out_of_network=False)

        _, bc = setup_billing_case_error_identified(
            ma, provider,
            claim_overrides={
                "billed_amount_cents": 100000, "allowed_amount_cents": 90000,
                "lines": [claim_line("A", 100000, 0.7, "UPCODING")]})
        validate_success(api.propose_settlement(
            bc["id"], {"counter_offer_cents": 60000},
            make_billing_advocate_headers("ba-1")))
        validate_success(api.accept_settlement(
            bc["id"], make_member_headers(ma["id"])))

        report = validate_success(api.get_utilization_report(
            emp["id"], make_employer_admin_headers("ea-1")))
        assert report["members_active"] == 1
        assert report["navigation_cases_total"] == 2
        assert report["navigation_cases_closed"] == 1
        assert report["emos_delivered"] == 0
        assert report["billing_savings_provisional_cents"] == 30000
        assert report["billing_savings_final_cents"] == 40000
        assert report["steerage_naive_cents"] == 200000
        assert report["steerage_counterfactual_cents"] == 0
        assert report["total_attributed_savings_cents"] == 40000
