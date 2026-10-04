"""Nurse lifecycle: submit gates, license rejection reversion, deactivation,
reactivation, and license verification expiry checks."""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import ADMIN, make_candidate_headers, make_employer_headers


class TestNurseSubmissionGate:
    def test_draft_to_pending_requires_existing_license(self, api):
        """PRD §3.1: "Once at least one verification exists in `PENDING` or `VERIFIED`, the nurse — still acting as `Candidate` on their own profile — submits the profile, moving it from `DRAFT` to `PENDING_VERIFICATION`."
        PRD §3.1: "Any transition attempted from a state where it does not exist is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/nurse_draft_to_pending_requires_existing_license
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")

        resp = api_client.submit_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "DRAFT"


class TestLicenseRejection:
    def test_reject_reverts_nurse_to_draft_and_requires_reason(self, api):
        """PRD §3.1: "if the nurse's last non-expired verification is rejected by a `PlatformAdmin` (the reject action requires a `rejection_reason` in the body; a missing one is rejected with `ERR_REVIEW_NOTE_REQUIRED`) and no other verification remains `PENDING`, the nurse reverts to `DRAFT`."

        Design: Corner/state_machines/license_reject_reverts_nurse_to_draft_and_requires_reason
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")
        lic = fx.add_license(nurse, license_number="RN-CA-100")
        fx.submit_nurse(nurse)

        no_reason = api_client.reject_license(lic["id"], {}, ADMIN)
        validate_error(no_reason, ApiErrorId.ERR_REVIEW_NOTE_REQUIRED, 400)

        rejected = validate_success(
            api_client.reject_license(
                lic["id"], {"rejection_reason": "license number not found on state board"}, ADMIN
            )
        )
        assert rejected["status"] == "REJECTED"

        nurse_after = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse_after["status"] == "DRAFT"
        assert nurse_after["license_verified"] is False

    def test_verify_with_past_expiry_rejected(self, api):
        """PRD §3.1: "The moment a `PlatformAdmin` verifies a license — which requires the verification still be `PENDING` and its `expiry_date` be strictly after the clock's current date, otherwise the verify action is rejected with `ERR_LICENSE_EXPIRED` (HTTP 422) — the nurse's `license_verified` flag is recomputed."

        Design: Corner/state_machines/license_verify_with_past_expiry_rejected
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")
        lic = fx.add_license(nurse, license_number="RN-CA-901", expiry_date="2026-09-01")

        resp = api_client.verify_license(lic["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LICENSE_EXPIRED, 422)

        after = validate_success(
            api_client.get_license_verification(lic["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "PENDING"


class TestDeactivationGate:
    def test_deactivate_blocked_with_live_applications(self, api):
        """PRD §3.1: "Deactivation moves `ACTIVE` to `INACTIVE` but is permitted only when the nurse's `active_application_count` — the count of their applications in `SUBMITTED` or `UNDER_REVIEW` — is zero in the sense that no application exists in `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED`; attempting deactivation with any such live application is rejected with `ERR_NURSE_HAS_LIVE_APPLICATIONS` (HTTP 409)."

        Design: Corner/state_machines/nurse_deactivate_blocked_with_live_applications
        """
        ctx = fx.setup_application_under_review()
        nurse = ctx["nurse"]
        app = ctx["application"]

        blocked = api_client.deactivate_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        validate_error(blocked, ApiErrorId.ERR_NURSE_HAS_LIVE_APPLICATIONS)

        declined = validate_success(
            api_client.decline_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert declined["status"] == "DECLINED"

        nurse_now = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse_now["active_application_count"] == 0

        deactivated = validate_success(
            api_client.deactivate_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert deactivated["status"] == "INACTIVE"


class TestReactivationGate:
    def test_reactivate_requires_license_still_verified(self, api):
        """PRD §3.1: "Reactivation moves `INACTIVE` back to `ACTIVE` and requires that `license_verified` be true at reactivation time."

        Design: Corner/state_machines/nurse_reactivate_requires_license_still_verified
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")
        lic = fx.add_license(nurse, license_number="RN-CA-900", expiry_date="2026-09-03")
        fx.submit_nurse(nurse)
        fx.verify_license(lic)

        deactivated = validate_success(
            api_client.deactivate_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert deactivated["status"] == "INACTIVE"

        fx.set_clock("2026-09-04T00:00:00Z")

        resp = api_client.reactivate_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDENTIALS_INCOMPLETE)

        after = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "INACTIVE"


class TestWithdrawalCascade:
    def test_nurse_withdraw_cascades_applications_and_rescinds_offers(self, api):
        """PRD §3.1: "withdrawal moves the nurse to the terminal `WITHDRAWN`, requires that the nurse have no placement in `PENDING_START` or `GUARANTEE_ACTIVE`, and cascades — every application of theirs in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` transitions to `WITHDRAWN`, and any application in `OFFER_EXTENDED` sees its attached offer cascade to `RESCINDED`."

        Design: Corner/state_machines/nurse_withdraw_cascades_applications_and_rescinds_offers
        """
        # Application 1: carried all the way to OFFER_EXTENDED with an ISSUED offer.
        ctx = fx.setup_offer_issued()
        nurse, employer1 = ctx["nurse"], ctx["employer"]
        app1, offer1 = ctx["application"], ctx["offer"]

        # Application 2 from a second employer, moved to UNDER_REVIEW.
        employer2 = fx.create_employer(
            legal_name="Coastal General", fee_model="SUBSCRIPTION",
            subscription_tier="PRO", guarantee_days=90, placement_fee_bps=1500,
        )
        req2 = fx.create_requisition(
            employer2, unit_name="ICU-North", distance_from_facility_miles=30,
            offered_hourly_rate_cents=8200, openings_total=1,
        )
        app2 = fx.create_application(req2, nurse, employer2, proposed_hourly_rate_cents=8300)
        app2 = fx.review_application(app2, nurse)
        assert app2["status"] == "UNDER_REVIEW"

        withdrawn = validate_success(
            api_client.withdraw_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"

        app1_after = validate_success(
            api_client.get_application(app1["id"], make_candidate_headers(nurse["id"]))
        )
        assert app1_after["status"] == "WITHDRAWN"
        offer_after = validate_success(
            api_client.get_offer(offer1["id"], make_candidate_headers(nurse["id"]))
        )
        assert offer_after["status"] == "RESCINDED"

        app2_after = validate_success(
            api_client.get_application(app2["id"], make_candidate_headers(nurse["id"]))
        )
        assert app2_after["status"] == "WITHDRAWN"

        late_review = api_client.review_application(
            app1["id"], make_candidate_headers(nurse["id"])
        )
        validate_error(late_review, ApiErrorId.ERR_INVALID_STATE)


class TestApplicationTerminalLockdown:
    def test_terminal_states_lock_all_actions(self, api):
        """PRD §3.4: "The nurse may instead decline from `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING`, moving the application to the terminal `DECLINED`."
        PRD §3.1: "Any transition attempted from a state where it does not exist is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/application_terminal_states_lock_all_actions
        """
        ctx = fx.setup_marketplace()
        nurse, employer, req = ctx["nurse"], ctx["employer"], ctx["requisition"]
        app = fx.create_application(req, nurse, employer)

        declined = validate_success(
            api_client.decline_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert declined["status"] == "DECLINED"

        rev = api_client.review_application(app["id"], make_candidate_headers(nurse["id"]))
        validate_error(rev, ApiErrorId.ERR_INVALID_STATE)

        ctr = api_client.counter_application(
            app["id"], {"proposed_hourly_rate_cents": 9000}, make_employer_headers(employer["id"])
        )
        validate_error(ctr, ApiErrorId.ERR_INVALID_STATE)

        wd = api_client.withdraw_application(app["id"], make_employer_headers(employer["id"]))
        validate_error(wd, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(
            api_client.get_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "DECLINED"
        _, meta = validate_paginated(
            api_client.list_application_interviews(app["id"], make_employer_headers(employer["id"]))
        )
        assert meta["total_count"] == 0
