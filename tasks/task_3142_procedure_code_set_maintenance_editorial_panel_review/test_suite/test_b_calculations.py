"""Corner coverage indexed under the calculation surface."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    STAFF, LICENSING,
    api_client, set_clock, create_meeting, create_cycle,
    setup_submitted_change_in_cycle,
    setup_gpci_code_value, create_errata_notice,
)


def _activate_released_value(value):
    """Drive a code value to ACTIVE through the PRD SS3.6 release.

    PRD SS3.8 authorises publication only against a code value in value_status
    ACTIVE, and PRD SS3.6 makes the cycle release the operation that sets every
    CodeValue bound to the cycle to ACTIVE. A release needs only one CodeValue
    bound to the cycle, the logical clock at or after the cycle's comment close,
    and no descriptor hole in the published range; the value's effective date is
    January 1 of the cycle's year, exactly as it was when created directly.
    """
    set_clock("2026-09-01T00:00:00Z")
    meeting = create_meeting("APR2026", "APRIL",
                             "2026-04-13T14:00:00Z", "2026-04-13T23:00:00Z")
    cycle = create_cycle([meeting["id"]], year=2027, capacity=300)
    created = validate_success(api_client.create_code_value(
        {
            "code": value["code"],
            "work_rvu": value["work_rvu"],
            "facility_pe_rvu": value["facility_pe_rvu"],
            "nonfacility_pe_rvu": value["nonfacility_pe_rvu"],
            "mp_rvu": value["mp_rvu"],
            "conversion_factor": value["conversion_factor"],
            "rounding_variant": value["rounding_variant"],
            "release_id": cycle["id"],
        },
        LICENSING,
    ), 201)
    set_clock("2026-10-01T00:00:00Z")
    api_client.release_release_cycle(cycle["id"], STAFF)
    return validate_success(api_client.get_code_value(created["id"], LICENSING))


class TestCommentWindowBoundary:
    @pytest.fixture
    def submitted_change(self):
        """A sponsored change enrolled in an open cycle, still in DRAFT."""
        return setup_submitted_change_in_cycle(
            change_code="00069", society_name="Window Society", society_code="WIN",
            meeting_code="JUN2026", meeting_month="JUNE", year=2028, capacity=400,
            meeting_starts="2026-06-08T14:00:00Z", meeting_ends="2026-06-08T23:00:00Z",
            sponsored=True,
        )

    def test_window_one_day_short_of_thirty_is_rejected(self, api, submitted_change):
        """PRD §2.8: "A comment window is measured as the whole-day difference between
        its close instant and its open instant, and it is acceptable only when that
        difference is at least 30 whole days. Windows falling short, including a window
        that misses the floor by a single day, are rejected with
        ERR_COMMENT_PERIOD_TOO_SHORT at 422."

        Design: Corner/calculations/comment_period_one_day_short_is_rejected
        """
        change = submitted_change["change"]
        response = api.post_code_change(
            change["id"],
            {"comment_period_open_at": "2026-09-01T00:00:00Z",
             "comment_period_close_at": "2026-09-30T00:00:00Z"},
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_COMMENT_PERIOD_TOO_SHORT, expected_status=422)

    def test_rejected_posting_leaves_the_change_in_draft(self, api, submitted_change):
        """PRD §3.2: "A successful posting moves review_status from DRAFT to
        POSTED_FOR_COMMENT".

        Design: Corner/calculations/comment_period_one_day_short_is_rejected
        """
        change = submitted_change["change"]
        api.post_code_change(
            change["id"],
            {"comment_period_open_at": "2026-09-01T00:00:00Z",
             "comment_period_close_at": "2026-09-30T00:00:00Z"},
            STAFF,
        )
        row = validate_success(api.get_code_change(change["id"], STAFF))
        assert row["review_status"] == "DRAFT"


class TestCommentWindowAcceptedSide:
    @pytest.fixture
    def submitted_change(self):
        return setup_submitted_change_in_cycle(
            change_code="00070", society_name="Accepted Society", society_code="ACC",
            meeting_code="AUG2026", meeting_month="AUGUST", year=2029, capacity=400,
            meeting_starts="2026-08-10T14:00:00Z", meeting_ends="2026-08-10T23:00:00Z",
            sponsored=True,
        )

    def test_window_of_exactly_thirty_days_posts_the_change(self, api, submitted_change):
        """PRD §2.8: "A comment window is measured as the whole-day difference between
        its close instant and its open instant, and it is acceptable only when that
        difference is at least 30 whole days."
        PRD §2.8: "Conversely, a full public posting period is not exempt: the full
        30-day window applies and the floor is enforced."
        PRD §3.2: "A successful posting moves review_status from DRAFT to
        POSTED_FOR_COMMENT, sets administrative_review_status to ADMIN_COMPLETE, sets
        posting_state to POSTED, and stamps the two window instants supplied in the
        request. The posting follow-on then sets posting_state onward to COMMENT_OPEN".

        Design: Corner/calculations/comment_period_exactly_thirty_days_is_accepted
        """
        change = submitted_change["change"]
        posted = validate_success(api.post_code_change(
            change["id"],
            {"comment_period_open_at": "2026-09-01T00:00:00Z",
             "comment_period_close_at": "2026-10-01T00:00:00Z"},
            STAFF,
        ))
        assert posted["review_status"] == "POSTED_FOR_COMMENT"
        assert posted["posting_state"] == "COMMENT_OPEN"
        assert posted["administrative_review_status"] == "ADMIN_COMPLETE"

    def test_posted_change_records_the_supplied_window_instants(self, api, submitted_change):
        """PRD §3.2: "stamps the two window instants supplied in the request."

        Design: Corner/calculations/comment_period_exactly_thirty_days_is_accepted
        """
        change = submitted_change["change"]
        posted = validate_success(api.post_code_change(
            change["id"],
            {"comment_period_open_at": "2026-09-01T00:00:00Z",
             "comment_period_close_at": "2026-10-01T00:00:00Z"},
            STAFF,
        ))
        assert posted["comment_period_open_at"] is not None
        assert posted["comment_period_close_at"] is not None


class TestErrataPublicationOverwritesPayment:
    def test_publishing_an_errata_overwrites_the_code_value_payment(self, api):
        """PRD §3.8: "A successful publication recomputes the corrected facility
        payment into corrected_facility_payment_cents, recomputes the numerator day
        count into proration_numerator_days and the denominator day count into
        proration_denominator_days, overwrites the named code value's
        facility_payment_cents with the corrected figure, stamps published_at and moves
        status to PUBLISHED."

        Design: Corner/calculations/errata_publication_overwrites_code_value_payment
        """
        bundle = setup_gpci_code_value(code="00080", society_code="ERR")
        # PRD SS3.8 publication requires the named code value to be ACTIVE, and
        # PRD SS3.6 makes a release the operation that sets every CodeValue bound
        # to the cycle to ACTIVE; the value's own effective date is unchanged.
        active_value = _activate_released_value(bundle["value"])
        # PRD SS3.8: publication also requires the logical clock to have reached
        # the notice's own erratum effective date.
        set_clock("2027-05-03T00:00:00Z")
        notice = create_errata_notice(active_value["id"],
                                      errata_effective_date="2027-05-03T00:00:00Z",
                                      prior_cents=18173)
        published = validate_success(api.publish_errata_notice(notice["id"], STAFF))
        assert published["status"] == "PUBLISHED"
        code_value = validate_success(api.get_code_value(active_value["id"], LICENSING))
        assert code_value["facility_payment_cents"] == 12099
        assert code_value["work_rvu"] == 2.80
        assert code_value["conversion_factor"] == 34.63