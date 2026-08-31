"""Counterfeit detection: the seizure cascade and its symmetric unwind."""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_1,
    assert_bag_settlement_identity,
    assert_counterfeit_report,
    assert_fitness_lot,
    correction_note_payload,
    make_compliance_headers,
    read_account,
    read_bag,
    read_session,
    read_session_lots,
    read_ticket,
    setup_drafted_counterfeit_report,
    setup_submitted_counterfeit_report,
    validate_error,
    validate_success,
)


class TestSeizureCascade:
    def test_submitting_the_report_seizes_the_lot_and_drains_the_bag(self, api):
        """PRD §3.5: "On success `submitted_at` is stamped from the logical clock and a
        four-hop cascade runs. First, the lot moves `PENDING_REVIEW → SEIZED`. Second,
        because the lot was seized, the lot's counting session's `seized_face_value_cents`
        and the bag's `seized_amount_cents` both increase by the lot's `face_value_cents`,
        and the bag's `settlement_amount_cents` is recomputed as `counted_amount_cents` plus
        `claim_adjustment_cents` minus `seized_amount_cents` — so the seizure reduces what
        the customer will ultimately be paid."
        PRD §3.5: "Submitting the report moves it `DRAFT → SUBMITTED` and is where value
        actually leaves the deposit."

        Design: Difficulty/transitive_cascade/counterfeit_submit_cascades_lot_to_bag_to_ticket_to_account
        """
        scenario = setup_drafted_counterfeit_report(credit_branch="provisional")

        response = api.submit_counterfeit_report(
            scenario["report"]["id"], make_compliance_headers(COMPLIANCE_1)
        )
        report = validate_success(response, 200)
        assert_counterfeit_report(report)
        assert report["status"] == "SUBMITTED", f"Expected SUBMITTED, got {report['status']}"
        assert report["submitted_at"] is not None, "submitted_at is stamped on submission"

        lot = read_session_lots(scenario["session"]["id"], category="COUNTERFEIT_SUSPECT")[0]
        assert_fitness_lot(lot)
        assert lot["status"] == "SEIZED", f"The lot must move to SEIZED, got {lot['status']}"

        session = read_session(scenario["session"]["id"])
        assert session["seized_face_value_cents"] == 20_000, (
            f"The session's seized total rises by the lot's 20000 face value, got "
            f"{session['seized_face_value_cents']}"
        )

        bag = read_bag(scenario["bag"]["id"])
        assert bag["counted_amount_cents"] == 100_000, "The machine reading is not rewritten"
        assert bag["seized_amount_cents"] == 20_000, (
            f"The bag's seized_amount_cents rises by 20000, got {bag['seized_amount_cents']}"
        )
        assert bag["settlement_amount_cents"] == 80_000, (
            f"100000 + 0 - 20000 = 80000, got {bag['settlement_amount_cents']}"
        )
        assert_bag_settlement_identity(bag)

    def test_the_seizure_bubbles_up_to_the_ticket_and_the_depositors_risk_figures(self, api):
        """PRD §3.5: "Third, because the bag's settlement amount changed, the deposit
        ticket's `counted_total_cents` is recomputed. Fourth, because the ticket total
        changed, the depositor's `counterfeit_incident_count` is incremented by 1 and the
        persisted risk figures are recomputed by re-running the `SETTLED_ONLY` view of the
        risk model described in §3.7 onto the account's `risk_score` and `risk_grade`."
        PRD §3.7: "The raw score then starts at 100 and subtracts three penalties: 1.5
        points for each percentage point of variance ratio, 8 points for each counterfeit
        incident in the view, and 3 points for each denied claim on the account."
        PRD §3.7: "The letter band follows from the score: at least 80 is `A`, otherwise at
        least 60 is `B`, otherwise at least 40 is `C`, and anything below 40 is `D`."

        Design: Difficulty/transitive_cascade/counterfeit_submit_cascades_lot_to_bag_to_ticket_to_account
        """
        scenario = setup_submitted_counterfeit_report(credit_branch="provisional")

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["counted_total_cents"] == 80_000, (
            f"The ticket total follows the bag down to 80000, got {ticket['counted_total_cents']}"
        )

        account = read_account(scenario["account"]["id"])
        assert account["counterfeit_incident_count"] == 1, (
            f"Expected counterfeit_incident_count 1, got {account['counterfeit_incident_count']}"
        )
        assert account["risk_score"] == 92.00, (
            "No ticket has settled, so the variance ratio is 0.00 and only the single "
            f"counterfeit incident scores: 100 - 8 = 92.00, got {account['risk_score']}"
        )
        assert account["risk_grade"] == "A", (
            f"92.00 is at least 80, so the band is A, got {account['risk_grade']}"
        )

    def test_returning_the_report_for_correction_unwinds_every_seizure_effect(self, api):
        """PRD §3.5: "Every seizure effect is unwound symmetrically: the lot moves `SEIZED →
        PENDING_REVIEW`; the bag's `seized_amount_cents` and the session's
        `seized_face_value_cents` each decrease by the lot's `face_value_cents`; the bag's
        `settlement_amount_cents` and the ticket's `counted_total_cents` are recomputed from
        the restored figures; and the depositor's `counterfeit_incident_count` is decremented
        by 1 with the `SETTLED_ONLY` risk view re-run onto `risk_score` and `risk_grade`."
        PRD §3.5: "Returning it for correction requires a `correction_note` giving the
        reason, moves the report `SUBMITTED → DRAFT`, writes the note, and clears
        `submitted_at` back to null."

        Design: Corner/state_machines/counterfeit_return_for_correction_unwinds_the_seizure_cascade
        """
        scenario = setup_submitted_counterfeit_report()
        session_id = scenario["session"]["id"]
        notes_before = sum(lot["note_count"] for lot in read_session_lots(session_id))

        response = api.return_counterfeit_report_for_correction(
            scenario["report"]["id"],
            correction_note_payload("Serial number transposed; refile with the corrected serial."),
            make_compliance_headers(COMPLIANCE_1),
        )
        report = validate_success(response, 200)
        assert report["status"] == "DRAFT", f"Expected DRAFT, got {report['status']}"
        assert report["submitted_at"] is None, "submitted_at is cleared back to null"

        lot = read_session_lots(session_id, category="COUNTERFEIT_SUSPECT")[0]
        assert lot["status"] == "PENDING_REVIEW", (
            f"The lot returns to PENDING_REVIEW, got {lot['status']}"
        )
        assert read_session(session_id)["seized_face_value_cents"] == 0, (
            "The session's seized total returns to 0"
        )

        bag = read_bag(scenario["bag"]["id"])
        assert bag["seized_amount_cents"] == 0, "The bag's seized_amount_cents returns to 0"
        assert bag["settlement_amount_cents"] == 100_000, (
            f"The bag's settlement amount is restored to 100000, got {bag['settlement_amount_cents']}"
        )
        assert read_ticket(scenario["ticket"]["id"])["counted_total_cents"] == 100_000, (
            "The ticket total is restored to 100000"
        )

        account = read_account(scenario["account"]["id"])
        assert account["counterfeit_incident_count"] == 0, (
            f"counterfeit_incident_count returns to 0, got {account['counterfeit_incident_count']}"
        )
        assert account["risk_score"] == 100.00, (
            f"With no incident and no settled ticket the score is 100.00, got {account['risk_score']}"
        )

        notes_after = sum(lot["note_count"] for lot in read_session_lots(session_id))
        assert notes_after == notes_before == 10, (
            f"The session's note count is conserved across the cycle: {notes_before} then {notes_after}"
        )


class TestReportLotAgreement:
    def test_a_report_that_disagrees_with_its_lot_cannot_be_submitted(self, api):
        """PRD §3.5: "and the filer's assertions must match the lot exactly — the report's
        `denomination_cents` must equal the lot's `denomination_cents` and the report's
        `note_count` must equal the lot's `note_count`, with any difference rejected as
        `ERR_REPORT_LOT_MISMATCH`."
        PRD §3.5: "The report is created in `DRAFT` with `seized_face_value_cents` computed
        as `denomination_cents` multiplied by `note_count`, and with `submitted_at`,
        `case_number` and `correction_note` all null."

        Design: Corner/validations/counterfeit_report_mismatching_its_lot_is_rejected_on_submit
        """
        scenario = setup_drafted_counterfeit_report(report_note_count=3)
        assert scenario["report"]["status"] == "DRAFT"
        assert scenario["report"]["seized_face_value_cents"] == 30_000, (
            "The DRAFT report multiplies out the filer's own assertions"
        )

        response = api.submit_counterfeit_report(
            scenario["report"]["id"], make_compliance_headers(COMPLIANCE_1)
        )
        validate_error(response, ApiErrorId.ERR_REPORT_LOT_MISMATCH.value)
        assert response.status_code == 422

        lot = read_session_lots(scenario["session"]["id"], category="COUNTERFEIT_SUSPECT")[0]
        assert lot["status"] == "PENDING_REVIEW", "The lot is untouched by a refused submission"
        assert read_bag(scenario["bag"]["id"])["seized_amount_cents"] == 0
        assert read_account(scenario["account"]["id"])["counterfeit_incident_count"] == 0
