"""Difficulty tests: transitive cascades — the four-link COE denial cascade and
the four-link close cascade."""
from __future__ import annotations

from test_helpers import (
    add_standard_service_period,
    create_coe_request_payload,
    create_loan_payload,
    create_veteran_payload,
    get_appraisal,
    get_entitlement_account,
    get_funding_fee_assessment,
    get_loan,
    get_occupancy_certificate,
    make_appraiser_headers,
    setup_approved_loan,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    submit_value_issued_report,
    validate_success,
)


class TestCoeDenialCascade:
    def test_coe_denial_cascades_loan_appraisal_appraiser_queue(self, api):
        """PRD §3.2: "Denial is not contained to the certificate. Every loan of
        the same veteran whose `underwriting_status` is still `SUBMITTED`
        becomes `DENIED`. In turn, every appraisal of each such newly denied
        loan that is sitting in `REQUESTED` or `ASSIGNED` becomes `CANCELLED`.
        Each appraiser who held one of those cancelled `ASSIGNED` appraisals has
        their `open_assignment_count` decremented accordingly. And each freed
        appraiser slot triggers queue promotion: the earliest-created appraisal
        still waiting in `REQUESTED` in that appraiser's region becomes
        `ASSIGNED` to that appraiser, whose `open_assignment_count` increments."

        Design: Difficulty/transitive_cascade/coe_denial_cascades_loan_appraisal_appraiser_queue
        """
        appraiser = validate_success(
            api.create_appraiser({
                "name": "App C", "region": "SOUTH", "max_open_assignments": 1,
            }),
            expected_status=201,
        )
        # Veteran A: healthy ISSUED COE (PRD §3.3 requires an ISSUED COE for
        # loan creation), loan SUBMITTED, appraisal holds the appraiser's
        # single slot. A second COE request, left in REQUESTED, is the
        # denial trigger (PRD §3.2: denial moves a certificate from
        # REQUESTED to DENIED and fires the four-link cascade).
        vet_a = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Den A")),
            expected_status=201,
        )
        add_standard_service_period(vet_a["id"])
        coe_a = validate_success(
            api.create_coe_request(vet_a["id"], create_coe_request_payload()),
            expected_status=201,
        )
        validate_success(api.issue_coe(coe_a["id"]))
        loan_a = validate_success(
            api.create_loan(
                vet_a["id"],
                create_loan_payload(coe_a["id"], purchase_price_cents=25000000),
            ),
            expected_status=201,
        )
        appraisal_a = validate_success(
            api.create_appraisal_request(loan_a["id"]), expected_status=201)
        assert appraisal_a["status"] == "ASSIGNED"
        assert appraisal_a["appraiser_id"] == appraiser["id"]
        coe_a2 = validate_success(
            api.create_coe_request(vet_a["id"], create_coe_request_payload()),
            expected_status=201,
        )

        # Veteran B: healthy ISSUED COE, loan SUBMITTED; the pool is exhausted
        # so its appraisal queues in REQUESTED.
        ctx_b = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V Den B"})
        loan_b = validate_success(
            api.create_loan(
                ctx_b["veteran"]["id"],
                create_loan_payload(ctx_b["coe"]["id"],
                                    purchase_price_cents=25000000),
            ),
            expected_status=201,
        )
        appraisal_b = validate_success(
            api.create_appraisal_request(loan_b["id"]), expected_status=201)
        assert appraisal_b["status"] == "REQUESTED"

        # Trigger: deny veteran A's second (still REQUESTED) COE request.
        validate_success(api.deny_coe(coe_a2["id"]))

        assert get_loan(loan_a["id"])["underwriting_status"] == "DENIED"
        assert get_appraisal(appraisal_a["id"])["status"] == "CANCELLED"
        # The freed slot promotes veteran B's queued appraisal.
        promoted = get_appraisal(appraisal_b["id"])
        assert promoted["status"] == "ASSIGNED"
        assert promoted["appraiser_id"] == appraiser["id"]

    def test_coe_denial_cascade_does_not_touch_other_veterans_loans(self, api):
        """PRD §3.2: "Every loan of the same veteran whose `underwriting_status`
        is still `SUBMITTED` becomes `DENIED`."

        Design: Difficulty/transitive_cascade/coe_denial_cascades_loan_appraisal_appraiser_queue
        """
        # Same four-link cascade shape, asserting the boundary: the other
        # veteran's SUBMITTED loan survives.
        appraiser = validate_success(
            api.create_appraiser({
                "name": "App C2", "region": "SOUTH", "max_open_assignments": 1,
            }),
            expected_status=201,
        )
        vet_a = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Den A2")),
            expected_status=201,
        )
        add_standard_service_period(vet_a["id"])
        coe_a = validate_success(
            api.create_coe_request(vet_a["id"], create_coe_request_payload()),
            expected_status=201,
        )
        validate_success(api.issue_coe(coe_a["id"]))
        loan_a = validate_success(
            api.create_loan(
                vet_a["id"],
                create_loan_payload(coe_a["id"], purchase_price_cents=25000000),
            ),
            expected_status=201,
        )
        appraisal_a = validate_success(
            api.create_appraisal_request(loan_a["id"]), expected_status=201)
        assert appraisal_a["status"] == "ASSIGNED"
        coe_a2 = validate_success(
            api.create_coe_request(vet_a["id"], create_coe_request_payload()),
            expected_status=201,
        )

        ctx_b = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V Den B2"})
        loan_b = validate_success(
            api.create_loan(
                ctx_b["veteran"]["id"],
                create_loan_payload(ctx_b["coe"]["id"],
                                    purchase_price_cents=25000000),
            ),
            expected_status=201,
        )

        validate_success(api.deny_coe(coe_a2["id"]))

        assert get_loan(loan_a["id"])["underwriting_status"] == "DENIED"
        # Veteran B's loan is untouched by the cascade.
        assert get_loan(loan_b["id"])["underwriting_status"] == "SUBMITTED"


class TestCloseCascade:
    def test_close_cascades_fee_entitlement_occupancy(self, api):
        """PRD §3.4: "A successful close fires a four-link cascade. The loan's
        `closing_status` becomes `CLOSED`, `closing_date` and
        `first_payment_due_date` are set from the close payload, and the loan's
        `version` increments. The entitlement charge posts:
        `entitlement_charged_cents` becomes the smaller of one quarter of the
        loan amount (rounded half up to whole cents) and the account's
        `remaining_with_bonus_cents`, and the funding fee assessment moves from
        `ASSESSED` to `COLLECTED` with `collected_cents` set to the
        `assessed_fee_cents`. The entitlement account then absorbs the charge —
        `total_charged_cents` increases by the charged amount and both
        remaining-entitlement variants recompute — and the veteran's
        `charged_loan_count` recomputes. Finally, an `OccupancyCertificate`
        springs into existence for the loan in `CERTIFIED` status."
        PRD §3.6: "its `certification_date` equal to the loan's `closing_date`
        and its `move_in_deadline` sixty days after the closing date, the
        deadline day itself included"

        Design: Difficulty/transitive_cascade/close_cascades_fee_entitlement_occupancy
        """
        ctx = setup_approved_loan(price_cents=30000000)
        closed = validate_success(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            })
        )
        assert closed["closing_status"] == "CLOSED"
        assert closed["entitlement_charged_cents"] == 7500000

        fee = get_funding_fee_assessment(ctx["loan"]["id"])
        assert fee["status"] == "COLLECTED"
        assert fee["collected_cents"] == 645000

        account = get_entitlement_account(ctx["veteran"]["id"])
        assert account["total_charged_cents"] == 7500000
        assert account["remaining_with_bonus_cents"] == 11663750

        veteran = validate_success(api.get_veteran(ctx["veteran"]["id"]))
        assert veteran["charged_loan_count"] == 1

        occ = get_occupancy_certificate(ctx["loan"]["id"])
        assert occ["status"] == "CERTIFIED"
        assert str(occ["move_in_deadline"]).startswith("2026-05-09")

    def test_close_cascade_fee_collects_assessed_amount(self, api):
        """PRD §3.4: "the funding fee assessment moves from `ASSESSED` to
        `COLLECTED` with `collected_cents` set to the `assessed_fee_cents`"

        Design: Difficulty/transitive_cascade/close_cascades_fee_entitlement_occupancy
        """
        ctx = setup_approved_loan(price_cents=30000000)
        fee_before = get_funding_fee_assessment(ctx["loan"]["id"])
        assert fee_before["status"] == "ASSESSED"
        assert fee_before["assessed_fee_cents"] == 645000
        assert fee_before["collected_cents"] == 0

        validate_success(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            })
        )
        fee_after = get_funding_fee_assessment(ctx["loan"]["id"])
        assert fee_after["status"] == "COLLECTED"
        assert fee_after["collected_cents"] == fee_after["assessed_fee_cents"]
        assert fee_after["collected_cents"] == 645000
