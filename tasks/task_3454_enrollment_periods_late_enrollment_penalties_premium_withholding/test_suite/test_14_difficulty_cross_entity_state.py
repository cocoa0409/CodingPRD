"""Difficulty coverage: cross-entity state dependencies — an enrollment's
allowed transitions gated by another entity's clock- or lifecycle-state."""

from test_helpers import (
    ApiErrorId,
    adjust_arrangement,
    enroll,
    enrollment_payload,
    make_beneficiary_headers,
    register_beneficiary,
    set_clock,
    setup_withholding_shortfall,
    switch_collection_method_payload,
    validate_error,
    validate_success,
)


class TestEnrollmentCreationDependsOnWindowState:
    """The same POST /medicare/enrollments succeeds while the beneficiary's
    IEP row is clock-OPEN and fails once the row is EXPIRED."""

    def test_enrollment_succeeds_while_iep_open(self, client):
        """PRD section 3.2: "Precedence among windows is fixed: the IEP
        governs first — when the beneficiary's IEP row is `OPEN`, or
        equivalently when the clock month falls within the inclusive range
        from `iep_start_month` to `iep_end_month`." PRD section 3.2:
        "enrolling one month after `T` yields two months after the enrollment
        month".

        Design: Difficulty/cross_entity_state_dependency/enrollment_creation_depends_on_window_state
        """
        set_clock(client, "2025-07-15T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1960-06-10", full_name="Wendy Window"
        )
        enrollment = enroll(client, beneficiary, part="PART_B")
        # Attainment 2025-06; clock month 2025-07 == T+1 -> effective 2025-09.
        assert enrollment["enrolled_via_window"] == "IEP"
        assert enrollment["effective_month"] == "2025-09"

    def test_enrollment_rejected_once_iep_expired(self, client):
        """PRD section 3.2: "Some window must govern the clock month, or the
        enrollment is rejected with `ERR_NO_OPEN_ENROLLMENT_WINDOW`." PRD
        section 3.2: "Failing both, the calendar General Enrollment Period
        governs during January through March. If none governs, enrollment is
        refused."

        Design: Difficulty/cross_entity_state_dependency/enrollment_creation_depends_on_window_state
        """
        set_clock(client, "2025-07-15T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1960-06-10", full_name="Wendy Window"
        )
        enroll(client, beneficiary, part="PART_B")

        # Clock 2026-06: IEP [2025-03, 2025-09] expired, no SEP, June is not
        # GEP season — a different part changes nothing.
        set_clock(client, "2026-06-10T00:00:00Z")
        response = client.create_enrollment(
            enrollment_payload(beneficiary["id"], "PART_D"),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NO_OPEN_ENROLLMENT_WINDOW)


class TestSwitchToWithholdingDependsOnArrangementState:
    """The DIRECT_BILL -> WITHHOLDING transition opens and closes with the
    arrangement's ACTIVE state."""

    def test_switch_to_withholding_rejected_while_arrangement_suspended(
        self, client
    ):
        """PRD section 3.7: "Switching to `WITHHOLDING` requires the
        enrollment to currently be in `DIRECT_BILL` — a `DELINQUENT`
        enrollment may not switch — and requires the beneficiary to hold an
        `ACTIVE` WithholdingArrangement, otherwise
        `ERR_NO_ACTIVE_WITHHOLDING`."

        Design: Difficulty/cross_entity_state_dependency/switch_to_withholding_depends_on_arrangement_state
        """
        state = setup_withholding_shortfall(client)
        assert state["arrangement"]["status"] == "SUSPENDED"
        assert state["enrollment_b"]["collection_status"] == "DIRECT_BILL"
        arrears = [inv for inv in state["invoices"] if inv["is_arrears"]]
        assert len(arrears) == 1
        assert arrears[0]["part"] == "PART_D"
        assert arrears[0]["amount_cents"] == 950

        response = client.switch_collection_method(
            state["enrollment_b"]["id"],
            switch_collection_method_payload("WITHHOLDING"),
            headers=make_beneficiary_headers(state["beneficiary"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_WITHHOLDING)

    def test_switch_to_withholding_succeeds_after_arrangement_resumes(self, client):
        """PRD section 3.7: "The adjustment resumes a `SUSPENDED` arrangement
        — moving it back to `ACTIVE` — exactly when the new benefit amount
        covers the sum of the current monthly premiums of the beneficiary's
        `ACTIVE` billable (`PART_B` and `PART_D`) enrollments". PRD
        section 3.7: "Resuming does NOT flip any enrollments back to
        `WITHHOLDING`; restoring withholding requires an explicit
        collection-method switch per enrollment."

        Design: Difficulty/cross_entity_state_dependency/switch_to_withholding_depends_on_arrangement_state
        """
        state = setup_withholding_shortfall(client)
        resumed = adjust_arrangement(client, state["arrangement"]["id"], 30000)
        assert resumed["status"] == "ACTIVE", "30000 >= 21950 total premium"

        untouched = state["enrollment_d"]
        assert untouched["collection_status"] == "DIRECT_BILL"

        response = client.switch_collection_method(
            state["enrollment_b"]["id"],
            switch_collection_method_payload("WITHHOLDING"),
            headers=make_beneficiary_headers(state["beneficiary"]["id"]),
        )
        switched = validate_success(response)
        assert switched["collection_status"] == "WITHHOLDING"
