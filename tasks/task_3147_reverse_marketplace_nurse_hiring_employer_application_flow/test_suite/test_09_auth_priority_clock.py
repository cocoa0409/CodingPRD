"""Validation priority pairs, auth/RBAC, clock semantics, SLA report, and
immediate-consistency reads."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.factories import create_offer_payload, create_requisition_payload
from test_helpers.test_users import ADMIN, make_candidate_headers, make_employer_headers


class TestClock:
    def test_clock_default_set_is_a_noop(self, api):
        """PRD §2.4: "Before any administrative call sets it, the clock reads exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time. A `PlatformAdmin`-only capability advances the clock by supplying a `current_utc` instant; the response echoes `current_utc` and reports `fired_transitions`, the count of system transitions the advance triggered."

        Design: Corner/endpoints/clock_default_is_2026_09_01_before_any_set
        """
        data = validate_success(
            api_client.set_clock("2026-09-01T00:00:00Z", ADMIN)
        )
        assert data["current_utc"] == "2026-09-01T00:00:00Z"
        assert data["fired_transitions"] == 0


class TestAuthentication:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, carrying a role outside this enumeration, or — for an entity-backed role — omitting `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_missing_role_header
        """
        fx.set_clock()
        resp = api_client.get_nurse(
            NON_EXISTENT_UUID, headers={"X-User-ID": "someone"}
        )
        assert resp.status_code == 401
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestAuthorization:
    def test_candidate_cannot_create_requisition(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint, or whose `X-User-ID` does not match the owning entity on an ownership-scoped endpoint, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: requisition creation is authorized for the Employer role only.

        Design: Corner/validations/role_not_permitted_for_endpoint
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")
        resp = api_client.create_requisition(
            create_requisition_payload(NON_EXISTENT_UUID),
            make_candidate_headers(nurse["id"]),
        )
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_candidate_cannot_act_on_another_nurses_application(self, api):
        """PRD §2.1: "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Nurse`; ownership checks on any resource that references a nurse compare the resource's `nurse_id` foreign key to `X-User-ID`."
        PRD §2.1: "A request whose role is not permitted for the endpoint, or whose `X-User-ID` does not match the owning entity on an ownership-scoped endpoint, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/candidate_cannot_act_on_another_nurses_application
        """
        ctx = fx.setup_marketplace()
        nurse_a, employer, req = ctx["nurse"], ctx["employer"], ctx["requisition"]
        nurse_b = fx.setup_active_nurse(email="bother@x.com", years_experience=4)["nurse"]
        app = fx.create_application(req, nurse_a, employer)

        resp = api_client.review_application(app["id"], make_candidate_headers(nurse_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(
            api_client.get_application(app["id"], make_candidate_headers(nurse_a["id"]))
        )
        assert after["status"] == "SUBMITTED"

    def test_platform_admin_cannot_perform_employer_exclusive_operations(self, api):
        """PRD §4: requisition pause is authorized for the Employer role only.
        PRD §2.1: "A request whose role is not permitted for the endpoint, or whose `X-User-ID` does not match the owning entity on an ownership-scoped endpoint, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/platform_admin_cannot_perform_employer_exclusive_operations
        """
        fx.set_clock()
        employer = fx.create_employer()
        req = fx.create_requisition(employer)

        resp = api_client.pause_requisition(req["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(
            api_client.get_requisition(req["id"], make_employer_headers(employer["id"]))
        )
        assert after["status"] == "OPEN"

    def test_employer_cannot_verify_licenses(self, api):
        """PRD §4: license verification is authorized for the PlatformAdmin role only.
        PRD §2.1: "A request whose role is not permitted for the endpoint, or whose `X-User-ID` does not match the owning entity on an ownership-scoped endpoint, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/employer_cannot_verify_licenses_or_screenings
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")
        lic = fx.add_license(nurse)
        fx.submit_nurse(nurse)
        employer = fx.create_employer()

        resp = api_client.verify_license(lic["id"], make_employer_headers(employer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(
            api_client.get_license_verification(lic["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "PENDING"

    def test_candidate_read_scope_excludes_screenings(self, api):
        """PRD §4: reading a screening is authorized for the Employer and PlatformAdmin roles only; reading an application is authorized for Candidate, Employer, and PlatformAdmin.
        PRD §2.1: "A request whose role is not permitted for the endpoint, or whose `X-User-ID` does not match the owning entity on an ownership-scoped endpoint, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/candidate_shared_read_scope_excludes_screenings
        """
        ctx = fx.setup_application_under_review()
        nurse = ctx["nurse"]
        scr = fx.open_screening(ctx["application"], ctx["employer"])

        resp = api_client.get_screening(scr["id"], make_candidate_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        own_app = validate_success(
            api_client.get_application(ctx["application"]["id"], make_candidate_headers(nurse["id"]))
        )
        assert own_app["id"] == ctx["application"]["id"]


class TestPriorityPairs:
    def test_state_beats_fiscal_on_closed_requisition_accept(self, api):
        """PRD §2.6: "Existence checks (priority 3) always run after authentication (priority 1) and authorization (priority 2), and before state-machine legality (priority 4) and every business rule (priorities 5 through 11). Within business rules, deadline checks (priority 5) precede confidentiality (priority 6), which precede credential gates (priority 7), which precede matching-field constraints (priority 8), which precede scheduling conflicts (priority 9) and unit day-capacity (priority 9.5), which precede quota checks (priority 10), which precede duplicate guards (priority 11). A request that fails several checks surfaces the error from the earliest-priority check that fails."
        PRD §3.6: "The nurse may decline an `ISSUED` offer, which moves the offer to `DECLINED` and the application from `OFFER_EXTENDED` to `DECLINED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_closed_requisition_accept
        """
        ctx = fx.setup_offer_issued()
        nurse, offer = ctx["nurse"], ctx["offer"]

        declined = validate_success(
            api_client.decline_offer(offer["id"], make_candidate_headers(nurse["id"]))
        )
        assert declined["status"] == "DECLINED"

        # The terminal-state check (priority 4) fires before any quota/fiscal check.
        resp = api_client.accept_offer(offer["id"], make_candidate_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        _, meta = validate_paginated(
            api_client.list_placements(ADMIN, params={"application_id": ctx["application"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_temporal_beats_referential_on_late_interview(self, api):
        """PRD §2.6: "Within business rules, deadline checks (priority 5) precede confidentiality (priority 6), which precede credential gates (priority 7), which precede matching-field constraints (priority 8), which precede scheduling conflicts (priority 9) and unit day-capacity (priority 9.5), which precede quota checks (priority 10), which precede duplicate guards (priority 11). A request that fails several checks surfaces the error from the earliest-priority check that fails."
        PRD §3.4: "On any clock advance that reaches `response_deadline_at`, an application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` transitions to the terminal `EXPIRED` — the boundary is inclusive, so a clock reading exactly equal to the deadline expires the application — and any of its interviews still `SCHEDULED` cascade to `CANCELLED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_late_interview
        """
        fx.set_clock()
        # License expires 2026-09-03: after the clock passes it, license_verified
        # is false AND the 72h application deadline (2026-09-04) has passed.
        nurse = fx.create_draft_nurse(email="liz@x.com")
        lic = fx.add_license(nurse, license_number="RN-CA-900", expiry_date="2026-09-03")
        fx.submit_nurse(nurse)
        fx.verify_license(lic)
        nurse = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse["status"] == "ACTIVE"

        employer = fx.create_employer()
        req = fx.create_requisition(employer)
        app = fx.create_application(req, nurse, employer)
        fx.review_application(app, nurse)

        fx.set_clock("2026-09-05T00:00:00Z")

        app_after = validate_success(
            api_client.get_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert app_after["status"] == "EXPIRED"

        resp = api_client.schedule_interview(
            app["id"],
            {"starts_at": "2026-09-06T10:00:00Z", "ends_at": "2026-09-06T11:00:00Z"},
            make_employer_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


    def test_accept_on_declined_offer_rejected_regardless_of_openings(self, api):
        """PRD §2.6: "A request that fails several checks surfaces the error from the earliest-priority check that fails."
        PRD §2.6: "Existence checks (priority 3) always run after authentication (priority 1) and authorization (priority 2), and before state-machine legality (priority 4) and every business rule (priorities 5 through 11)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_closed_requisition_accept
        """
        ctx = fx.setup_offer_issued()
        nurse, offer = ctx["nurse"], ctx["offer"]

        validate_success(
            api_client.decline_offer(offer["id"], make_candidate_headers(nurse["id"]))
        )
        # Two offers of failure are present in principle — the offer is terminal
        # (priority 4) — and the state error is the one surfaced.
        resp = api_client.accept_offer(offer["id"], make_candidate_headers(nurse["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        offer_after = validate_success(
            api_client.get_offer(offer["id"], make_employer_headers(ctx["employer"]["id"]))
        )
        assert offer_after["status"] == "DECLINED"


class TestPriorityPairsTemporal:
    def test_late_review_rejected_after_deadline_expiry(self, api):
        """PRD §2.6: "Within business rules, deadline checks (priority 5) precede confidentiality (priority 6), which precede credential gates (priority 7), which precede matching-field constraints (priority 8), which precede scheduling conflicts (priority 9) and unit day-capacity (priority 9.5), which precede quota checks (priority 10), which precede duplicate guards (priority 11). A request that fails several checks surfaces the error from the earliest-priority check that fails."
        PRD §3.4: "On any clock advance that reaches `response_deadline_at`, an application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` transitions to the terminal `EXPIRED` — the boundary is inclusive, so a clock reading exactly equal to the deadline expires the application — and any of its interviews still `SCHEDULED` cascade to `CANCELLED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_late_interview
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="liz@x.com")
        lic = fx.add_license(nurse, license_number="RN-CA-901", expiry_date="2026-09-03")
        fx.submit_nurse(nurse)
        fx.verify_license(lic)
        nurse = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse["status"] == "ACTIVE"

        employer = fx.create_employer()
        req = fx.create_requisition(employer)
        app = fx.create_application(req, nurse, employer)

        # Past both the license expiry (2026-09-03) and the 72h deadline
        # (2026-09-04): the deadline transition fires on the clock advance.
        fx.set_clock("2026-09-05T00:00:00Z")
        app_after = validate_success(
            api_client.get_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert app_after["status"] == "EXPIRED"

        late = api_client.review_application(app["id"], make_candidate_headers(nurse["id"]))
        validate_error(late, ApiErrorId.ERR_INVALID_STATE)


class TestSlaReport:
    def test_sla_report_counts_breach_at_strict_greater_than_threshold(self, api):
        """PRD §3.8: "For each, the employer's first-action time is the whole hours — truncated toward zero — from application creation to the earliest of: the first interview's scheduling timestamp, the first counter, the offer's `issued_at`, or an employer withdrawal. An application breaches when that first-action time is strictly greater than the employer's `sla_response_hours`; exactly equal is not a breach. The report returns `breach_count`, the number of breaching applications, `evaluated_count`, the number evaluated, and `rapid_offer_target_met`, which is true when the accepted application's time-to-offer — whole hours from application creation to the offer's `issued_at` — is at most 120 hours."
        PRD §3.6: "the `offered_hourly_rate_cents` must equal the application's current `proposed_hourly_rate_cents` — including any counter revisions — and the `start_date` must fall between 14 and 90 days after the clock's current date at issuance, with violations rejected as `ERR_TERMS_MISMATCH`"

        Design: Corner/calculations/sla_report_counts_breach_at_strict_greater_than_threshold
        """
        ctx = fx.setup_application_under_review()
        app, nurse, employer, req = (
            ctx["application"], ctx["nurse"], ctx["employer"], ctx["requisition"],
        )

        # First employer action lands 50h after creation: a counter to 9000.
        fx.set_clock("2026-09-03T02:00:00Z")
        countered = validate_success(
            api_client.counter_application(
                app["id"], {"proposed_hourly_rate_cents": 9000},
                make_employer_headers(employer["id"]),
            )
        )
        assert countered["revision_count"] == 1

        iv = fx.schedule_interview(
            app, employer,
            starts_at="2026-09-03T10:00:00Z", ends_at="2026-09-03T11:00:00Z",
        )
        fx.set_clock("2026-09-03T12:00:00Z")
        fx.complete_interview(iv, employer)
        scr = fx.open_screening(app, employer)
        fx.verify_screening_credentials(scr)
        fx.clear_screening_background(scr)
        doc = fx.upload_document(app, nurse, doc_type="SIGNED_CONTRACT")
        fx.approve_document(doc, employer)

        # Offer at the pre-counter rate no longer matches the current terms.
        mismatch = api_client.issue_offer(
            app["id"],
            create_offer_payload(
                fx.fresh_requisition_version(req["id"], employer),
                offered_hourly_rate_cents=8500, start_date="2026-09-20",
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(mismatch, ApiErrorId.ERR_TERMS_MISMATCH)

        report = validate_success(
            api_client.get_sla_report(req["id"], make_employer_headers(employer["id"]))
        )
        assert report["evaluated_count"] == 1
        assert report["breach_count"] == 1  # 50h > 48h sla (strict >)
        assert report["rapid_offer_target_met"] is False


class TestImmediateConsistency:
    def test_accept_cascade_visible_in_same_and_next_requests(self, api):
        """PRD §3.7: "Offer acceptance is an atomic multi-entity commit, and it is where the marketplace's financial machinery engages."
        PRD §3.7: "Fifth, an **Invoice** is created in `ISSUED` with `amount_credited_cents` at zero, its `invoice_kind` set to `PLACEMENT_FEE`, its `employer_id` and `placement_id` wired to the new placement."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_request
        """
        ctx = fx.setup_offer_issued()
        nurse, employer, req = ctx["nurse"], ctx["employer"], ctx["requisition"]

        placement = validate_success(
            api_client.accept_offer(ctx["offer"]["id"], make_candidate_headers(nurse["id"]))
        )
        # The accept response IS the created Placement.
        assert placement["status"] == "PENDING_START"
        assert placement["application_id"] == ctx["application"]["id"]

        req_after = validate_success(
            api_client.get_requisition(req["id"], make_employer_headers(employer["id"]))
        )
        assert req_after["openings_filled"] == 1
        assert req_after["status"] == "OPEN"  # openings_total 2 > 1 filled

        nurse_after = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse_after["status"] == "HIRED"

        rows, meta = validate_paginated(
            api_client.list_employer_invoices(employer["id"], make_employer_headers(employer["id"]))
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "ISSUED"
        assert rows[0]["invoice_kind"] == "PLACEMENT_FEE"
        assert rows[0]["placement_id"] == placement["id"]
        assert rows[0]["amount_credited_cents"] == 0
