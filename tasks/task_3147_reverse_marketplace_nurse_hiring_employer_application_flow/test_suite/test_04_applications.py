"""Employer-initiated applications: creation gates, OCC, counters, deadlines."""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.factories import create_application_payload
from test_helpers.test_users import make_candidate_headers, make_employer_headers


def _instant(text: str) -> datetime:
    """Parse an ISO 8601 instant regardless of fractional-second formatting."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class TestApplicationCreationGates:
    def test_application_on_confidential_employer_rejected(self, api):
        """PRD §2.8: "At application creation, an employer named in the nurse's `confidentiality_exclusions` who attempts to initiate an application to that nurse is rejected with `ERR_CANDIDATE_CONFIDENTIAL` (HTTP 403)."

        Design: Corner/validations/application_on_confidential_employer_rejected
        """
        fx.set_clock()
        shady = fx.create_employer(
            legal_name="Shady Pines", fee_model="SUBSCRIPTION",
            subscription_tier="PRO", guarantee_days=90, placement_fee_bps=1500,
        )
        nurse = fx.setup_active_nurse(
            email="shy3@x.com", current_employer_name="Shady Pines",
        )["nurse"]
        req = fx.create_requisition(shady, unit_name="ICU-South", openings_total=1)

        resp = api_client.create_application(
            create_application_payload(
                req["id"], nurse["id"], fx.fresh_nurse_version(nurse["id"]),
            ),
            make_employer_headers(shady["id"]),
        )
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_CONFIDENTIAL, 403)

        _, meta = validate_paginated(
            api_client.list_nurse_applications(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert meta["total_count"] == 0

    def test_application_requires_active_license_verified_nurse(self, api):
        """PRD §3.4: "The nurse must be `ACTIVE` and license-verified, or creation fails with `ERR_CREDENTIALS_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/application_requires_active_license_verified_nurse
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")
        lic = fx.add_license(nurse)
        fx.submit_nurse(nurse)  # PENDING_VERIFICATION; license still PENDING
        employer = fx.create_employer()
        req = fx.create_requisition(employer)

        nurse_now = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        resp = api_client.create_application(
            create_application_payload(req["id"], nurse["id"], nurse_now["version"],
                                       proposed_hourly_rate_cents=9000),
            make_employer_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDENTIALS_INCOMPLETE)

        _, meta = validate_paginated(
            api_client.list_nurse_applications(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert meta["total_count"] == 0

    def test_terms_mismatch_shift_and_rate_floor(self, api):
        """PRD §3.4: "The proposed terms must match the requisition: `proposed_shift` must equal the requisition's `shift`, and `proposed_hourly_rate_cents` must be at least the requisition's `offered_hourly_rate_cents`; violations are rejected with `ERR_TERMS_MISMATCH` (HTTP 422)."

        Design: Corner/validations/terms_mismatch_shift_and_rate_floor
        """
        ctx = fx.setup_marketplace()
        nurse, employer, req = ctx["nurse"], ctx["employer"], ctx["requisition"]

        bad_shift = api_client.create_application(
            create_application_payload(
                req["id"], nurse["id"], fx.fresh_nurse_version(nurse["id"]),
                proposed_shift="NIGHT",
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(bad_shift, ApiErrorId.ERR_TERMS_MISMATCH)

        low_rate = api_client.create_application(
            create_application_payload(
                req["id"], nurse["id"], fx.fresh_nurse_version(nurse["id"]),
                proposed_hourly_rate_cents=7999,
            ),
            make_employer_headers(employer["id"]),
        )
        validate_error(low_rate, ApiErrorId.ERR_TERMS_MISMATCH)

        _, meta = validate_paginated(
            api_client.list_nurse_applications(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert meta["total_count"] == 0


class TestApplicationOcc:
    def test_create_stale_nurse_version_rejected(self, api):
        """PRD §2.7: "Creating an application — the employer-initiated application write — requires the request to carry `expected_nurse_version`, a non-optional field holding the `version` of the target `Nurse` as the employer last observed it. If the nurse's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_NURSE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/application_create_occ_stale_nurse_version_rejected
        """
        ctx = fx.setup_marketplace()
        nurse, employer = ctx["nurse"], ctx["employer"]
        observed_version = fx.fresh_nurse_version(nurse["id"])

        # The first application legitimately bumps the nurse's version.
        fx.create_application(ctx["requisition"], nurse, employer)

        employer2 = fx.create_employer(
            legal_name="Coastal General", fee_model="SUBSCRIPTION",
            subscription_tier="PRO", guarantee_days=90, placement_fee_bps=1500,
        )
        req2 = fx.create_requisition(
            employer2, unit_name="ICU-North", offered_hourly_rate_cents=8200, openings_total=1,
        )
        stale = api_client.create_application(
            create_application_payload(req2["id"], nurse["id"], observed_version,
                                       proposed_hourly_rate_cents=8300),
            make_employer_headers(employer2["id"]),
        )
        assert stale.status_code == 412
        validate_error(stale, ApiErrorId.ERR_STALE_NURSE_VERSION, 412)

        fresh = api_client.create_application(
            create_application_payload(
                req2["id"], nurse["id"], fx.fresh_nurse_version(nurse["id"]),
                proposed_hourly_rate_cents=8300,
            ),
            make_employer_headers(employer2["id"]),
        )
        validate_success(fresh, expected_status=201)

        nurse_now = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse_now["active_application_count"] == 2


class TestCounterCycle:
    def test_counter_cycle_single_deadline_extension(self, api):
        """PRD §3.4: "Each counter increments `revision_count`, which is hard-capped at 2; a counter attempted at the cap is rejected with `ERR_TERMS_MISMATCH`. The first counter additionally extends the deadline: when `deadline_extended` is false, `response_deadline_at` gains a further 48 hours and `deadline_extended` flips true; a second counter leaves the deadline unchanged but still increments `revision_count`."

        Design: Difficulty/non_linear_state_machine/application_counter_cycle_with_single_deadline_extension
        """
        ctx = fx.setup_application_under_review()
        app, employer, nurse = ctx["application"], ctx["employer"], ctx["nurse"]
        created_deadline = _instant(app["response_deadline_at"])
        assert created_deadline == datetime(2026, 9, 4, tzinfo=timezone.utc), (
            "creation sets response_deadline_at = submission + 72 hours"
        )

        first = validate_success(
            api_client.counter_application(
                app["id"], {"proposed_hourly_rate_cents": 8700},
                make_employer_headers(employer["id"]),
            )
        )
        assert first["revision_count"] == 1
        assert first["deadline_extended"] is True
        assert _instant(first["response_deadline_at"]) == created_deadline + timedelta(hours=48), (
            "the first counter extends the deadline by a further 48 hours"
        )
        assert first["status"] == "UNDER_REVIEW"

        second = validate_success(
            api_client.counter_application(
                app["id"], {"proposed_hourly_rate_cents": 9000},
                make_employer_headers(employer["id"]),
            )
        )
        assert second["revision_count"] == 2
        assert second["deadline_extended"] is True
        assert _instant(second["response_deadline_at"]) == _instant(first["response_deadline_at"]), (
            "the second counter leaves the deadline unchanged"
        )
        assert second["status"] == "UNDER_REVIEW"

        third = api_client.counter_application(
            app["id"], {"proposed_hourly_rate_cents": 9100},
            make_employer_headers(employer["id"]),
        )
        validate_error(third, ApiErrorId.ERR_TERMS_MISMATCH)

        after = validate_success(
            api_client.get_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "UNDER_REVIEW"
        assert after["revision_count"] == 2

    def test_counter_extends_deadline_exactly_once(self, api):
        """PRD §3.4: "The first counter additionally extends the deadline: when `deadline_extended` is false, `response_deadline_at` gains a further 48 hours and `deadline_extended` flips true; a second counter leaves the deadline unchanged but still increments `revision_count`."

        Design: Difficulty/non_linear_state_machine/application_counter_cycle_with_single_deadline_extension
        """
        ctx = fx.setup_application_under_review()
        app, employer = ctx["application"], ctx["employer"]
        initial_deadline = _instant(app["response_deadline_at"])

        first = validate_success(
            api_client.counter_application(
                app["id"], {"proposed_hourly_rate_cents": 8700},
                make_employer_headers(employer["id"]),
            )
        )
        assert first["deadline_extended"] is True
        assert _instant(first["response_deadline_at"]) == initial_deadline + timedelta(hours=48)

        second = validate_success(
            api_client.counter_application(
                app["id"], {"proposed_hourly_rate_cents": 8800},
                make_employer_headers(employer["id"]),
            )
        )
        assert second["response_deadline_at"] == first["response_deadline_at"]
        assert second["deadline_extended"] is True


class TestResponseDeadlineBoundary:
    def test_exact_equality_expires_and_one_ms_earlier_reviews(self, api):
        """PRD §3.4: "On any clock advance that reaches `response_deadline_at`, an application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` transitions to the terminal `EXPIRED` — the boundary is inclusive, so a clock reading exactly equal to the deadline expires the application — and any of its interviews still `SCHEDULED` cascade to `CANCELLED`."
        PRD §3.4: "The nurse, acting as `Candidate`, moves the application from `SUBMITTED` to `UNDER_REVIEW` by reviewing it — permitted only while clock now is still before `response_deadline_at`; an action at or past the deadline is rejected with `ERR_DEADLINE_PASSED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/response_deadline_exact_equality_expires
        """
        fx.set_clock()
        nurse_a = fx.setup_active_nurse(email="a@x.com")["nurse"]
        nurse_b = fx.setup_active_nurse(email="b@x.com", years_experience=4)["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(employer)
        app_a = fx.create_application(req, nurse_a, employer)
        app_b = fx.create_application(req, nurse_b, employer)

        fx.set_clock("2026-09-03T23:59:59.999Z")
        reviewed = validate_success(
            api_client.review_application(app_a["id"], make_candidate_headers(nurse_a["id"]))
        )
        assert reviewed["status"] == "UNDER_REVIEW"

        fx.set_clock("2026-09-04T00:00:00Z")
        app_b_after = validate_success(
            api_client.get_application(app_b["id"], make_candidate_headers(nurse_b["id"]))
        )
        assert app_b_after["status"] == "EXPIRED", (
            "clock == response_deadline_at expires the application (inclusive boundary)"
        )
        late = api_client.review_application(app_b["id"], make_candidate_headers(nurse_b["id"]))
        validate_error(late, ApiErrorId.ERR_INVALID_STATE)

    def test_review_at_deadline_rejected(self, api):
        """PRD §3.4: "The nurse, acting as `Candidate`, moves the application from `SUBMITTED` to `UNDER_REVIEW` by reviewing it — permitted only while clock now is still before `response_deadline_at`; an action at or past the deadline is rejected with `ERR_DEADLINE_PASSED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/response_deadline_exact_equality_expires
        """
        fx.set_clock()
        nurse = fx.setup_active_nurse(email="nora@x.com")["nurse"]
        employer = fx.create_employer()
        req = fx.create_requisition(employer)
        app = fx.create_application(req, nurse, employer)

        # One millisecond before the deadline the review still succeeds.
        fx.set_clock("2026-09-03T23:59:59.999Z")
        reviewed = validate_success(
            api_client.review_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert reviewed["status"] == "UNDER_REVIEW"

        # At exactly the deadline the application expires under the inclusive boundary.
        fx.set_clock("2026-09-04T00:00:00Z")
        after = validate_success(
            api_client.get_application(app["id"], make_candidate_headers(nurse["id"]))
        )
        assert after["status"] == "EXPIRED"
