"""Allocation appeals: eligibility, lifecycle, terminal lockdown (PRD §3.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    current_run_version,
    file_appeal,
    get_success_data,
    setup_dealer_run,
    validate_error,
    validate_success,
)

ALLOC = TEST_USERS["allocator_headers"]


class TestAppealEligibility:
    def test_new_point_appeal_by_old_dealer_rejected(self, api):
        """PRD §3.10: "A `NEW_POINT` appeal requires the dealer's `opened_on` to be within 6 months of the run's `published_at`; outside that window the appeal is rejected with `ERR_APPEAL_INELIGIBLE`."

        Design: Corner/validations/appeal_new_point_outside_grace_rejected
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3, opened_on="2020-01-01T00:00:00Z")
        dealer = fx["dealers"][0]
        resp = file_appeal(dealer, fx["run"]["id"], appeal_type="NEW_POINT", requested_units=2)
        validate_error(resp, ApiErrorId.ERR_APPEAL_INELIGIBLE, 422)

    def test_new_point_appeal_within_grace_accepted(self, api):
        """PRD §3.10: "A `NEW_POINT` appeal requires the dealer's `opened_on` to be within 6 months of the run's `published_at`".
        PRD §3.10: "Filing stamps `filed_at` and starts the appeal in `FILED` status."

        Design: Corner/validations/appeal_new_point_outside_grace_rejected
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3, opened_on="2026-06-01T00:00:00Z")
        dealer = fx["dealers"][0]
        appeal = validate_success(
            file_appeal(dealer, fx["run"]["id"], appeal_type="NEW_POINT", requested_units=2), 201
        )
        assert appeal["state"] == "FILED"
        assert appeal["filed_at"] is not None


class TestAppealTerminalLockdown:
    def test_denied_appeal_cannot_be_granted(self, api):
        """PRD §3.10: "From `UNDER_REVIEW`, the allocator may deny the appeal (transitioning to `DENIED`) or grant it."
        PRD §2.5: "Target resource is in a state from which the requested transition exists — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/terminal_appeal_cannot_be_granted
        """
        fx = setup_dealer_run(num_dealers=1, base_units=3, opened_on="2026-06-01T00:00:00Z")
        dealer = fx["dealers"][0]
        run = fx["run"]
        appeal = get_success_data(
            file_appeal(dealer, run["id"], appeal_type="NEW_POINT", requested_units=1)
        )
        get_success_data(api.review_appeal(appeal["id"], ALLOC))
        denied = validate_success(api.deny_appeal(appeal["id"], ALLOC), 200)
        assert denied["state"] == "DENIED"
        resp = api.grant_appeal(
            appeal["id"],
            {"granted_units": 1, "expected_run_version": current_run_version(run["id"])},
            ALLOC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
