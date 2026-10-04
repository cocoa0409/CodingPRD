"""Carrier agreements: membership rules, monitoring member-set coverage,
half-open period overlap, the 45-day waiting period, and the HHI
competitive-concern gate."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_agreement,
    create_agreement_payload,
    create_monitoring_report_payload,
    make_carrier,
    make_carrier_rep_headers,
    set_logical_clock,
    setup_carrier_shipper,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["reviewer_headers"]
DOCKET = TEST_USERS["docket_headers"]


def _two_carriers(prefix="Lines"):
    a = make_carrier(org_type="VOCC", org_name=f"Alpha {prefix}")
    b = make_carrier(org_type="VOCC", org_name=f"Beta {prefix}")
    return a, b


def _volumes(a_id, b_id, a_teus, b_teus):
    return [{"carrier_id": a_id, "carried_teus": a_teus},
            {"carrier_id": b_id, "carried_teus": b_teus}]


class TestAgreementMembership:
    def test_agreement_membership_rules_enforced(self):
        """PRD §3.8: "Membership is policed at filing: there must be at least
        two distinct members, every member must be a vessel-operating common
        carrier in `ACTIVE` standing, and the filing carrier's own organization
        must appear among the members — a failing membership is rejected with
        `ERR_INVALID_AGREEMENT_MEMBERSHIP` (HTTP 422)."

        Design: Corner/validations/agreement_membership_rules_enforced
        """
        set_logical_clock()
        ca, cb = _two_carriers("Member Lines")
        cn = make_carrier(org_type="NVOCC", org_name="Member NVOCC Co")

        r1 = api_client.create_agreement(create_agreement_payload(
            [ca["id"]], agreement_number="AG-BAD-1"),
            make_carrier_rep_headers(ca["id"]))
        validate_error(r1, ApiErrorId.ERR_INVALID_AGREEMENT_MEMBERSHIP)

        r2 = api_client.create_agreement(create_agreement_payload(
            [ca["id"], cn["id"]], agreement_number="AG-BAD-2"),
            make_carrier_rep_headers(ca["id"]))
        validate_error(r2, ApiErrorId.ERR_INVALID_AGREEMENT_MEMBERSHIP)

        r3 = api_client.create_agreement(create_agreement_payload(
            [ca["id"], cb["id"]], agreement_number="AG-BAD-3"),
            make_carrier_rep_headers(cn["id"]))
        validate_error(r3, ApiErrorId.ERR_INVALID_AGREEMENT_MEMBERSHIP)

        rows, meta = validate_paginated(api_client.list_agreements(DOCKET))
        assert meta["total_count"] == 0


class TestMonitoringReports:
    def test_monitoring_report_must_cover_exactly_the_member_set(self):
        """PRD §3.8: "The `member_volumes` must cover exactly the member set:
        every entry's `carrier_id` must be a member of the agreement, and every
        member must be covered — a mismatch is rejected with
        `ERR_MEMBER_SET_MISMATCH` (HTTP 422)."

        Design: Corner/validations/monitoring_report_must_cover_exactly_the_member_set
        """
        set_logical_clock()
        ca, cb = _two_carriers("Cover Lines")
        agreement = validate_success(api_client.create_agreement(
            create_agreement_payload([ca["id"], cb["id"]],
                                     agreement_number="AG-2026-09",
                                     agreement_type="SPACE_CHARTER"),
            make_carrier_rep_headers(ca["id"])), 201)

        r = api_client.append_monitoring_report(agreement["id"],
            create_monitoring_report_payload(1000, _volumes(ca["id"], cb["id"], 300, 0)[:1]),
            make_carrier_rep_headers(ca["id"]))
        validate_error(r, ApiErrorId.ERR_MEMBER_SET_MISMATCH)

        after = validate_success(api_client.get_agreement(agreement["id"], DOCKET), 200)
        assert after["monitoring_reports"] == []
        assert after["market_concentration_hhi"] is None

    def test_monitoring_reports_adjacent_periods_accepted(self):
        """PRD §3.8: "Reporting periods are half-open: a period includes its
        start and excludes its end, a new period must not overlap any existing
        report's period on the same agreement — though touching boundaries,
        where one period's end equals another's start, are allowed".
        PRD §3.8: "The agreement's `market_concentration_hhi` tracks the `hhi`
        of the report with the latest `reporting_period_end` among all reports
        on the agreement".

        Design: Difficulty/resource_temporal_overlap/monitoring_reports_half_open_adjacency_allowed_overlap_rejected
        """
        set_logical_clock()
        ca, cb = _two_carriers("Overlap Lines")
        agreement = validate_success(api_client.create_agreement(
            create_agreement_payload([ca["id"], cb["id"]],
                                     agreement_number="AG-2026-02",
                                     agreement_type="SPACE_CHARTER"),
            make_carrier_rep_headers(ca["id"])), 201)
        rep = make_carrier_rep_headers(ca["id"])

        r1 = api_client.append_monitoring_report(agreement["id"],
            create_monitoring_report_payload(1000, _volumes(ca["id"], cb["id"], 300, 200)),
            rep)
        validate_success(r1, 201)
        r2 = api_client.append_monitoring_report(agreement["id"],
            create_monitoring_report_payload(
                1000, _volumes(ca["id"], cb["id"], 300, 200),
                reporting_period_start="2026-04-01T00:00:00Z",
                reporting_period_end="2026-07-01T00:00:00Z"),
            rep)
        data = validate_success(r2, 201)
        assert len(data["monitoring_reports"]) == 2, (
            "the second period starts exactly where the first ends — allowed")
        # 30.0000^2 + 20.0000^2 = 900.00 + 400.00 = 1300.00.
        assert data["market_concentration_hhi"] == pytest.approx(1300.0, abs=0.005)
        assert data["competitive_concern_flag"] is False

    def test_monitoring_reports_overlapping_period_rejected(self):
        """PRD §3.8: "an intersecting submission is rejected with
        `ERR_MONITORING_PERIOD_OVERLAP` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/monitoring_reports_half_open_adjacency_allowed_overlap_rejected
        """
        set_logical_clock()
        ca, cb = _two_carriers("Overlap Lines")
        agreement = validate_success(api_client.create_agreement(
            create_agreement_payload([ca["id"], cb["id"]],
                                     agreement_number="AG-2026-02",
                                     agreement_type="SPACE_CHARTER"),
            make_carrier_rep_headers(ca["id"])), 201)
        rep = make_carrier_rep_headers(ca["id"])
        for start, end in (("2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"),
                           ("2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z")):
            validate_success(api_client.append_monitoring_report(agreement["id"],
                create_monitoring_report_payload(
                    1000, _volumes(ca["id"], cb["id"], 300, 200),
                    reporting_period_start=start, reporting_period_end=end),
                rep), 201)

        r3 = api_client.append_monitoring_report(agreement["id"],
            create_monitoring_report_payload(
                1000, _volumes(ca["id"], cb["id"], 300, 200),
                reporting_period_start="2026-03-01T00:00:00Z",
                reporting_period_end="2026-05-01T00:00:00Z"),
            rep)
        validate_error(r3, ApiErrorId.ERR_MONITORING_PERIOD_OVERLAP)
        after = validate_success(api_client.get_agreement(agreement["id"], DOCKET), 200)
        assert len(after["monitoring_reports"]) == 2
        assert after["market_concentration_hhi"] == pytest.approx(1300.0, abs=0.005)


class TestGoEffectiveGates:
    def test_waiting_period_44_days_rejected_45_exact_accepted(self):
        """PRD §3.8: "the `waiting_period_ends_at` is set forty-five days after
        filing" and "the logical clock must have reached `waiting_period_ends_at`,
        otherwise `ERR_WAITING_PERIOD_NOT_ELAPSED` (HTTP 422)".

        Design: Corner/calculations/waiting_period_44_days_rejected_45_exact_accepted
        """
        set_logical_clock()
        ca, cb = _two_carriers("Wait Lines")
        agreement = validate_success(api_client.create_agreement(
            create_agreement_payload([ca["id"], cb["id"]],
                                     agreement_number="AG-WAIT-1",
                                     agreement_type="RATE_DISCUSSION"),
            make_carrier_rep_headers(ca["id"])), 201)
        assert agreement["waiting_period_ends_at"] == "2026-10-16T00:00:00Z", (
            "filed_at 2026-09-01T00:00:00Z + 45 days")

        set_logical_clock("2026-10-15T00:00:00Z")
        r1 = api_client.go_effective(agreement["id"], REVIEWER)
        validate_error(r1, ApiErrorId.ERR_WAITING_PERIOD_NOT_ELAPSED)

        set_logical_clock("2026-10-16T00:00:00Z")
        data = validate_success(api_client.go_effective(agreement["id"], REVIEWER), 200)
        assert data["review_status"] == "EFFECTIVE"

    def test_agreement_go_effective_twice_returns_not_awaiting_review(self):
        """PRD §3.8: "the agreement's `review_status` must stand in
        `AWAITING_REVIEW`, otherwise `ERR_AGREEMENT_NOT_AWAITING_REVIEW`
        (HTTP 409)".

        Design: Corner/state_machines/agreement_go_effective_twice_returns_not_awaiting_review
        """
        set_logical_clock()
        ca, cb = _two_carriers("Terminal Lines")
        agreement = validate_success(api_client.create_agreement(
            create_agreement_payload([ca["id"], cb["id"]],
                                     agreement_number="AG-TERM-1",
                                     agreement_type="EQUIPMENT_POOLING"),
            make_carrier_rep_headers(ca["id"])), 201)
        set_logical_clock("2026-10-16T00:00:00Z")
        first = validate_success(api_client.go_effective(agreement["id"], REVIEWER), 200)
        assert first["review_status"] == "EFFECTIVE"

        r2 = api_client.go_effective(agreement["id"], REVIEWER)
        validate_error(r2, ApiErrorId.ERR_AGREEMENT_NOT_AWAITING_REVIEW)

    def test_hhi_exactly_2500_blocks_go_effective_while_249201_allows(self):
        """PRD §3.8: "The `competitive_concern_flag` is true exactly when that
        concentration figure reaches or exceeds 2500." and "the
        `competitive_concern_flag` must be false — a latest-report concentration
        at or above the 2500 threshold blocks effectiveness with
        `ERR_COMPETITIVE_CONCERN_UNRESOLVED` (HTTP 409)."

        Design: Corner/calculations/hhi_exactly_2500_blocks_go_effective_while_249201_allows
        """
        set_logical_clock()
        ca, cb = _two_carriers("HHI Lines")
        rep = make_carrier_rep_headers(ca["id"])
        ag_hi = validate_success(api_client.create_agreement(
            create_agreement_payload([ca["id"], cb["id"]], agreement_number="AG-HI"),
            rep), 201)
        ag_lo = validate_success(api_client.create_agreement(
            create_agreement_payload([ca["id"], cb["id"]], agreement_number="AG-LO"),
            rep), 201)

        hi = validate_success(api_client.append_monitoring_report(ag_hi["id"],
            create_monitoring_report_payload(1000, _volumes(ca["id"], cb["id"], 400, 300)),
            rep), 201)
        # shares 40.0000 / 30.0000 -> 1600.00 + 900.00 = 2500.00.
        assert hi["market_concentration_hhi"] == pytest.approx(2500.0, abs=0.005)
        assert hi["competitive_concern_flag"] is True

        lo = validate_success(api_client.append_monitoring_report(ag_lo["id"],
            create_monitoring_report_payload(1000, _volumes(ca["id"], cb["id"], 399, 300)),
            rep), 201)
        # shares 39.9000 / 30.0000 -> 1592.01 + 900.00 = 2492.01.
        assert lo["market_concentration_hhi"] == pytest.approx(2492.01, abs=0.005)
        assert lo["competitive_concern_flag"] is False

        set_logical_clock("2026-10-16T00:00:00Z")
        r_hi = api_client.go_effective(ag_hi["id"], REVIEWER)
        validate_error(r_hi, ApiErrorId.ERR_COMPETITIVE_CONCERN_UNRESOLVED)
        data_lo = validate_success(api_client.go_effective(ag_lo["id"], REVIEWER), 200)
        assert data_lo["review_status"] == "EFFECTIVE"
