"""Temporal overlap windows: half-open policy activation windows and
closed-interval impact-report periods."""
from test_helpers import (
    ApiErrorId,
    create_eligibility_policy_payload,
    get_success_data,
    make_eligibility_officer_headers,
    make_platform_admin_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestPolicyWindowOverlap:
    def test_half_open_overlap_and_adjacency(self, api):
        """PRD §3.2: "no two `ACTIVE` policies in the same `state_code` may have
        overlapping half-open windows, and a violation is rejected with
        `ERR_POLICY_WINDOW_OVERLAP`. Adjacency is not overlap — when one
        policy's `effective_to` equals another's `effective_from`, both may be
        active."

        Design: Difficulty/resource_temporal_overlap/policy_window_half_open_overlap_and_adjacency
        """
        set_clock()
        eo = make_eligibility_officer_headers()
        p1 = get_success_data(
            api.create_eligibility_policy(create_eligibility_policy_payload(), eo)
        )
        get_success_data(api.activate_eligibility_policy(p1["id"], eo))
        # Interior intersection with the ACTIVE window is rejected.
        p_ovl = get_success_data(
            api.create_eligibility_policy(
                create_eligibility_policy_payload(
                    name="Overlap TX",
                    effective_from="2026-06-01",
                    effective_to="2027-06-01",
                ),
                eo,
            )
        )
        resp = api.activate_eligibility_policy(p_ovl["id"], eo)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP, 409)
        fetched = get_success_data(api.get_eligibility_policy(p_ovl["id"], eo))
        assert fetched["status"] == "DRAFT"
        # A window starting exactly at the other's end is adjacent, not overlap.
        p_adj = get_success_data(
            api.create_eligibility_policy(
                create_eligibility_policy_payload(
                    name="Adjacent TX",
                    effective_from="2027-01-01",
                    effective_to="2028-01-01",
                ),
                eo,
            )
        )
        data = validate_success(api.activate_eligibility_policy(p_adj["id"], eo), 200)
        assert data["status"] == "ACTIVE"
        # Overlap is scoped per state_code: the same dates in CA are fine.
        p_ca = get_success_data(
            api.create_eligibility_policy(
                create_eligibility_policy_payload(
                    name="CA Overlap OK",
                    state_code="CA",
                    effective_from="2026-06-01",
                    effective_to="2027-06-01",
                ),
                eo,
            )
        )
        data = validate_success(api.activate_eligibility_policy(p_ca["id"], eo), 200)
        assert data["status"] == "ACTIVE"

    def test_adjacency_allowed_at_both_sides(self, api):
        """PRD §3.2: "Adjacency is not overlap — when one policy's
        `effective_to` equals another's `effective_from`, both may be active."

        Design: Difficulty/resource_temporal_overlap/policy_window_half_open_overlap_and_adjacency
        """
        set_clock()
        eo = make_eligibility_officer_headers()
        p_mid = get_success_data(
            api.create_eligibility_policy(
                create_eligibility_policy_payload(
                    name="TX Mid",
                    effective_from="2026-06-01",
                    effective_to="2026-12-01",
                ),
                eo,
            )
        )
        get_success_data(api.activate_eligibility_policy(p_mid["id"], eo))
        p_left = get_success_data(
            api.create_eligibility_policy(
                create_eligibility_policy_payload(
                    name="TX Left",
                    effective_from="2026-01-01",
                    effective_to="2026-06-01",
                ),
                eo,
            )
        )
        p_right = get_success_data(
            api.create_eligibility_policy(
                create_eligibility_policy_payload(
                    name="TX Right",
                    effective_from="2026-12-01",
                    effective_to="2027-06-01",
                ),
                eo,
            )
        )
        left = validate_success(
            api.activate_eligibility_policy(p_left["id"], eo), 200
        )
        right = validate_success(
            api.activate_eligibility_policy(p_right["id"], eo), 200
        )
        assert left["status"] == "ACTIVE"
        assert right["status"] == "ACTIVE"


class TestReportPeriodOverlap:
    def test_closed_interval_boundary_sharing_is_overlap(self, api):
        """PRD §3.10: "no two `PUBLISHED` reports sharing the same scope and
        scope key may have overlapping closed periods, and because the
        intervals are inclusive, even sharing a single boundary date counts as
        overlap. A violation is rejected with `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_overlap
        """
        set_clock()
        admin = make_platform_admin_headers()
        r1 = get_success_data(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-09-01",
                    "period_end": "2026-09-30",
                    "counting_variant": "PER_ACCOUNT",
                },
                admin,
            )
        )
        assert r1["households_relieved"] == 0
        assert r1["dollars_abolished_cents"] == 0
        get_success_data(api.publish_impact_report(r1["id"], admin))
        r2 = get_success_data(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-09-30",
                    "period_end": "2026-10-31",
                    "counting_variant": "PER_ACCOUNT",
                },
                admin,
            )
        )
        assert r2["households_relieved"] == 0
        assert r2["dollars_abolished_cents"] == 0
        r3 = get_success_data(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-10-01",
                    "period_end": "2026-10-31",
                    "counting_variant": "PER_ACCOUNT",
                },
                admin,
            )
        )
        # Sharing the boundary date 2026-09-30 is an overlap for closed
        # intervals.
        resp = api.publish_impact_report(r2["id"], admin)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP, 409)
        fetched = get_success_data(api.get_impact_report(r2["id"], admin))
        assert fetched["status"] == "DRAFT"
        # The first fully disjoint day publishes fine.
        resp = api.publish_impact_report(r3["id"], admin)
        data = validate_success(resp, 200)
        assert data["status"] == "PUBLISHED"

    def test_disjoint_periods_publish_independently(self, api):
        """PRD §3.10: "no two `PUBLISHED` reports sharing the same scope and
        scope key may have overlapping closed periods, and because the
        intervals are inclusive, even sharing a single boundary date counts as
        overlap."

        Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_overlap
        """
        set_clock()
        admin = make_platform_admin_headers()
        r1 = get_success_data(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-09-01",
                    "period_end": "2026-09-30",
                    "counting_variant": "PER_ACCOUNT",
                },
                admin,
            )
        )
        get_success_data(api.publish_impact_report(r1["id"], admin))
        r2 = get_success_data(
            api.create_impact_report(
                {
                    "scope": "GLOBAL",
                    "period_start": "2026-11-01",
                    "period_end": "2026-11-30",
                    "counting_variant": "DEDUPED_HOUSEHOLD",
                },
                admin,
            )
        )
        data = validate_success(api.publish_impact_report(r2["id"], admin), 200)
        assert data["status"] == "PUBLISHED"
