"""Offers, screening parallel axes, onboarding documents, and offer-side gates."""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.factories import create_offer_payload
from test_helpers.test_users import ADMIN, make_candidate_headers, make_employer_headers


class TestOfferIssueGate:
    def test_offer_issue_gated_by_completed_interview(self, api):
        """PRD §3.6: "With an application in `INTERVIEWING` and at least one of its interviews `COMPLETED`, the employer issues an **Offer**, supplying `offered_hourly_rate_cents`, a `start_date`, and — per §2.7 — `expected_requisition_version`."
        PRD §3.1: "Any transition attempted from a state where it does not exist is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/offer_issue_gated_by_completed_interview
        """
        ctx = fx.setup_application_interviewing()
        app, req, employer, iv = (
            ctx["application"], ctx["requisition"], ctx["employer"], ctx["interview"],
        )
        # The interview window is still running — it cannot be completed yet.
        fx.set_clock("2026-09-02T10:30:00Z")

        resp = api_client.issue_offer(
            app["id"],
            create_offer_payload(fx.fresh_requisition_version(req["id"], employer)),
            make_employer_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        iv_after = validate_success(
            api_client.get_interview(iv["id"], make_employer_headers(employer["id"]))
        )
        assert iv_after["status"] == "SCHEDULED"
        app_after = validate_success(
            api_client.get_application(app["id"], make_employer_headers(employer["id"]))
        )
        assert app_after["status"] == "INTERVIEWING"

    def test_offer_issue_succeeds_once_interview_completed(self, api):
        """PRD §3.6: "With an application in `INTERVIEWING` and at least one of its interviews `COMPLETED`, the employer issues an **Offer**, supplying `offered_hourly_rate_cents`, a `start_date`, and — per §2.7 — `expected_requisition_version`."

        Design: Difficulty/cross_entity_state_dependency/offer_issue_gated_by_completed_interview
        """
        ctx = fx.setup_application_with_completed_interview()
        app, req, employer = ctx["application"], ctx["requisition"], ctx["employer"]

        offer = validate_success(
            api_client.issue_offer(
                app["id"],
                create_offer_payload(fx.fresh_requisition_version(req["id"], employer)),
                make_employer_headers(employer["id"]),
            ),
            expected_status=201,
        )
        assert offer["status"] == "ISSUED"


class TestOfferOcc:
    def test_offer_issue_occ_stale_requisition_version_rejected(self, api):
        """PRD §2.7: "Issuing an offer on an application requires `expected_requisition_version`, likewise non-optional, holding the `version` of the parent `Requisition` as last observed; a mismatch with the requisition's current `version` is rejected with `ERR_STALE_REQUISITION_VERSION` (HTTP 412)."

        Design: Corner/endpoints/offer_issue_occ_stale_requisition_version_rejected
        """
        ctx = fx.setup_application_with_completed_interview()
        app, req, employer = ctx["application"], ctx["requisition"], ctx["employer"]
        observed = req["version"]

        # Any requisition mutation advances its version; pause then resume bumps it twice.
        fx._data(api_client.pause_requisition(req["id"], make_employer_headers(employer["id"])),
                 "pause requisition")
        fx._data(api_client.resume_requisition(req["id"], make_employer_headers(employer["id"])),
                 "resume requisition")

        stale = api_client.issue_offer(
            app["id"], create_offer_payload(observed),
            make_employer_headers(employer["id"]),
        )
        assert stale.status_code == 412
        validate_error(stale, ApiErrorId.ERR_STALE_REQUISITION_VERSION, 412)

        fresh = api_client.issue_offer(
            app["id"],
            create_offer_payload(fx.fresh_requisition_version(req["id"], employer)),
            make_employer_headers(employer["id"]),
        )
        offer = validate_success(fresh, expected_status=201)
        assert offer["status"] == "ISSUED"


class TestScreeningAxes:
    def test_parallel_axes_compound_overall(self, api):
        """PRD §3.6: "A screening tracks two independent axes in parallel: `credential_status` moving among `PENDING`, `VERIFIED`, and `FAILED`, and `background_status` moving among `PENDING`, `CLEARED`, and `FLAGGED`. Both axes start at `PENDING`, making the derived `overall_status` begin as `IN_PROGRESS`. The derived value is a compound: `COMPLETE` when credentials are `VERIFIED` and background is `CLEARED`; `BLOCKED` when either axis is `FAILED` or `FLAGGED`; otherwise `IN_PROGRESS`."

        Design: Difficulty/non_linear_state_machine/screening_parallel_axes_compound_overall
        """
        ctx = fx.setup_application_under_review()
        scr = fx.open_screening(ctx["application"], ctx["employer"])
        assert scr["credential_status"] == "PENDING"
        assert scr["background_status"] == "PENDING"
        assert scr["overall_status"] == "IN_PROGRESS"

        scr = fx.clear_screening_background(scr)
        assert scr["background_status"] == "CLEARED"
        assert scr["credential_status"] == "PENDING"
        assert scr["overall_status"] == "IN_PROGRESS", (
            "one cleared axis alone leaves the compound IN_PROGRESS"
        )

        scr = fx.verify_screening_credentials(scr)
        assert scr["credential_status"] == "VERIFIED"
        assert scr["overall_status"] == "COMPLETE"

    def test_fail_after_clear_yields_blocked(self, api):
        """PRD §3.6: "The derived value is a compound: `COMPLETE` when credentials are `VERIFIED` and background is `CLEARED`; `BLOCKED` when either axis is `FAILED` or `FLAGGED`; otherwise `IN_PROGRESS`."

        Design: Difficulty/non_linear_state_machine/screening_parallel_axes_compound_overall
        """
        ctx = fx.setup_application_under_review()
        scr = fx.open_screening(ctx["application"], ctx["employer"])
        scr = fx.clear_screening_background(scr)
        assert scr["overall_status"] == "IN_PROGRESS"

        scr = validate_success(api_client.fail_credentials(scr["id"], ADMIN))
        assert scr["credential_status"] == "FAILED"
        assert scr["background_status"] == "CLEARED"
        assert scr["overall_status"] == "BLOCKED"


class TestScreeningFailureCascade:
    def test_screening_fail_rescind_cascade_two_hops(self, api):
        """PRD §3.6: "Failing credentials or flagging background flips `overall_status` to `BLOCKED` and, if the application's offer is currently `ISSUED`, cascades: the offer transitions to `RESCINDED` and the application to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/screening_fail_rescind_cascade_two_hops
        """
        # Build to OFFER_EXTENDED with the credential axis still PENDING.
        ctx = fx.setup_application_with_completed_interview()
        app, req, employer, nurse = (
            ctx["application"], ctx["requisition"], ctx["employer"], ctx["nurse"],
        )
        scr = fx.open_screening(app, employer)
        scr = fx.clear_screening_background(scr)
        assert scr["overall_status"] == "IN_PROGRESS"
        offer = fx.issue_offer(app, req, employer)
        assert offer["status"] == "ISSUED"

        scr = validate_success(api_client.fail_credentials(scr["id"], ADMIN))
        assert scr["credential_status"] == "FAILED"
        assert scr["overall_status"] == "BLOCKED"

        offer_after = validate_success(
            api_client.get_offer(offer["id"], make_employer_headers(employer["id"]))
        )
        assert offer_after["status"] == "RESCINDED"

        app_after = validate_success(
            api_client.get_application(app["id"], make_employer_headers(employer["id"]))
        )
        assert app_after["status"] == "WITHDRAWN"

        _, meta = validate_paginated(
            api_client.list_placements(ADMIN, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 0, "no placement may exist for a rescinded offer"

    def test_flag_background_rescinds_issued_offer(self, api):
        """PRD §3.6: "Failing credentials or flagging background flips `overall_status` to `BLOCKED` and, if the application's offer is currently `ISSUED`, cascades: the offer transitions to `RESCINDED` and the application to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/screening_fail_rescind_cascade_two_hops
        """
        ctx = fx.setup_application_with_completed_interview()
        app, req, employer = ctx["application"], ctx["requisition"], ctx["employer"]
        scr = fx.open_screening(app, employer)
        scr = fx.verify_screening_credentials(scr)
        assert scr["overall_status"] == "IN_PROGRESS"
        offer = fx.issue_offer(app, req, employer)

        scr = validate_success(api_client.flag_background(scr["id"], ADMIN))
        assert scr["background_status"] == "FLAGGED"
        assert scr["overall_status"] == "BLOCKED"

        offer_after = validate_success(
            api_client.get_offer(offer["id"], make_employer_headers(employer["id"]))
        )
        assert offer_after["status"] == "RESCINDED"
        app_after = validate_success(
            api_client.get_application(app["id"], make_employer_headers(employer["id"]))
        )
        assert app_after["status"] == "WITHDRAWN"


class TestScreeningDuplicate:
    def test_duplicate_screening_per_application_rejected(self, api):
        """PRD §3.6: "The employer opens a **Screening** — exactly one per application; a second is rejected with `ERR_DUPLICATE_RESOURCE` — by supplying the `application_id`."

        Design: Corner/state_machines/duplicate_screening_per_application_rejected
        """
        ctx = fx.setup_application_under_review()
        app, employer = ctx["application"], ctx["employer"]
        fx.open_screening(app, employer)

        dup = api_client.create_screening(
            {"application_id": app["id"]}, make_employer_headers(employer["id"])
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_RESOURCE)

        _, meta = validate_paginated(
            api_client.list_application_screenings(app["id"], make_employer_headers(employer["id"]))
        )
        assert meta["total_count"] == 1


class TestOfferAcceptanceGate:
    def test_accept_without_approved_contract_rejected(self, api):
        """PRD §3.6: "an onboarding document with `doc_type` `SIGNED_CONTRACT` in `APPROVED` status must exist for the application — a missing screening or missing approved contract is rejected with `ERR_CREDENTIALS_INCOMPLETE`"

        Design: Corner/validations/offer_accept_without_approved_contract_rejected
        """
        # Full pipeline except the SIGNED_CONTRACT stays RECEIVED (not approved).
        ctx = fx.setup_application_with_completed_interview()
        app, req, employer, nurse = (
            ctx["application"], ctx["requisition"], ctx["employer"], ctx["nurse"],
        )
        scr = fx.open_screening(app, employer)
        scr = fx.verify_screening_credentials(scr)
        scr = fx.clear_screening_background(scr)
        assert scr["overall_status"] == "COMPLETE"
        fx.upload_document(app, nurse, doc_type="SIGNED_CONTRACT")  # never approved
        offer = fx.issue_offer(app, req, employer)

        resp = api_client.accept_offer(offer["id"], make_candidate_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDENTIALS_INCOMPLETE)

        offer_after = validate_success(
            api_client.get_offer(offer["id"], make_employer_headers(employer["id"]))
        )
        assert offer_after["status"] == "ISSUED"
        _, meta = validate_paginated(
            api_client.list_placements(ADMIN, params={"application_id": app["id"]})
        )
        assert meta["total_count"] == 0


class TestDocumentReview:
    def test_reject_requires_review_note(self, api):
        """PRD §3.6: "the owning employer then approves it to `APPROVED` or rejects it to `REJECTED` — rejection requires a `review_note` in the body, and a missing one is rejected with `ERR_REVIEW_NOTE_REQUIRED` (HTTP 400)."

        Design: Corner/validations/document_reject_requires_review_note
        """
        ctx = fx.setup_marketplace()
        nurse, employer = ctx["nurse"], ctx["employer"]
        app = fx.create_application(ctx["requisition"], nurse, employer)
        doc = fx.upload_document(app, nurse, doc_type="W4")

        no_note = api_client.reject_document(doc["id"], {}, make_employer_headers(employer["id"]))
        validate_error(no_note, ApiErrorId.ERR_REVIEW_NOTE_REQUIRED, 400)

        rejected = validate_success(
            api_client.reject_document(
                doc["id"], {"review_note": "illegible scan"},
                make_employer_headers(employer["id"]),
            )
        )
        assert rejected["status"] == "REJECTED"
