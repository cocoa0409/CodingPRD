"""Cascades, the openings conservation invariant, requisition closure, and
employer suspension."""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.factories import create_offer_payload
from test_helpers.test_users import ADMIN, make_candidate_headers, make_employer_headers


class TestOfferAcceptFillCascade:
    def test_offer_accept_fill_cascade_three_hops(self, api):
        """PRD §3.7: "Second, the requisition's `openings_filled` increases by 1; if it thereby equals `openings_total`, the requisition transitions `OPEN` to `FILLED`, which itself cascades every sibling application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` to `WITHDRAWN` and every sibling application in `OFFER_EXTENDED` to offer-`RESCINDED`. Third, the nurse transitions `ACTIVE` to `HIRED`, which cascades all of that nurse's other live applications — any in `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` — to `WITHDRAWN`. Fourth, the application itself transitions to `ACCEPTED`."
        PRD §3.4: "The employer may withdraw from the same three states, moving the application to `WITHDRAWN` and cascading any of its interviews still `SCHEDULED` to `CANCELLED`; the withdrawing employer must own the application's `employer_id`."

        Design: Difficulty/transitive_cascade/offer_accept_fill_cascade_three_hops
        """
        # Nurse A carried to an ISSUED offer on a one-seat requisition.
        ctx = fx.setup_offer_issued(req_overrides={"openings_total": 1})
        nurse_a, employer, req = ctx["nurse"], ctx["employer"], ctx["requisition"]
        offer_a = ctx["offer"]

        # Nurse B on the same requisition in INTERVIEWING with a SCHEDULED interview.
        nurse_b = fx.setup_active_nurse(email="bree@x.com", years_experience=5)["nurse"]
        app_b = fx.create_application(req, nurse_b, employer, proposed_hourly_rate_cents=8200)
        fx.review_application(app_b, nurse_b)
        iv_b = fx.schedule_interview(
            app_b, employer,
            starts_at="2026-09-03T10:00:00Z", ends_at="2026-09-03T11:00:00Z",
        )

        placement = validate_success(
            api_client.accept_offer(offer_a["id"], make_candidate_headers(nurse_a["id"]))
        )
        assert placement["status"] == "PENDING_START"
        assert placement["annualized_salary_cents"] == 8500 * 2080

        req_after = validate_success(
            api_client.get_requisition(req["id"], make_employer_headers(employer["id"]))
        )
        assert req_after["openings_filled"] == 1
        assert req_after["status"] == "FILLED"

        app_b_after = validate_success(
            api_client.get_application(app_b["id"], make_employer_headers(employer["id"]))
        )
        assert app_b_after["status"] == "WITHDRAWN"

        iv_b_after = validate_success(
            api_client.get_interview(iv_b["id"], make_employer_headers(employer["id"]))
        )
        assert iv_b_after["status"] == "CANCELLED"

        nurse_a_after = validate_success(
            api_client.get_nurse(nurse_a["id"], make_candidate_headers(nurse_a["id"]))
        )
        assert nurse_a_after["status"] == "HIRED"
        nurse_b_after = validate_success(
            api_client.get_nurse(nurse_b["id"], make_candidate_headers(nurse_b["id"]))
        )
        assert nurse_b_after["status"] == "ACTIVE"

    def test_accept_hires_nurse_and_accepts_application(self, api):
        """PRD §3.7: "Third, the nurse transitions `ACTIVE` to `HIRED`, which cascades all of that nurse's other live applications — any in `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` — to `WITHDRAWN`. Fourth, the application itself transitions to `ACCEPTED`."

        Design: Difficulty/transitive_cascade/offer_accept_fill_cascade_three_hops
        """
        ctx = fx.setup_offer_issued()
        nurse, employer = ctx["nurse"], ctx["employer"]

        # A second, live application from another employer on the same nurse.
        employer2 = fx.create_employer(
            legal_name="Coastal General", fee_model="SUBSCRIPTION",
            subscription_tier="PRO", guarantee_days=90, placement_fee_bps=1500,
        )
        req2 = fx.create_requisition(
            employer2, unit_name="ICU-North", offered_hourly_rate_cents=8200, openings_total=1,
        )
        app2 = fx.create_application(req2, nurse, employer2, proposed_hourly_rate_cents=8300)
        fx.review_application(app2, nurse)

        placement = validate_success(
            api_client.accept_offer(ctx["offer"]["id"], make_candidate_headers(nurse["id"]))
        )
        assert placement["status"] == "PENDING_START"

        app_after = validate_success(
            api_client.get_application(ctx["application"]["id"], make_employer_headers(employer["id"]))
        )
        assert app_after["status"] == "ACCEPTED"
        nurse_after = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse_after["status"] == "HIRED"

        app2_after = validate_success(
            api_client.get_application(app2["id"], make_employer_headers(employer2["id"]))
        )
        assert app2_after["status"] == "WITHDRAWN"


class TestOpeningsConservation:
    def test_openings_conserved_through_fill_and_guarantee_termination(self, api):
        """PRD §2.10: "The system maintains a conservation invariant across all of this: for every requisition, `openings_filled` always equals the count of its placements in `PENDING_START`, `GUARANTEE_ACTIVE`, or `COMPLETED`, and always satisfies zero at minimum and `openings_total` at maximum. Placements in `TERMINATED_IN_GUARANTEE` are excluded from the count — the seat returns to the pool in the same request that terminates the placement."
        PRD §3.8: "The requisition's `openings_filled` decreases by 1, and if the requisition was `FILLED` it transitions back to `OPEN` — the seat returns to the pool."

        Design: Difficulty/compensating_invariant/openings_conserved_through_fill_and_guarantee_termination
        """
        ctx = fx.setup_placement_accepted(req_overrides={"openings_total": 1})
        employer, req, placement = ctx["employer"], ctx["requisition"], ctx["placement"]

        req_mid = validate_success(
            api_client.get_requisition(req["id"], make_employer_headers(employer["id"]))
        )
        assert req_mid["openings_filled"] == 1
        assert req_mid["status"] == "FILLED"
        assert 0 <= req_mid["openings_filled"] <= req_mid["openings_total"]

        fx.set_clock("2026-10-30T00:00:00Z")
        terminated = validate_success(
            api_client.terminate_placement(placement["id"], make_employer_headers(employer["id"]))
        )
        assert terminated["status"] == "TERMINATED_IN_GUARANTEE"

        req_after = validate_success(
            api_client.get_requisition(req["id"], make_employer_headers(employer["id"]))
        )
        assert req_after["openings_filled"] == 0
        assert req_after["status"] == "OPEN"
        assert 0 <= req_after["openings_filled"] <= req_after["openings_total"]

        # The terminated placement no longer counts toward the invariant set.
        _, meta = validate_paginated(
            api_client.list_placements(
                make_employer_headers(employer["id"]), params={"requisition_id": req["id"]}
            )
        )
        assert meta["total_count"] == 1  # only the terminated row exists
        live, _ = validate_paginated(
            api_client.list_placements(
                make_employer_headers(employer["id"]),
                params={"requisition_id": req["id"], "status": "GUARANTEE_ACTIVE"},
            )
        )
        assert len(live) == 0
        live2, _ = validate_paginated(
            api_client.list_placements(
                make_employer_headers(employer["id"]),
                params={"requisition_id": req["id"], "status": "PENDING_START"},
            )
        )
        assert len(live2) == 0
        assert len(live) + len(live2) == req_after["openings_filled"]

    def test_termination_returns_nurse_to_active(self, api):
        """PRD §3.8: "The nurse transitions from `HIRED` back to `ACTIVE`."

        Design: Difficulty/compensating_invariant/openings_conserved_through_fill_and_guarantee_termination
        """
        ctx = fx.setup_placement_accepted(req_overrides={"openings_total": 1})
        nurse, employer = ctx["nurse"], ctx["employer"]

        fx.set_clock("2026-10-30T00:00:00Z")
        validate_success(
            api_client.terminate_placement(
                ctx["placement"]["id"], make_employer_headers(employer["id"])
            )
        )

        nurse_after = validate_success(
            api_client.get_nurse(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert nurse_after["status"] == "ACTIVE"


class TestPlacementTerminationClockGate:
    def test_termination_after_guarantee_end_rejected(self, api):
        """PRD §3.8: "Termination requires the clock's current date be on or before `guarantee_ends_on`; a termination attempted after that date is rejected with `ERR_PLACEMENT_GUARANTEE_EXPIRED` (HTTP 409), because the placement is complete and the fee is final."
        PRD §3.8: "On any clock advance moving strictly past `guarantee_ends_on`, a `GUARANTEE_ACTIVE` placement transitions to `COMPLETED`, and its linked placement-fee invoice transitions to `SETTLED`: the provisional fee becomes final and no refund is possible thereafter."

        Design: Difficulty/cross_entity_state_dependency/placement_termination_gated_by_clock_vs_guarantee_end
        """
        ctx = fx.setup_placement_accepted()
        employer, placement = ctx["employer"], ctx["placement"]
        invoice = fx.get_placement_invoice(placement, employer)

        fx.set_clock("2026-12-15T00:00:00Z")

        placement_after = validate_success(
            api_client.get_placement(placement["id"], make_employer_headers(employer["id"]))
        )
        assert placement_after["status"] == "COMPLETED"

        resp = api_client.terminate_placement(placement["id"], make_employer_headers(employer["id"]))
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_GUARANTEE_EXPIRED)

        invoice_after = validate_success(
            api_client.get_invoice(invoice["id"], make_employer_headers(employer["id"]))
        )
        assert invoice_after["status"] == "SETTLED"

    def test_completed_placement_invoice_settles_on_guarantee_end(self, api):
        """PRD §3.8: "On any clock advance moving strictly past `guarantee_ends_on`, a `GUARANTEE_ACTIVE` placement transitions to `COMPLETED`, and its linked placement-fee invoice transitions to `SETTLED`: the provisional fee becomes final and no refund is possible thereafter."

        Design: Difficulty/cross_entity_state_dependency/placement_termination_gated_by_clock_vs_guarantee_end
        """
        ctx = fx.setup_placement_accepted()
        employer, placement = ctx["employer"], ctx["placement"]
        invoice = fx.get_placement_invoice(placement, employer)
        assert invoice["status"] == "ISSUED"

        fx.set_clock("2026-12-15T00:00:00Z")

        placement_after = validate_success(
            api_client.get_placement(placement["id"], make_employer_headers(employer["id"]))
        )
        assert placement_after["status"] == "COMPLETED"
        invoice_after = validate_success(
            api_client.get_invoice(invoice["id"], make_employer_headers(employer["id"]))
        )
        assert invoice_after["status"] == "SETTLED"


class TestEmployerSuspension:
    def test_suspend_blocks_new_applications_and_offer_issuance(self, api):
        """PRD §3.2: "Suspension blocks two operations for that employer: initiating new applications and issuing offers, both rejected with `ERR_NO_OPENINGS` (HTTP 409) at the quota-check priority."

        Design: Corner/state_machines/employer_suspend_blocks_new_applications_and_offer_issuance
        """
        ctx = fx.setup_application_with_completed_interview()
        nurse, employer, req = ctx["nurse"], ctx["employer"], ctx["requisition"]

        suspended = validate_success(api_client.suspend_employer(employer["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"

        new_app = api_client.create_application(
            {
                "requisition_id": req["id"],
                "nurse_id": nurse["id"],
                "proposed_hourly_rate_cents": 8500,
                "proposed_shift": "DAY",
                "expected_nurse_version": fx.fresh_nurse_version(nurse["id"]),
            },
            make_employer_headers(employer["id"]),
        )
        validate_error(new_app, ApiErrorId.ERR_NO_OPENINGS)

        offer = api_client.issue_offer(
            ctx["application"]["id"],
            create_offer_payload(fx.fresh_requisition_version(req["id"], employer)),
            make_employer_headers(employer["id"]),
        )
        validate_error(offer, ApiErrorId.ERR_NO_OPENINGS)

        # Reads keep working under suspension.
        req_read = validate_success(
            api_client.get_requisition(req["id"], make_employer_headers(employer["id"]))
        )
        assert req_read["status"] == "OPEN"


class TestRequisitionClosure:
    def test_close_with_offer_extended_blocked(self, api):
        """PRD §3.2: "closure requires that no application against the requisition be in `OFFER_EXTENDED`, and cascades every application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` to `WITHDRAWN`."
        PRD §3.1: "Any transition attempted from a state where it does not exist is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/requisition_close_with_offer_extended_blocked
        """
        ctx = fx.setup_offer_issued()
        employer, req, offer = ctx["employer"], ctx["requisition"], ctx["offer"]

        resp = api_client.close_requisition(req["id"], make_employer_headers(employer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        req_after = validate_success(
            api_client.get_requisition(req["id"], make_employer_headers(employer["id"]))
        )
        assert req_after["status"] == "OPEN"
        offer_after = validate_success(
            api_client.get_offer(offer["id"], make_employer_headers(employer["id"]))
        )
        assert offer_after["status"] == "ISSUED"
