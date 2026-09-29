"""
Identity, role and ownership gates: the same endpoint and the same row, refused
or allowed purely on who is asking, and always in the order the ladder declares.
"""

from test_helpers import (
    ADMIN_HEADERS,
    EVALUATOR_HEADERS,
    FISCAL_2_HEADERS,
    FISCAL_HEADERS,
    INTAKE_HEADERS,
    ROLE_PROVIDER,
    ApiErrorId,
    assert_case_weight,
    assert_ledger,
    build_accrued_visit_case,
    build_active_services,
    build_intake,
    build_plan_with_line,
    build_visit_scheduled,
    create_child,
    create_coordinator,
    create_provider,
    factories,
    headers_without_user_id,
    make_family_representative_headers,
    make_provider_headers,
    make_service_coordinator_headers,
    read_cost_share,
    read_ifsp,
    read_referral,
    read_timeline,
    read_visit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCUMENTATION_CLOCK = "2026-03-25T09:00:00Z"
SESSION_START = "2026-03-24T14:00:00Z"
SESSION_END = "2026-03-24T14:30:00Z"
SECOND_AGENCY = "Northgate Speech Partners"


class TestVisitDocumentationIdentityLadder:

    def test_missing_identity_then_wrong_role_then_wrong_provider(self, api):
        """
        Four calls to the same document endpoint on the same session differ only
        in the caller: an absent `X-User-ID` is 401, a well-formed operator in the
        wrong role is 403 on the role gate, a well-formed provider that holds no
        authorization on the session is 403 on the ownership gate, and only the
        authorized agency succeeds.

        PRD 2.8: "Authentication — `ERR_UNAUTHENTICATED` (401): `X-User-Role` is
        present and names a declared role, and `X-User-ID` is present whenever the
        named role is entity-backed."
        PRD 2.8: "Authorization — `ERR_ROLE_NOT_PERMITTED` (403): the named role
        appears in the target endpoint's authorised role list."
        PRD 3.7: "Only the delivering `Provider` documents a session, and only its
        own: the acting `X-User-ID` must equal the `provider_id` on the session's
        authorization, or the request is refused with `ERR_NOT_RESOURCE_OWNER`."
        PRD 2.8: "No state is written on any failure."
        PRD 3.7: "On success the session moves `SCHEDULED → DELIVERED`;
        `actual_units`, `actual_start`, `actual_end` and `session_note` are stored,
        together with `documented_by_user_id` capturing the acting provider
        identity."

        Design: Corner/rbac/visit_documentation_missing_x_user_then_role_then_owner_ladder
        """
        case = build_visit_scheduled(
            api, scheduled_start=SESSION_START, scheduled_end=SESSION_END
        )
        other_provider_id = create_provider(api, agency_name=SECOND_AGENCY)
        set_clock(api, DOCUMENTATION_CLOCK)
        payload = factories.document_visit_payload(
            actual_units=2, actual_start=SESSION_START, actual_end=SESSION_END
        )

        unauthenticated = api.document_visit(
            case.visit_id, payload, headers_without_user_id(ROLE_PROVIDER)
        )
        validate_error(unauthenticated, ApiErrorId.UNAUTHENTICATED.value, 401)

        wrong_role = api.document_visit(case.visit_id, payload, ADMIN_HEADERS)
        validate_error(wrong_role, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)

        wrong_provider = api.document_visit(
            case.visit_id, payload, make_provider_headers(other_provider_id)
        )
        validate_error(
            wrong_provider, ApiErrorId.NOT_RESOURCE_OWNER.value, 403
        )

        untouched = read_visit(api, case.visit_id)
        assert untouched["visit_status"] == "SCHEDULED"
        assert untouched["actual_units"] is None
        assert untouched["documented_by_user_id"] is None

        delivered = validate_success(
            api.document_visit(
                case.visit_id, payload, make_provider_headers(case.provider_id)
            ),
            200,
        )
        assert delivered["visit_status"] == "DELIVERED"
        assert delivered["documented_by_user_id"] == case.provider_id


# ─── Ownership binds writes, never reads ──────────────────────────────

CONTACT_DATE = "2026-03-20"
EXIT_DATE = "2026-03-20"
EXIT_RATINGS = {
    "exit_rating_social": 4,
    "exit_rating_knowledge": 5,
    "exit_rating_needs": 6,
}
SECOND_COORDINATOR_NAME = "Sam Ortiz"


class TestCoordinatorOwnership:

    def test_a_second_coordinator_may_read_the_case_it_may_not_write(self, api):
        """
        A coordinator who does not hold the case is refused both the monthly
        contact and the case exit on the ownership gate — before any state or
        completeness rule is reached — yet may read that case and its owner's
        caseload numbers, because read access is program-wide.

        PRD 2.2: "Ownership scoping constrains **writes** only. The five staff
        roles — `IntakeSpecialist`, `ProgramAdmin`, `Evaluator`, `FiscalOfficer`, and
        `ServiceCoordinator` — share read access across the entire program, so a
        coordinator may read another coordinator's cases even though they may not
        write to them."
        PRD 2.8: "Ownership — `ERR_NOT_RESOURCE_OWNER` (403), for entity-backed
        roles, on the six write endpoints
        `POST /ei/referrals/{referralId}/contact-logs`,
        `POST /ei/referrals/{referralId}/exit`, `POST /ei/ifsps/{ifspId}/consent`,
        `POST /ei/service-visits/{visitId}/document`, `POST /ei/transition-plans`
        and `POST /ei/transition-plans/{transitionPlanId}/notify-lea`."
        PRD 3.9: "The assigned `ServiceCoordinator` — and only the assigned
        coordinator, since the case's `coordinator_id` must equal the acting
        `X-User-ID` or the request is refused with `ERR_NOT_RESOURCE_OWNER` — logs
        each contact against the case with a `contact_date`, a `contact_method`, a
        `contact_type` and a narrative `summary`."
        PRD 3.9: "The server derives `contact_month` as the year-and-month prefix
        of `contact_date`, and derives `qualifies_for_monthly_requirement` as true
        exactly when the `contact_method` is `HOME_VISIT`, `PHONE` or `VIDEO`."
        PRD 3.2: "A coordinator's `active_case_count` is the number of referrals
        assigned to them whose status is neither `NOT_ELIGIBLE` nor `EXITED`, and
        their `weighted_caseload_points` is the sum of `case_weight_points` over
        exactly that same set of referrals, held to two decimal places rounded half
        up."

        Design: Corner/rbac/coordinator_ownership_restricts_writes_but_never_reads
        """
        case = build_active_services(api)
        other_coordinator_id = create_coordinator(
            api, full_name=SECOND_COORDINATOR_NAME
        )
        intruder_headers = make_service_coordinator_headers(other_coordinator_id)

        contact_refused = api.create_contact_log(
            case.referral_id,
            factories.contact_log_payload(CONTACT_DATE),
            intruder_headers,
        )
        validate_error(
            contact_refused, ApiErrorId.NOT_RESOURCE_OWNER.value, 403
        )
        _, empty_meta = validate_paginated(
            api.list_contact_logs(ADMIN_HEADERS, {"referral_id": case.referral_id})
        )
        assert empty_meta["total_count"] == 0

        exit_refused = api.exit_referral(
            case.referral_id,
            factories.exit_payload(
                EXIT_DATE, exit_reason="REACHED_AGE_THREE", **EXIT_RATINGS
            ),
            intruder_headers,
        )
        validate_error(exit_refused, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)
        assert read_referral(api, case.referral_id)["status"] == "ACTIVE_SERVICES"

        shared_read = validate_success(
            api.get_referral(case.referral_id, intruder_headers), 200
        )
        assert shared_read["coordinator_id"] == case.coordinator_id

        summary = validate_success(
            api.get_caseload_summary(case.coordinator_id, intruder_headers), 200
        )
        assert summary["active_case_count"] == 1
        assert_case_weight(summary["weighted_caseload_points"], 1.00)

        logged = validate_success(
            api.create_contact_log(
                case.referral_id,
                factories.contact_log_payload(CONTACT_DATE),
                case.coordinator_headers,
            ),
            201,
        )
        assert logged["contact_method"] == "HOME_VISIT"
        assert logged["contact_type"] == "MONTHLY_CHECK_IN"
        assert logged["contact_month"] == "2026-03"
        assert logged["qualifies_for_monthly_requirement"] is True


# ─── Segregation of duties keys on the stored identity ────────────────

TIER_2_INCOME_CENTS = 19_470_000
HOUSEHOLD_SIZE = 4
ACCRUED_SHARE_CENTS = 1_300
WAIVE_AMOUNT_CENTS = 650


class TestFiscalSegregationOfDuties:

    def test_the_determining_officer_may_not_waive_its_own_row(self, api):
        """
        Two fiscal officers hold identical permissions, yet the one recorded on the
        determination is refused the waiver while the other is allowed it. A
        non-fiscal role is refused earlier, at the role gate, which is what
        separates the two 403s.

        PRD 2.2: "`FiscalOfficer` owns family cost participation: determining the
        sliding scale, finalizing verified income, recording or withdrawing insurance
        consent, and waiving balances."
        PRD 2.8: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403), on
        `POST /ei/cost-shares/{costShareId}/waive`."
        PRD 3.8: "And the officer recorded in `determined_by_user_id` may not be the
        officer waiving: that attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.8: "On success `family_waived_cents` rises by the waived amount,
        `family_balance_cents` falls by the same amount, the `waiver_reason_code` is
        stored, and `total_assessed_cents` is deliberately left untouched — which is
        exactly how the identity `total_assessed_cents` equals
        `family_balance_cents` plus `family_waived_cents` survives the waiver."

        Design: Corner/rbac/determining_officer_cannot_waive_the_row_they_determined
        """
        case = build_accrued_visit_case(
            api,
            cost_share={
                "household_size": HOUSEHOLD_SIZE,
                "declared_annual_gross_income_cents": TIER_2_INCOME_CENTS,
            },
        )
        waiver = factories.waive_payload(WAIVE_AMOUNT_CENTS)

        own_row = api.waive_cost_share(case.cost_share_id, waiver, FISCAL_HEADERS)
        validate_error(own_row, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        wrong_role = api.waive_cost_share(
            case.cost_share_id,
            factories.waive_payload(
                WAIVE_AMOUNT_CENTS, waiver_reason_code="ADMIN_ERROR"
            ),
            ADMIN_HEADERS,
        )
        validate_error(wrong_role, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
        assert_ledger(
            read_cost_share(api, case.cost_share_id),
            ACCRUED_SHARE_CENTS,
            ACCRUED_SHARE_CENTS,
            0,
        )

        waived = validate_success(
            api.waive_cost_share(case.cost_share_id, waiver, FISCAL_2_HEADERS), 200
        )
        assert_ledger(
            waived,
            ACCRUED_SHARE_CENTS,
            ACCRUED_SHARE_CENTS - WAIVE_AMOUNT_CENTS,
            WAIVE_AMOUNT_CENTS,
        )
        assert waived["waiver_reason_code"] == "HARDSHIP"
        assert waived["month_accrued_cents"] == ACCRUED_SHARE_CENTS


# ─── The family identity is a Child id, and it reads nothing ──────────

SECOND_CHILD = {
    "first_name": "Ben",
    "last_name": "Ito",
    "date_of_birth": "2024-07-02",
}
CONSENT_DATE = "2026-03-20"


class TestFamilyRepresentativeScope:

    def test_another_childs_parent_cannot_consent_and_no_parent_may_read(self, api):
        """
        A second registered child yields a well-formed family identity that is not
        this case's family, so consent is refused on ownership rather than
        authentication; the role holds no read permission at all; and the true
        family's consent activates both the plan and the case.

        PRD 2.2: "When `X-User-Role` is `FamilyRepresentative`, `X-User-ID` is the
        `id` of the acting `Child`; ownership checks compare the referral's
        `child_id` to `X-User-ID`."
        PRD 3.5: "Only a `FamilyRepresentative` records consent, and only for their
        own child: the acting `X-User-ID` must equal the case's `child_id`, or the
        request is refused with `ERR_NOT_RESOURCE_OWNER`."
        PRD 2.2: "`Provider` and `FamilyRepresentative` have no read access under
        `/ei` at all: their sole capabilities are, respectively, documenting their own
        visits and consenting to their own child's plan."
        PRD 3.5: "Consent advances the plan `PENDING_CONSENT → ACTIVE` or, closing
        the amendment cycle, `AMENDMENT_PENDING → ACTIVE`."
        PRD 3.5: "The case transitions `IFSP_PENDING → ACTIVE_SERVICES`, its
        `services_start_date` is set to the plan's `consent_signed_date`, its
        `case_weight_points` is recomputed — the stage base drops from 1.50 to 1.00,
        which usually lowers the coordinator's load even as the case becomes busier —
        the coordinator's aggregates are recomputed after it, and
        `monthly_contact_status` is recomputed for the first time, leaving
        `NOT_APPLICABLE` behind."

        Design: Corner/rbac/family_representative_cannot_consent_for_another_child_or_read_the_plan
        """
        case = build_plan_with_line(api)
        other_child_id = create_child(api, **SECOND_CHILD)
        consent = factories.consent_payload(consent_signed_date=CONSENT_DATE)

        not_this_family = api.record_consent(
            case.ifsp_id, consent, make_family_representative_headers(other_child_id)
        )
        validate_error(
            not_this_family, ApiErrorId.NOT_RESOURCE_OWNER.value, 403
        )
        still_pending = read_ifsp(api, case.ifsp_id)
        assert still_pending["status"] == "PENDING_CONSENT"
        assert still_pending["consent_scope"] is None

        read_refused = api.get_ifsp(case.ifsp_id, case.family_headers)
        validate_error(read_refused, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)

        activated = validate_success(
            api.record_consent(case.ifsp_id, consent, case.family_headers), 200
        )
        assert activated["status"] == "ACTIVE"
        assert activated["consent_signed_date"] == CONSENT_DATE
        referral = read_referral(api, case.referral_id)
        assert referral["status"] == "ACTIVE_SERVICES"
        assert referral["services_start_date"] == CONSENT_DATE


# ─── Every role-exclusive write refuses every other role ──────────────

THIRD_CHILD = {
    "first_name": "Cara",
    "last_name": "Diaz",
    "date_of_birth": "2024-09-09",
}
INTAKE_CONTACT_DATE = "2026-03-02"
CLOCK_ATTEMPT = "2026-03-05T09:00:00Z"


class TestRoleExclusiveWrites:

    def test_seven_exclusive_writes_are_refused_at_the_role_gate(self, api):
        """
        A sweep across five roles' exclusive writes, each attempted by a role that
        is plausible in the domain but not authorised: every call is refused at the
        role gate, ahead of every state rule, and nothing is written — not a row and
        not the logical clock.

        PRD 2.2: "`IntakeSpecialist` is front-door intake staff, and is the only
        role that may register a child or open a referral."
        PRD 2.2: "`Evaluator` is multidisciplinary evaluation staff: scheduling and
        completing assessments, and recording the three entry outcome ratings."
        PRD 2.2: "`ServiceCoordinator` is the assigned coordinator for a case and
        owns that case's monthly contacts, transition planning, the local education
        agency notification, and case exit."
        PRD 2.8: "Authorization — `ERR_ROLE_NOT_PERMITTED` (403): the named role
        appears in the target endpoint's authorised role list."
        PRD 2.8: "When several rules could reject the same request, the service
        evaluates them in a fixed order and reports the **first** violated rule."
        PRD 3.2: "`gross_elapsed_days` is then the whole number of days from
        `referral_received_date`, exclusive, to the stop date, inclusive."

        Design: Corner/rbac/role_exclusive_writes_are_rejected_for_every_other_role
        """
        case = build_intake(api)

        admin_registers_child = api.create_child(
            factories.child_payload(**THIRD_CHILD), ADMIN_HEADERS
        )
        validate_error(
            admin_registers_child, ApiErrorId.ROLE_NOT_PERMITTED.value, 403
        )

        intake_hires_coordinator = api.create_coordinator(
            factories.coordinator_payload(full_name="Sam Ortiz"), INTAKE_HEADERS
        )
        validate_error(
            intake_hires_coordinator, ApiErrorId.ROLE_NOT_PERMITTED.value, 403
        )

        admin_schedules_assessment = api.create_assessment(
            factories.assessment_payload(case.referral_id), ADMIN_HEADERS
        )
        validate_error(
            admin_schedules_assessment, ApiErrorId.ROLE_NOT_PERMITTED.value, 403
        )

        admin_determines_fee = api.create_cost_share(
            factories.cost_share_payload(case.referral_id), ADMIN_HEADERS
        )
        validate_error(
            admin_determines_fee, ApiErrorId.ROLE_NOT_PERMITTED.value, 403
        )

        admin_logs_contact = api.create_contact_log(
            case.referral_id,
            factories.contact_log_payload(
                INTAKE_CONTACT_DATE, contact_method="PHONE"
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            admin_logs_contact, ApiErrorId.ROLE_NOT_PERMITTED.value, 403
        )

        evaluator_registers_provider = api.create_provider(
            factories.provider_payload(), EVALUATOR_HEADERS
        )
        validate_error(
            evaluator_registers_provider,
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

        evaluator_moves_clock = api.set_clock(
            {"current_utc": CLOCK_ATTEMPT}, EVALUATOR_HEADERS
        )
        validate_error(
            evaluator_moves_clock, ApiErrorId.ROLE_NOT_PERMITTED.value, 403
        )

        for lister in (api.list_assessments, api.list_cost_shares):
            _, meta = validate_paginated(
                lister(ADMIN_HEADERS, {"referral_id": case.referral_id})
            )
            assert meta["total_count"] == 0
        _, contact_meta = validate_paginated(
            api.list_contact_logs(ADMIN_HEADERS, {"referral_id": case.referral_id})
        )
        assert contact_meta["total_count"] == 0
        assert read_timeline(api, case.referral_id)["gross_elapsed_days"] == 0
