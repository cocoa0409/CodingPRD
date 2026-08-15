"""Compensating invariants: seat count and money outstanding (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    clear_application,
    commit_application,
    create_abroad_application,
    create_approved_application,
    create_committed_application,
    create_open_program,
    create_partner_agreement,
    create_student,
    create_submitted_application,
    get_statement_for_application,
    make_student_headers,
    record_payment,
    setup_open_program_with_application,
    validate_success,
    api_client,
    COORD_A_HEADERS,
)


class TestSeatCountInvariant:
    def test_seat_count_commit_withdraw_invariant(self, api):
        """PRD §3.4: "The `seats_taken` counter on a program is a derived figure with an
        exact definition: it counts precisely the program's applications in `COMMITTED` or
        `ABROAD` status — applications holding a seat. ... The counter rises by one at commit
        and falls by one when a committed application withdraws and again when an abroad
        student's return is recorded (§3.8)."

        Design: Difficulty/compensating_invariant/seat_count_commit_withdraw_invariant
        """
        program, student, application = create_approved_application(
            student_overrides={"full_name": "Seat Student", "email": "seat@uni.edu"},
        )
        commit_application(application, student)
        mid = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert mid["seats_taken"] == 1, (
            f"After commit, seats_taken must be 1, got {mid['seats_taken']}"
        )

        withdrawn = validate_success(
            api.withdraw_application(application["id"], make_student_headers(student["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdraw_reason"] == "STUDENT_INITIATED"

        end = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert end["seats_taken"] == 0, (
            "The compensating withdraw must release the seat, restoring seats_taken to 0"
        )

    def test_seat_count_starts_at_zero_then_commit_adds_one(self, api):
        """PRD §3.4: "The `seats_taken` counter on a program is a derived figure with an
        exact definition: it counts precisely the program's applications in `COMMITTED` or
        `ABROAD` status — applications holding a seat. ... The counter rises by one at
        commit ..."

        Design: Difficulty/compensating_invariant/seat_count_commit_withdraw_invariant
        """
        agreement = create_partner_agreement()
        program = create_open_program(agreement["id"], capacity=30)
        baseline = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert baseline["seats_taken"] == 0, (
            "A fresh program holds no seats: seats_taken must be 0"
        )
        student = create_student(full_name="Seat Counter", email="sc@uni.edu")
        application = create_submitted_application(student, program)
        application = clear_application(application, "CLEARED")
        application = approve_application(application["id"])
        # APPROVED is outside the seat-holding set.
        mid = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert mid["seats_taken"] == 0, (
            "APPROVED does not hold a seat; seats_taken must still be 0"
        )
        commit_application(application, student)
        after = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert after["seats_taken"] == 1, (
            "Commit moves the application into COMMITTED and consumes exactly one seat"
        )

    def test_seats_taken_excludes_returned_home(self, api):
        """PRD §3.4: "The `seats_taken` counter on a program is a derived figure with an
        exact definition: it counts precisely the program's applications in `COMMITTED` or
        `ABROAD` status — applications holding a seat. `SUBMITTED`, `RETURNED_FOR_REVISION`,
        `CLEARED`, `APPROVED`, `RETURNED_HOME`, and all terminal statuses are excluded."

        Design: Corner/calculations/seats_taken_excludes_returned
        """
        program, student1, app1 = create_abroad_application(
            student_overrides={"full_name": "Returnee", "email": "ret@uni.edu"},
        )
        # Second application COMMITTED (still holding a seat).
        student2 = create_student(full_name="Stayer", email="stay@uni.edu")
        app2 = create_submitted_application(student2, program)
        app2 = clear_application(app2, "CLEARED")
        app2 = approve_application(app2["id"])
        commit_application(app2, student2)

        mid = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert mid["seats_taken"] == 2, (
            f"COMMITTED + ABROAD both hold seats; expected 2, got {mid['seats_taken']}"
        )

        validate_success(
            api.application_lifecycle(
                app1["id"], {"action": "RECORD_RETURN"}, COORD_A_HEADERS,
            )
        )
        end = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert end["seats_taken"] == 1, (
            "After RECORD_RETURN the seat is released: RETURNED_HOME is outside the "
            "counted set"
        )


class TestRefundCreditMemoInvariant:
    def test_billing_outstanding_pay_void_invariant(self, api):
        """PRD §3.4: "Voiding is the statement's compensating path. When an application
        withdraws from `COMMITTED` — manually per §3.2 or via the suspension cascade per
        §3.6 — its statement, whether `ISSUED`, `PARTIALLY_PAID`, or `PAID`, transitions to
        `VOID`: `credit_memo_cents` is set to the full `amount_paid_cents` (a complete
        refund of monies actually paid) and `outstanding_cents` is forced to 0."

        Design: Difficulty/compensating_invariant/billing_outstanding_pay_void_invariant
        """
        program, student, application = create_approved_application(
            student_overrides={"full_name": "Money Student", "email": "money@uni.edu", "aid_award_cents": 900000},
        )
        commit_application(application, student)

        stmt = get_statement_for_application(application["id"])
        # charge = 1800000 + 35000 + 5000 - 900000
        assert stmt["outstanding_cents"] == 940000

        partial = record_payment(stmt["id"], 100000)
        assert partial["status"] == "PARTIALLY_PAID"
        assert partial["outstanding_cents"] == 840000

        validate_success(
            api.withdraw_application(application["id"], make_student_headers(student["id"]))
        )
        void_stmt = get_statement_for_application(application["id"])
        assert void_stmt["status"] == "VOID"
        assert void_stmt["credit_memo_cents"] == 100000, (
            "Void refunds monies actually paid: credit_memo_cents must equal "
            "amount_paid_cents (100000)"
        )
        assert void_stmt["outstanding_cents"] == 0

    def test_void_is_terminal(self, api):
        """PRD §3.4: "`VOID` is terminal." and PRD §2.10: "The target resource must be in a
        valid from-state for the requested transition ... otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/billing_outstanding_pay_void_invariant
        """
        from test_helpers import BURSAR_HEADERS

        program, student, application = create_approved_application()
        commit_application(application, student)
        stmt = get_statement_for_application(application["id"])
        validate_success(
            api.withdraw_application(application["id"], make_student_headers(student["id"]))
        )
        # A payment against a VOID statement is not a valid transition.
        resp = api.record_payment(stmt["id"], {"amount_cents": 1}, BURSAR_HEADERS)
        from test_helpers import validate_error
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
