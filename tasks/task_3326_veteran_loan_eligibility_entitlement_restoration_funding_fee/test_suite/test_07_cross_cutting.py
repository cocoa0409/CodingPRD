"""Corner tests for the appraisal selector's eligibility filter, queue
promotion, and close-time immediate consistency."""
from __future__ import annotations

from test_helpers import (
    create_appraiser_payload,
    create_loan_payload,
    get_appraisal,
    get_entitlement_account,
    get_funding_fee_assessment,
    get_occupancy_certificate,
    make_appraiser_headers,
    setup_approved_loan,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_success,
)


class TestSelectorEligibilityFilter:
    def test_selector_region_mismatch_excludes_pool(self, api):
        """PRD §3.5: "The candidate set is the active appraisers whose region
        equals the loan's `property_region` and whose `open_assignment_count` is
        below their `max_open_assignments`."
        PRD §3.5: "When the candidate set is empty, the appraisal simply stays
        `REQUESTED` — queued, unassigned — and this is not an error."

        Design: Corner/cross_cutting_layers/selector_region_mismatch_excludes_pool
        """
        validate_success(
            api.create_appraiser(
                create_appraiser_payload(name="App SouthOnly", region="SOUTH")),
            expected_status=201,
        )
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Mw"})
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"], property_region="MIDWEST",
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        appraisal = validate_success(
            api.create_appraisal_request(loan["id"]), expected_status=201)
        assert appraisal["status"] == "REQUESTED"
        assert appraisal["appraiser_id"] is None

    def test_inactive_appraiser_excluded_from_assignment(self, api):
        """PRD §3.5: "an optional `active` flag (defaulting true; inactive
        appraisers are excluded from assignment)"

        Design: Corner/cross_cutting_layers/inactive_appraiser_excluded_from_assignment
        """
        validate_success(
            api.create_appraiser(create_appraiser_payload(
                name="App Inact", region="SOUTH", active=False)),
            expected_status=201,
        )
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Ina"})
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        appraisal = validate_success(
            api.create_appraisal_request(loan["id"]), expected_status=201)
        assert appraisal["status"] == "REQUESTED"
        assert appraisal["appraiser_id"] is None


class TestQueuePromotion:
    def test_appraisal_promotion_on_value_issued_frees_slot(self, api):
        """PRD §3.5: "it moves the appraisal to its terminal `VALUE_ISSUED`
        state, sets `appraised_value_cents` from the payload, increments
        `report_round`, decrements the appraiser's `open_assignment_count`, and
        runs queue promotion for that appraiser."
        PRD §3.2: "the earliest-created appraisal still waiting in `REQUESTED` in
        that appraiser's region becomes `ASSIGNED` to that appraiser"

        Design: Corner/cross_cutting_layers/appraisal_promotion_on_value_issued_frees_slot
        """
        appraiser = validate_success(
            api.create_appraiser(create_appraiser_payload(
                name="App P", region="SOUTH", max_open_assignments=1)),
            expected_status=201,
        )
        ctx_1 = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V P1"})
        loan_1 = validate_success(
            api.create_loan(
                ctx_1["veteran"]["id"],
                create_loan_payload(ctx_1["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        first = validate_success(
            api.create_appraisal_request(loan_1["id"]), expected_status=201)
        assert first["status"] == "ASSIGNED"
        assert first["appraiser_id"] == appraiser["id"]

        ctx_2 = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V P2"})
        loan_2 = validate_success(
            api.create_loan(
                ctx_2["veteran"]["id"],
                create_loan_payload(ctx_2["coe"]["id"],
                                    purchase_price_cents=21000000),
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_appraisal_request(loan_2["id"]), expected_status=201)
        assert second["status"] == "REQUESTED"

        validate_success(
            api.submit_appraisal_report(
                first["id"],
                {"outcome": "VALUE_ISSUED", "appraised_value_cents": 20000000},
                headers=make_appraiser_headers(appraiser["id"]),
            )
        )
        promoted = get_appraisal(second["id"])
        assert promoted["status"] == "ASSIGNED"
        assert promoted["appraiser_id"] == appraiser["id"]


class TestCloseImmediateConsistency:
    def test_close_response_reflects_all_cascaded_mutations(self, api):
        """PRD §3.4: "A successful close fires a four-link cascade. The loan's
        `closing_status` becomes `CLOSED`, `closing_date` and
        `first_payment_due_date` are set from the close payload, and the loan's
        `version` increments. The entitlement charge posts:
        `entitlement_charged_cents` becomes the smaller of one quarter of the
        loan amount (rounded half up to whole cents) and the account's
        `remaining_with_bonus_cents`, and the funding fee assessment moves from
        `ASSESSED` to `COLLECTED` with `collected_cents` set to the
        `assessed_fee_cents`."

        Design: Corner/consistency_model/close_response_reflects_all_cascaded_mutations
        """
        ctx = setup_approved_loan(price_cents=20000000)
        closed = validate_success(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            })
        )
        assert closed["closing_status"] == "CLOSED"
        assert closed["entitlement_charged_cents"] == 5000000

        # Follow-up reads agree immediately (no eventual-consistency window).
        fee = get_funding_fee_assessment(ctx["loan"]["id"])
        assert fee["status"] == "COLLECTED"
        account = get_entitlement_account(ctx["veteran"]["id"])
        assert account["total_charged_cents"] == 5000000
