"""Completeness review: the cyclic return-incomplete / resubmit loop, its
resubmission counter, fee recomputation, and the ninety-day window
(PRD §2.8, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    begin_review,
    create_district,
    create_owner,
    create_property,
    make_applicant_headers,
    resubmit,
    return_incomplete,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]


class TestApplicationResubmissionCycle:
    def test_resubmission_cycle_counts_each_resubmit(self, api):
        """PRD §3.3: "Resubmission replaces the `work_items` array wholesale
        with the payload's revised items (which must again be non-empty, or
        `ERR_EMPTY_WORK_ITEMS`), optionally updates
        `is_visible_from_public_way`, recomputes `declared_cost_cents` and
        `provisional_fee_cents` from the new declared items, increments
        `resubmission_count` by one, and returns the application to
        `UNDER_STAFF_REVIEW`."

        Design: Difficulty/non_linear_state_machine/application_resubmission_cycle
        """
        district = create_district(name="Old Town", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            work_items=[work_item("SITE_WORK", "walkway", 100000)],
        )
        begin_review(submitted["id"])

        return_incomplete(submitted["id"], "Missing elevation drawings")
        first = resubmit(
            submitted["id"], owner["id"], [work_item("SITE_WORK", "walkway rev1", 120000)]
        )
        assert first["status"] == "UNDER_STAFF_REVIEW"
        assert first["resubmission_count"] == 1

        return_incomplete(submitted["id"], "Material spec still missing")
        second = resubmit(
            submitted["id"], owner["id"], [work_item("SITE_WORK", "walkway rev2", 150000)]
        )
        assert second["status"] == "UNDER_STAFF_REVIEW"
        assert second["resubmission_count"] == 2

    def test_resubmission_recomputes_declared_cost_and_fee(self, api):
        """PRD §3.3: "Resubmission replaces the `work_items` array wholesale
        with the payload's revised items (which must again be non-empty, or
        `ERR_EMPTY_WORK_ITEMS`), optionally updates
        `is_visible_from_public_way`, recomputes `declared_cost_cents` and
        `provisional_fee_cents` from the new declared items, increments
        `resubmission_count` by one, and returns the application to
        `UNDER_STAFF_REVIEW`."
        PRD §3.2: "a `SITE_WORK` item a base of 10,000 cents at 0.2 percent."

        Design: Difficulty/non_linear_state_machine/application_resubmission_cycle
        """
        district = create_district(name="Old Town", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            work_items=[work_item("SITE_WORK", "walkway", 100000)],
        )
        assert submitted["declared_cost_cents"] == 100000
        begin_review(submitted["id"])
        return_incomplete(submitted["id"])
        resubmit(submitted["id"], owner["id"], [work_item("SITE_WORK", "walkway rev1", 120000)])
        return_incomplete(submitted["id"])

        second = validate_success(
            api.resubmit_application(
                submitted["id"],
                {"work_items": [work_item("SITE_WORK", "walkway rev2", 150000)]},
                make_applicant_headers(owner["id"]),
            )
        )
        assert second["declared_cost_cents"] == 150000
        # 10000 + round_half_up(0.002 * 150000) = 10300, recomputed from the
        # new declared items.
        assert second["provisional_fee_cents"] == 10300


def test_begin_review_twice_returns_invalid_state(api):
    """PRD §3.3: "A `PreservationStaff` user takes up an application by
    beginning review, moving it from `SUBMITTED` to `UNDER_STAFF_REVIEW`."
    PRD §2.8: "The target resource must be in a state from which the requested
    transition is declared in §3; otherwise the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/begin_review_twice_returns_invalid_state
    """
    owner = create_owner()
    prop = create_property(owner["id"])
    submitted = submit_application(
        prop["id"], owner["id"], work_items=[work_item("SITE_WORK", "wall", 60000)]
    )
    begin_review(submitted["id"])

    response = api.begin_review(submitted["id"], STAFF)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    application = validate_success(api.get_application(submitted["id"], STAFF))
    assert application["status"] == "UNDER_STAFF_REVIEW"


def test_resubmit_after_ninety_day_window_lapsed(api):
    """PRD §3.3: "The applicant then has ninety days: resubmission is permitted
    only while the logical clock is no later than `returned_at` plus ninety
    days, and a later attempt is rejected with `ERR_RESUBMISSION_WINDOW_LAPSED`."

    Design: Corner/validations/resubmit_day_91_lapsed
    """
    set_clock("2026-08-01T00:00:00Z")
    owner = create_owner()
    prop = create_property(owner["id"])
    submitted = submit_application(
        prop["id"], owner["id"], work_items=[work_item("SITE_WORK", "wall", 200000)]
    )
    begin_review(submitted["id"])
    returned = return_incomplete(submitted["id"], "Missing specs")
    assert returned["status"] == "INCOMPLETE"

    # returned_at 2026-08-01 + 90 days = 2026-10-30; 2026-10-31 is past.
    set_clock("2026-10-31T00:00:00Z")
    response = api.resubmit_application(
        submitted["id"],
        {"work_items": [work_item("SITE_WORK", "wall rev", 210000)]},
        make_applicant_headers(owner["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RESUBMISSION_WINDOW_LAPSED)
