"""Partial updates, an on-time filing and the four-part filing key."""

from __future__ import annotations

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_DUPLICATE_STUDBOOK_SUBMISSION
from test_helpers.assertions import assert_money
from test_helpers.test_users import make_admin_headers, make_registrar_headers


class TestPartialInstitutionUpdate:
    """Only the fields actually supplied change."""

    def test_patching_the_standing_alone_leaves_every_other_field_alone(
            self, api):
        """A suspension moves the status and the version and nothing else.

        PRD: "every one of those four is optional in the request and only the
        fields actually supplied change."

        Design: Corner/endpoints/patch_institution_updates_only_the_supplied_fields
        """
        world = fx.register_institutions(api)
        data = validate_success(
            api.patch_institution(world.sender_id,
                                  {"accreditation_status": "SUSPENDED"},
                                  make_admin_headers())
        )
        assert data["accreditation_status"] == "SUSPENDED"
        assert str(data["accreditation_expires_on"])[:10] == "2028-12-31"
        assert data["holding_capacity_slots"] == 40
        assert data["disposition_policy_on_file"] is True
        assert data["version"] == 2

        _, meta = validate_paginated(
            api.list_institutions(world.admin,
                                  {"accreditation_status": "SUSPENDED"})
        )
        assert meta["total_count"] == 1


class TestOnTimeStudbookFiling:
    """A filing inside the grace window scores nothing on all four figures."""

    def test_an_on_time_filing_scores_zero_and_its_review_posts_nothing(
            self, api):
        """Filed on 2026-08-01 against a 2026-08-14 deadline, so days_late is 0.

        PRD: "The filing deadline is the thirtieth day after
        `reporting_period_end`, a one-month grace period."

        Design: Corner/endpoints/on_time_studbook_submission_scores_zero_and_review_posts_nothing
        """
        world = fx.base_world(api, publish=False)
        submission = validate_success(
            api.create_studbook_submission(
                f.studbook_submission_payload(world.program_id, world.sender_id,
                                              reporting_period_end="2026-07-15"),
                make_registrar_headers(world.sender_id),
            ),
            201,
        )
        assert str(submission["submitted_on"])[:10] == "2026-08-01"
        assert submission["status"] == "SUBMITTED"
        assert submission["days_late"] == 0
        assert_money(submission["base_points"], 0.00, "base_points")
        assert_money(submission["surcharge_multiplier"], 0.00,
                     "surcharge_multiplier")
        assert_money(submission["surcharge_points"], 0.00, "surcharge_points")
        assert_money(submission["total_compliance_points"], 0.00,
                     "total_compliance_points")

        reviewed = validate_success(
            api.review_studbook_submission(submission["id"],
                                           f.studbook_review_payload(),
                                           world.coordinator)
        )
        assert reviewed["status"] == "ACCEPTED"
        assert reviewed["review_note"] == "clean"
        institution = world.read_institution(world.sender_id)
        assert_money(institution["compliance_points_balance"], 0.00, "balance")
        assert institution["accreditation_status"] == "ACCREDITED"


class TestFilingUniquenessKey:
    """Uniqueness is over programme, institution, period end and type together."""

    def test_a_second_filing_of_the_same_type_and_period_is_refused(self, api):
        """The repeat BIRTH filing is refused while a TRANSFER filing is accepted.

        PRD: "if a submission already exists for the same combination of
        programme, institution, `reporting_period_end` and `submission_type` and
        that existing submission is `SUBMITTED` or `ACCEPTED`, the new filing is
        refused with `ERR_DUPLICATE_STUDBOOK_SUBMISSION` (HTTP 422)."

        Design: Corner/endpoints/duplicate_studbook_submission_is_refused_while_the_first_is_unreviewed
        """
        world = fx.base_world(api, publish=False)
        headers = make_registrar_headers(world.sender_id)
        first = validate_success(
            api.create_studbook_submission(
                f.studbook_submission_payload(world.program_id, world.sender_id,
                                              reporting_period_end="2026-07-15"),
                headers,
            ),
            201,
        )
        validate_error(
            api.create_studbook_submission(
                f.studbook_submission_payload(world.program_id, world.sender_id,
                                              reporting_period_end="2026-07-15"),
                headers,
            ),
            ERR_DUPLICATE_STUDBOOK_SUBMISSION,
        )
        second = validate_success(
            api.create_studbook_submission(
                f.studbook_submission_payload(world.program_id, world.sender_id,
                                              submission_type="TRANSFER",
                                              reporting_period_end="2026-07-15"),
                headers,
            ),
            201,
        )
        assert second["submission_type"] == "TRANSFER"
        _, meta = validate_paginated(
            api.list_studbook_submissions(world.admin,
                                          {"institution_id": world.sender_id})
        )
        assert meta["total_count"] == 2
        assert world.read_submission(first["id"])["status"] == "SUBMITTED"
