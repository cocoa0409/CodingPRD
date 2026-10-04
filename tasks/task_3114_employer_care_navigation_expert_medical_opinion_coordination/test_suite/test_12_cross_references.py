"""Cross-reference listings: children reachable from their parents."""
from test_helpers import (
    validate_success,
    create_member_payload, create_coverage_window_payload,
    create_claim_payload, create_billing_case_payload, claim_line,
    set_clock, setup_employer_with_member, setup_provider, grant_consent,
)
from test_helpers.test_users import (
    make_billing_advocate_headers,
    make_plan_administrator_headers,
)


class TestFkReverseReachability:
    def test_fk_reverse_reachability_lists_children_from_parent(
            self, api, platform_admin_headers):
        """PRD §3.1: "Coverage windows of a member can be listed with an
        optional `status` filter".
        PRD §3.8: "Billing cases can be listed per member or per claim."

        Design: Corner/endpoints/fk_reverse_reachability_lists_children_from_parent
        """
        set_clock()
        emp, m1 = setup_employer_with_member(member_overrides={
            "full_name": "Fk One", "external_member_ref": "FK-1"})
        m2 = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="Fk Two", external_member_ref="FK-2"),
            platform_admin_headers), expected_status=201)

        cw1 = validate_success(api.create_coverage_window(
            m1["id"], create_coverage_window_payload(
                coverage_tier="EMPLOYEE_ONLY", effective_start="2026-01-01",
                expected_member_version=m1["version"]),
            platform_admin_headers), expected_status=201)
        cw2 = validate_success(api.create_coverage_window(
            m2["id"], create_coverage_window_payload(
                coverage_tier="FAMILY", effective_start="2026-02-01",
                expected_member_version=m2["version"]),
            platform_admin_headers), expected_status=201)

        grant_consent(m1, "BILLING_ADVOCACY")
        provider = setup_provider(name="Fk Clinic")
        claim = validate_success(api.create_claim(
            create_claim_payload(
                member_id=m1["id"], provider_id=provider["id"],
                billed_amount_cents=50000, allowed_amount_cents=40000,
                lines=[claim_line("A", 50000, 1.0, "NONE")]),
            make_plan_administrator_headers("pa-1")), expected_status=201)
        bc = validate_success(api.create_billing_case(
            m1["id"], create_billing_case_payload(claim_id=claim["id"]),
            make_billing_advocate_headers("ba-1")), expected_status=201)

        windows_m1 = validate_success(api.list_coverage_windows(
            m1["id"], platform_admin_headers))
        assert [w["id"] for w in windows_m1] == [cw1["id"]]

        windows_m2 = validate_success(api.list_coverage_windows(
            m2["id"], platform_admin_headers))
        assert [w["id"] for w in windows_m2] == [cw2["id"]]

        cases = validate_success(api.list_claim_billing_cases(
            claim["id"], make_billing_advocate_headers("ba-1")))
        assert [c["id"] for c in cases] == [bc["id"]]
