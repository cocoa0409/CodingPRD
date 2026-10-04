"""Reverse-reachability reads, pagination and one computed read."""
from test_helpers import (
    ADMIN,
    CALIBRATION_PASS_THRESHOLD,
    MID_REGULAR_CLOCK_UTC,
    SPECIALIST,
    api_client,
    calibrate_reader,
    create_audit,
    create_registration,
    create_school,
    get_success_data,
    recruit_reader,
    setup_open_order,
    validate_paginated,
    validate_success,
)


def test_school_course_audit_listing_paginates_with_has_more():
    """PRD §2.3: "`total_count` is the number of rows matching the filter before pagination and `has_more` is true when further rows remain past the current page."
    PRD §2.3: "Reverse-reachability reads — the nested lists reached through a parent resource, such as the course audits of a school, the registrations of an order, the scores of a registration, the sends of a score, or the cases of a registration — accept the same `limit` and `offset` parameters and obey the same ordering rule."

    Design: Corner/endpoints/school_course_audits_pagination_and_has_more
    """
    school = create_school()
    audit_ids = [create_audit(school, course_title=f"AP Course {index}")["id"] for index in range(3)]

    page_one, meta_one = validate_paginated(
        api_client.list_school_course_audits(school["id"], ADMIN, params={"limit": 2, "offset": 0})
    )
    page_two, meta_two = validate_paginated(
        api_client.list_school_course_audits(school["id"], ADMIN, params={"limit": 2, "offset": 2})
    )

    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert sorted(seen) == sorted(audit_ids)
    assert len(set(seen)) == 3, "no row may appear on both pages"


def test_order_registrations_reverse_read_returns_the_created_registration():
    """PRD §2.3: "Reverse-reachability reads — the nested lists reached through a parent resource, such as the course audits of a school, the registrations of an order, the scores of a registration, the sends of a score, or the cases of a registration — accept the same `limit` and `offset` parameters and obey the same ordering rule."
    PRD §3.3: "the row opens in `REGISTERED` with `fees_paid_cents` at 0, `fee_waived` false, `accommodation_flag` false and zeroed fee fields"

    Design: Corner/endpoints/order_registrations_reverse_read_returns_created_registration
    """
    bundle = setup_open_order(clock=MID_REGULAR_CLOCK_UTC)
    registration = create_registration(
        bundle["order"], bundle["student"], bundle["school"], exam_subject="AP-CSA"
    )

    data, meta = validate_paginated(
        api_client.list_order_registrations(
            bundle["order"]["id"], ADMIN, params={"limit": 10, "offset": 0}
        )
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == registration["id"]
    assert data[0]["exam_order_id"] == bundle["order"]["id"]
    assert data[0]["status"] == "REGISTERED"
    assert data[0]["late_fee_cents"] == 0


def test_reader_calibration_summary_reports_the_weighted_index():
    """PRD §3.7: "the same 0.9000 agreement over a full 20-paper sample yields 0.9100, which passes."
    PRD §3.7: "the calibration summary read returns the same numbers side by side together with `calibration_round_count` and a `pass_threshold_met` boolean"
    PRD §3.7: "sets `load_status` to `AT_CAPACITY` when the reader's `assigned_score_count` has reached 120, or `AVAILABLE` otherwise"

    Design: Corner/endpoints/reader_calibration_summary_computed_read
    """
    reader = calibrate_reader(recruit_reader("AP-LATIN"), samples=20, agreement=0.9000)

    summary = validate_success(
        api_client.get_reader_calibration_summary(reader["id"], SPECIALIST)
    )

    assert summary["calibration_index"] == 0.9100, (
        f"0.9000 * 0.90 + 1.0 * 0.10 - 0.0 should be 0.91, got {summary['calibration_index']}"
    )
    assert summary["calibration_index"] > CALIBRATION_PASS_THRESHOLD
    assert abs(summary["reliability_index"] - 0.9) < 1e-9
    assert summary["pass_threshold_met"] is True
    assert summary["calibration_round_count"] == 1
    assert summary["load_status"] == "AVAILABLE"
