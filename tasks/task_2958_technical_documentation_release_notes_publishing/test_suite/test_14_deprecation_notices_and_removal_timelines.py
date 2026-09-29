"""Deprecation notices, their arithmetic notice periods, and the migration guide.

Telling customers that a feature is disappearing is the one communication in
this domain with a legal shape, so the notice period is enforced by arithmetic
rather than by judgement.  This module covers the per-tier minimum notice
period at and either side of its boundary, the two timeline fields a draft
stores so the accepted plan stays auditable, and the two migration-guide gates
that decide whether a notice may be drafted at all and whether it may go out.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_deprecation_notice,
    create_deprecation_notice,
    create_deprecation_notice_payload,
    expected_earliest_removal_date,
    expected_notice_days,
    read_deprecation_notice,
    read_topic,
    set_clock,
    topic_context,
    validate_error,
    validate_list,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"


class TestMinimumNoticePeriod:
    """The per-tier minimum is a closed lower bound: one day short is refused and
    exact equality is accepted."""

    @pytest.mark.parametrize(
        ("severity_tier", "removal_date", "notice_days"),
        [("MAJOR", "2026-11-02", 89), ("BREAKING", "2027-01-31", 179)],
    )
    def test_a_deprecation_one_day_short_of_its_tier_minimum_is_refused(
        self, api, docs_lead_headers, severity_tier, removal_date, notice_days
    ):
        """A notice period one day below the tier's floor never becomes a draft.

        PRD §3.9: "`notice_days` is the whole number of days from
        `announce_date` to `removal_date`, and the minimum required is 180 days
        for a `BREAKING` tier, 90 days for `MAJOR`, and 30 days for `MINOR`; a
        `notice_days` value exactly equal to the minimum is compliant, and only
        a shorter period is refused, with `ERR_NOTICE_PERIOD_TOO_SHORT`."

        PRD §3.9: "The release train's own dates never relax the minimum."

        Design: Corner/validations/deprecation_notice_one_day_short_of_the_minimum_rejected
        """
        set_clock(CLOCK)
        guide = topic_context(train_overrides={"product_key": "ATLAS"})
        assert expected_notice_days("2026-08-05", removal_date) == notice_days

        response = api.create_deprecation_notice(
            create_deprecation_notice_payload(
                guide["train_id"],
                guide["topic_id"],
                severity_tier=severity_tier,
                announce_date="2026-08-05",
                deprecated_date="2026-09-01",
                removal_date=removal_date,
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.NOTICE_PERIOD_TOO_SHORT, 409)

        _, meta = validate_list(
            api.list_deprecation_notices(
                docs_lead_headers, params={"release_train_id": guide["train_id"]}
            )
        )
        assert meta["total_count"] == 0, "a refused notice must not leave a draft behind"

    def test_a_short_notice_period_is_not_reported_as_a_misordered_timeline(
        self, api, docs_lead_headers
    ):
        """An 89-day MAJOR timeline is correctly ordered, so the refusal is the
        notice-period one and not the date-window one.

        PRD §3.9: "Second, the timeline must be ordered: `announce_date` on or
        before `deprecated_date`, and `deprecated_date` strictly before
        `removal_date`, else `ERR_INVALID_DATE_WINDOW`."

        PRD §3.9: "`notice_days` is the whole number of days from
        `announce_date` to `removal_date`, and the minimum required is 180 days
        for a `BREAKING` tier, 90 days for `MAJOR`, and 30 days for `MINOR`; a
        `notice_days` value exactly equal to the minimum is compliant, and only
        a shorter period is refused, with `ERR_NOTICE_PERIOD_TOO_SHORT`."

        Design: Corner/validations/deprecation_notice_one_day_short_of_the_minimum_rejected
        """
        set_clock(CLOCK)
        guide = topic_context(train_overrides={"product_key": "ATLAS"})

        response = api.create_deprecation_notice(
            create_deprecation_notice_payload(
                guide["train_id"],
                guide["topic_id"],
                severity_tier="MAJOR",
                announce_date="2026-08-05",
                deprecated_date="2026-09-01",
                removal_date="2026-11-02",
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.NOTICE_PERIOD_TOO_SHORT, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.INVALID_DATE_WINDOW.value

    @pytest.mark.parametrize(
        ("severity_tier", "removal_date", "notice_days"),
        [("MAJOR", "2026-11-03", 90), ("BREAKING", "2027-02-01", 180)],
    )
    def test_a_deprecation_at_exactly_its_tier_minimum_is_accepted(
        self, api, docs_lead_headers, severity_tier, removal_date, notice_days
    ):
        """Exact equality with the tier floor is compliant, not borderline.

        PRD §3.9: "`notice_days` is the whole number of days from
        `announce_date` to `removal_date`, and the minimum required is 180 days
        for a `BREAKING` tier, 90 days for `MAJOR`, and 30 days for `MINOR`; a
        `notice_days` value exactly equal to the minimum is compliant, and only
        a shorter period is refused, with `ERR_NOTICE_PERIOD_TOO_SHORT`."

        PRD §4: "Creating a new resource returns HTTP 201; every other
        successful operation, including every state transition and every read,
        returns HTTP 200."

        Design: Corner/validations/deprecation_notice_at_exactly_the_minimum_notice_period_accepted
        """
        set_clock(CLOCK)
        guide = topic_context(train_overrides={"product_key": "ATLAS"})

        response = api.create_deprecation_notice(
            create_deprecation_notice_payload(
                guide["train_id"],
                guide["topic_id"],
                severity_tier=severity_tier,
                announce_date="2026-08-05",
                deprecated_date="2026-09-01",
                removal_date=removal_date,
            ),
            docs_lead_headers,
        )
        data = validate_success(response, 201)

        assert_deprecation_notice(data)
        assert data["severity_tier"] == severity_tier
        assert data["notice_days"] == notice_days
        assert data["notice_days"] == expected_notice_days("2026-08-05", removal_date)
        assert data["status"] == "DRAFTED"
        assert data["published_at"] is None

    def test_a_minimal_notice_period_makes_the_earliest_removal_date_the_requested_one(
        self, api, docs_lead_headers
    ):
        """At the floor the derived earliest removal date coincides exactly with
        the removal date the DocsLead asked for.

        PRD §3.9: "A draft stores both computed timeline fields so the accepted
        plan is auditable afterwards: `notice_days` as above, and
        `earliest_removal_date` as `announce_date` plus the tier's minimum
        notice period in days."

        Design: Corner/validations/deprecation_notice_at_exactly_the_minimum_notice_period_accepted
        """
        set_clock(CLOCK)
        guide = topic_context(train_overrides={"product_key": "ATLAS"})

        notice = create_deprecation_notice(
            guide["train_id"],
            guide["topic_id"],
            severity_tier="MAJOR",
            announce_date="2026-08-05",
            deprecated_date="2026-09-01",
            removal_date="2026-11-03",
        )

        assert notice["notice_days"] == 90
        assert notice["earliest_removal_date"] == "2026-11-03"
        assert notice["earliest_removal_date"] == notice["removal_date"]
        assert notice["earliest_removal_date"] == expected_earliest_removal_date(
            "2026-08-05", "MAJOR"
        )

        _, meta = validate_list(
            api.list_deprecation_notices(
                docs_lead_headers, params={"release_train_id": guide["train_id"]}
            )
        )
        assert meta["total_count"] == 1


class TestDerivedTimelineFields:
    """The two stored timeline figures are separate derivations: one measures the
    plan, the other measures the floor the tier imposes on it."""

    def test_notice_days_and_earliest_removal_date_are_derived_independently(
        self, api, docs_lead_headers
    ):
        """A generous MINOR plan stores 35 notice days against a 30-day floor.

        PRD §3.9: "A draft stores both computed timeline fields so the accepted
        plan is auditable afterwards: `notice_days` as above, and
        `earliest_removal_date` as `announce_date` plus the tier's minimum
        notice period in days."

        PRD §3.9: "The notice opens with `status` `DRAFTED` and `published_at`
        null, and notices are listable with filters on `release_train_id`,
        `migration_guide_topic_id`, `status`, and `severity_tier`."

        Design: Corner/calculations/deprecation_notice_days_and_earliest_removal_date_stored
        """
        set_clock(CLOCK)
        guide = topic_context(train_overrides={"product_key": "ATLAS"})

        notice = create_deprecation_notice(
            guide["train_id"],
            guide["topic_id"],
            severity_tier="MINOR",
            announce_date="2026-08-01",
            deprecated_date="2026-08-10",
            removal_date="2026-09-05",
        )

        assert notice["notice_days"] == 35
        assert notice["earliest_removal_date"] == "2026-08-31"
        assert notice["notice_days"] == expected_notice_days("2026-08-01", "2026-09-05")
        assert notice["earliest_removal_date"] == expected_earliest_removal_date(
            "2026-08-01", "MINOR"
        )
        assert notice["earliest_removal_date"] != notice["removal_date"]
        assert notice["status"] == "DRAFTED"
        assert notice["published_at"] is None
        assert notice["migration_guide_topic_id"] == guide["topic_id"]

        read_back = read_deprecation_notice(notice["id"])
        assert read_back["notice_days"] == 35
        assert read_back["earliest_removal_date"] == "2026-08-31"
        assert read_back["version"] == 1

        rows, meta = validate_list(
            api.list_deprecation_notices(
                docs_lead_headers, params={"migration_guide_topic_id": guide["topic_id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == notice["id"]


class TestMigrationGuideGates:
    """The guide a notice points at is checked twice: for its product line when the
    draft is written, and for being live when the notice goes out."""

    def test_a_migration_guide_on_another_product_line_pre_empts_the_notice_period_check(
        self, api, docs_lead_headers
    ):
        """A cross-product guide with only 19 days of notice reports the
        referential mismatch, never the short notice period.

        PRD §3.9: "First, the migration guide must belong to the same product
        line: the topic named by `migration_guide_topic_id` must resolve,
        through its plan item, to a release train whose `product_key` equals the
        notice's own train's `product_key`, and a mismatch is refused with
        `ERR_MIGRATION_GUIDE_PRODUCT_MISMATCH`."

        PRD §3.9: "Because the product-line check precedes the arithmetic, a
        notice that points at the wrong product line *and* allows too little
        notice reports the referential mismatch."

        Design: Corner/errors/migration_guide_product_mismatch_and_unpublished_guide_rejected
        """
        set_clock(CLOCK)
        atlas = topic_context(train_overrides={"product_key": "ATLAS"})
        nimbus = topic_context(train_overrides={"product_key": "NIMBUS"})
        assert expected_notice_days("2026-08-01", "2026-08-20") == 19

        response = api.create_deprecation_notice(
            create_deprecation_notice_payload(
                atlas["train_id"],
                nimbus["topic_id"],
                severity_tier="MINOR",
                announce_date="2026-08-01",
                deprecated_date="2026-08-10",
                removal_date="2026-08-20",
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.MIGRATION_GUIDE_PRODUCT_MISMATCH, 409)

        _, meta = validate_list(
            api.list_deprecation_notices(
                docs_lead_headers, params={"release_train_id": atlas["train_id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_publishing_a_notice_whose_migration_guide_is_not_live_is_refused(
        self, api, docs_lead_headers
    ):
        """With the announce date already reached, an unpublished guide is the
        remaining obstacle and it names itself.

        PRD §3.9: "And the migration guide topic must actually be live, with
        `publication_state` `PUBLISHED`, else
        `ERR_MIGRATION_GUIDE_NOT_PUBLISHED`; pointing customers at a page they
        cannot read is the one failure this workflow exists to prevent."

        PRD §3.9: "The logical clock's date must have reached or passed
        `announce_date`, else `ERR_ANNOUNCE_DATE_NOT_REACHED` — customers cannot
        be told before the announcement day."

        Design: Corner/errors/migration_guide_product_mismatch_and_unpublished_guide_rejected
        """
        set_clock(CLOCK)
        guide = topic_context(train_overrides={"product_key": "ATLAS"})
        notice = create_deprecation_notice(
            guide["train_id"],
            guide["topic_id"],
            severity_tier="MINOR",
            announce_date="2026-08-01",
            deprecated_date="2026-08-10",
            removal_date="2026-09-05",
        )
        assert read_topic(guide["topic_id"])["publication_state"] == "UNPUBLISHED"
        assert notice["notice_days"] == 35
        assert notice["earliest_removal_date"] == "2026-08-31"

        response = api.publish_deprecation_notice(notice["id"], {}, docs_lead_headers)
        validate_error(response, ApiErrorId.MIGRATION_GUIDE_NOT_PUBLISHED, 409)

        unchanged = read_deprecation_notice(notice["id"])
        assert unchanged["status"] == "DRAFTED"
        assert unchanged["published_at"] is None
        assert unchanged["version"] == 1
