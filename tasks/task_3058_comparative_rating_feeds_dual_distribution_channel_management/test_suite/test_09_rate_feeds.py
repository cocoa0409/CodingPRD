"""Rate feed publications: window geometry (strict overlap vs 24-hour gap),
recall terminality, rater OCC, and rater-code uniqueness."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_product,
    create_feed_publication,
    create_product_payload,
    create_rater,
    get_success_data,
    publish_feed,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

RM = TEST_USERS["rating_manager_headers"]
ADMIN = TEST_USERS["carrier_admin_headers"]


class TestFeedWindowGeometry:
    def _setup(self, api):
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            min_premium_cents=0,
        )
        rater = create_rater()
        feed_f1 = create_feed_publication(
            rater["id"], product["id"],
            effective_start="2026-02-01T00:00:00Z",
            effective_end="2026-03-01T00:00:00Z",
        )
        return product, rater, feed_f1

    def test_rate_feed_windows_require_24h_buffer_touching_rejected(self, api):
        """PRD §3.2: "a non-overlapping window that nonetheless leaves less than a
        24-hour gap to a sibling window — touching intervals count as less than 24
        hours, while exactly 24 hours is allowed — is rejected with
        `ERR_FEED_WINDOW_GAP_VIOLATION`; between the two, the strict-overlap check
        is evaluated first."

        Design: Difficulty/resource_temporal_overlap/rate_feed_windows_require_24h_buffer_touching_rejected
        """
        product, rater, feed_f1 = self._setup(api)
        rater_version = get_success_data(api.get_rater(rater["id"], RM))["version"]

        # Touching window (gap 0h): rejected
        resp_touch = api.create_feed_publication(
            rater["id"],
            {
                "product_id": product["id"],
                "effective_start": "2026-03-01T00:00:00Z",
                "effective_end": "2026-04-01T00:00:00Z",
                "rate_table_payload": {"t": "touching"},
                "expected_rater_version": rater_version,
            },
            RM,
        )
        validate_error(resp_touch, ApiErrorId.ERR_FEED_WINDOW_GAP_VIOLATION, 409)

        # 23h gap: rejected
        rater_version = get_success_data(api.get_rater(rater["id"], RM))["version"]
        resp_23h = api.create_feed_publication(
            rater["id"],
            {
                "product_id": product["id"],
                "effective_start": "2026-03-01T23:00:00Z",
                "effective_end": "2026-04-01T00:00:00Z",
                "rate_table_payload": {"t": "gap23h"},
                "expected_rater_version": rater_version,
            },
            RM,
        )
        validate_error(resp_23h, ApiErrorId.ERR_FEED_WINDOW_GAP_VIOLATION, 409)

        # Exactly 24h gap: allowed
        feed_ok = create_feed_publication(
            rater["id"], product["id"],
            effective_start="2026-03-02T00:00:00Z",
            effective_end="2026-04-01T00:00:00Z",
        )
        assert feed_ok["status"] == "DRAFT"

    def test_rate_feed_strict_overlap_rejected_before_gap_rule(self, api):
        """PRD §3.2: "strict overlap with an existing window is rejected with
        `ERR_FEED_WINDOW_OVERLAP`, and a non-overlapping window that nonetheless
        leaves less than a 24-hour gap to a sibling window — touching intervals
        count as less than 24 hours, while exactly 24 hours is allowed — is
        rejected with `ERR_FEED_WINDOW_GAP_VIOLATION`; between the two, the
        strict-overlap check is evaluated first."

        Design: Difficulty/resource_temporal_overlap/rate_feed_windows_require_24h_buffer_touching_rejected
        """
        product, rater, feed_f1 = self._setup(api)
        version_before = get_success_data(api.get_rater(rater["id"], RM))["version"]

        resp = api.create_feed_publication(
            rater["id"],
            {
                "product_id": product["id"],
                "effective_start": "2026-02-15T00:00:00Z",
                "effective_end": "2026-02-20T00:00:00Z",
                "rate_table_payload": {"t": "overlap"},
                "expected_rater_version": version_before,
            },
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_FEED_WINDOW_OVERLAP, 409)

        # Rejected creates do not advance the rater version
        version_after = get_success_data(api.get_rater(rater["id"], RM))["version"]
        assert version_after == version_before


class TestFeedRecallTerminality:
    def test_feed_publish_from_recall_rejected(self, api):
        """PRD §3.2: "Recall moves a publication from `DRAFT` or `PUBLISHED` to
        `RECALLED` with a version increment; when the recalled publication was
        `PUBLISHED`, the same dependent-quote staleness flag is applied to quotes
        pinned to it in `QUOTED` or `AGENT_QUOTED`."

        Design: Corner/state_machines/feed_publish_from_recall_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        rater = create_rater()
        feed = create_feed_publication(rater["id"], product["id"])
        validate_success(api.recall_feed_publication(feed["id"], RM))

        resp = api.publish_feed_publication(feed["id"], RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_feed_publication(feed["id"], RM))
        assert after["status"] == "RECALLED"


class TestFeedCreateOCC:
    def test_occ_rate_feed_create_stale_rater_version_rejected(self, api):
        """PRD §2.7: "Creating a rate feed publication against a comparative rater
        requires `expected_rater_version`, equal to the rater's current
        `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_rate_feed_create_stale_rater_version_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        rater = create_rater()
        observed_version = rater["version"]

        feed_f1 = create_feed_publication(
            rater["id"], product["id"], expected_rater_version=observed_version,
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-07-01T00:00:00Z",
        )
        assert feed_f1["status"] == "DRAFT"

        # Stale: the rater version advanced on the first create
        resp = api.create_feed_publication(
            rater["id"],
            {
                "product_id": product["id"],
                "effective_start": "2026-08-01T00:00:00Z",
                "effective_end": "2027-01-01T00:00:00Z",
                "rate_table_payload": {"t": "f2"},
                "expected_rater_version": observed_version,
            },
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        # Refreshed version succeeds — the check is version-based
        rater_now = get_success_data(api.get_rater(rater["id"], RM))
        feed_f2 = create_feed_publication(
            rater["id"], product["id"], expected_rater_version=rater_now["version"],
            effective_start="2026-08-01T00:00:00Z",
            effective_end="2027-01-01T00:00:00Z",
        )
        assert feed_f2["status"] == "DRAFT"
        rater_final = get_success_data(api.get_rater(rater["id"], RM))
        assert rater_final["version"] == observed_version + 2


class TestRaterUniqueness:
    def test_duplicate_rater_code_rejected(self, api):
        """PRD §3.2: "Comparative raters are registered by a `RatingManager` with
        a `rater_code` (unique; a re-registration is refused with
        `ERR_DUPLICATE_RATER_CODE`), a `display_name`, the `feed_format_version`
        the rater consumes, and the `accepted_line_of_business` (`AUTO` or
        `HOME`)."

        Design: Corner/errors/duplicate_rater_code_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        create_rater(rater_code="PL-RATER")
        resp = api.create_rater(
            {
                "rater_code": "PL-RATER",
                "display_name": "Duplicate Rater",
                "feed_format_version": "v5.0",
                "accepted_line_of_business": "HOME",
            },
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RATER_CODE, 409)
        rows, meta = validate_paginated(api.list_raters(ADMIN))
        assert len(rows) == 1


class TestTemporalBeatsReferential:
    def test_business_temporal_beats_business_referential_on_feed_create(self, api):
        """PRD §2.8: "When a request would fail several checks, the checks are
        evaluated in a fixed priority order and the error of the **lowest**
        priority number is returned."
        PRD §2.8: "8. Temporal interval rules: appointment overlap
        (`ERR_APPOINTMENT_WINDOW_OVERLAP`), feed strict overlap
        (`ERR_FEED_WINDOW_OVERLAP`) and then the feed gap rule
        (`ERR_FEED_WINDOW_GAP_VIOLATION`), statement period overlap
        (`ERR_STATEMENT_PERIOD_OVERLAP`)."
        PRD §2.8: "9. Cross-entity referential rules: channel availability
        (`ERR_CHANNEL_NOT_AVAILABLE`), publishability at feed-creation time
        (`ERR_PRODUCT_NOT_PUBLISHABLE`), bundle eligibility
        (`ERR_BUNDLE_NOT_ELIGIBLE`), agent mismatch (`ERR_AGENT_MISMATCH`),
        duplicate rater code (`ERR_DUPLICATE_RATER_CODE`), duplicate consumer
        email (`ERR_DUPLICATE_CONSUMER_EMAIL`), agency-of-record transfer target
        (`ERR_AOR_NOT_ALLOWED`), second telematics enrollment
        (`ERR_TELEMATICS_ALREADY_ENROLLED`)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_referential_on_feed_create
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            min_premium_cents=0,
        )
        rater = create_rater()
        feed_f1 = create_feed_publication(
            rater["id"], product["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-07-01T00:00:00Z",
        )
        validate_success(api.withdraw_product(product["id"], RM))
        rater_version = get_success_data(api.get_rater(rater["id"], RM))["version"]

        resp = api.create_feed_publication(
            rater["id"],
            {
                "product_id": product["id"],
                "effective_start": "2026-03-01T00:00:00Z",
                "effective_end": "2026-09-01T00:00:00Z",
                "rate_table_payload": {"t": "f2"},
                "expected_rater_version": rater_version,
            },
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_FEED_WINDOW_OVERLAP, 409)

    def test_feed_create_overlapping_window_on_withdrawn_product_never_reports_publishability(self, api):
        """PRD §3.2: "The product referenced must already be `ACTIVE` at creation
        time, failing with `ERR_PRODUCT_NOT_PUBLISHABLE` when it is still `DRAFT`
        or already `WITHDRAWN`."
        PRD §2.8: "8. Temporal interval rules: appointment overlap
        (`ERR_APPOINTMENT_WINDOW_OVERLAP`), feed strict overlap
        (`ERR_FEED_WINDOW_OVERLAP`) and then the feed gap rule
        (`ERR_FEED_WINDOW_GAP_VIOLATION`), statement period overlap
        (`ERR_STATEMENT_PERIOD_OVERLAP`)."
        PRD §2.8: "9. Cross-entity referential rules: channel availability
        (`ERR_CHANNEL_NOT_AVAILABLE`), publishability at feed-creation time
        (`ERR_PRODUCT_NOT_PUBLISHABLE`), bundle eligibility
        (`ERR_BUNDLE_NOT_ELIGIBLE`), agent mismatch (`ERR_AGENT_MISMATCH`),
        duplicate rater code (`ERR_DUPLICATE_RATER_CODE`), duplicate consumer
        email (`ERR_DUPLICATE_CONSUMER_EMAIL`), agency-of-record transfer target
        (`ERR_AOR_NOT_ALLOWED`), second telematics enrollment
        (`ERR_TELEMATICS_ALREADY_ENROLLED`)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_referential_on_feed_create
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            coverage_rates={"LIABILITY": {"BASIC": 50000}},
            min_premium_cents=0,
        )
        rater = create_rater()
        create_feed_publication(
            rater["id"], product["id"],
            effective_start="2026-01-01T00:00:00Z",
            effective_end="2026-07-01T00:00:00Z",
        )
        validate_success(api.withdraw_product(product["id"], RM))
        rater_version = get_success_data(api.get_rater(rater["id"], RM))["version"]

        # Overlapping window on a WITHDRAWN product: both rules fail; the
        # temporal error wins and the referential error must not surface.
        resp = api.create_feed_publication(
            rater["id"],
            {
                "product_id": product["id"],
                "effective_start": "2026-02-01T00:00:00Z",
                "effective_end": "2026-03-01T00:00:00Z",
                "rate_table_payload": {"t": "overlap-withdrawn"},
                "expected_rater_version": rater_version,
            },
            RM,
        )
        assert resp.status_code == 409
        body = resp.json()["data"]
        assert body["error_id"] == "ERR_FEED_WINDOW_OVERLAP"
        assert body["error_id"] != "ERR_PRODUCT_NOT_PUBLISHABLE"
