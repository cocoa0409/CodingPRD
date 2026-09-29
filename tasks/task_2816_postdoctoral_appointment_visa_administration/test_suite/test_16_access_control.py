"""Role authority, header authenticity and the separations that ride on the user id.

Each of the six declared roles is exercised on an operation only it may perform,
while the read surface and the logical clock are confirmed to be genuinely
shared; the same kind of exclusive operation is then attempted by a role that
does not hold it against identifiers that resolve to nothing, so the role gate
has to answer before any lookup; three different header defects collapse onto a
single authentication code; and the two separations enforced on `X-User-ID`
refuse a request whose role is perfectly well authorised.
"""

from test_helpers import (
    ALL_ROLE_HEADER_KEYS,
    ApiErrorId,
    accept_offer,
    accept_offer_payload,
    activate_appointment,
    all_role_headers,
    api_client,
    assert_money,
    assert_risk_score,
    assert_timestamp_equals,
    clear_pending_screening,
    create_appointment_payload,
    create_lab_access_grant_payload,
    create_postdoc_payload,
    draft_appointment,
    finalize_payload,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    issue_offer,
    make_export_reviewer_headers,
    make_faculty_mentor_headers,
    make_hr_approver_headers,
    make_officer_headers,
    make_postdoc_headers,
    make_scholar_advisor_headers,
    queued_screening_cycle,
    read_appointment,
    recommendation_payload,
    register_faculty_mentor,
    register_funding_source,
    register_laboratory,
    register_postdoc,
    salary_exception_payload,
    screening_decision_payload,
    set_clock,
    submit_petition_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
)

_ASSOCIATE_TERM = {
    "title_classification": "POSTDOC_ASSOCIATE",
    "employment_class": "EMPLOYEE",
    "term_start_date": "2026-10-01",
    "term_end_date": "2027-09-30",
    "annual_salary_usd": 62000.00,
}

_FEDERAL_AWARD = {
    "funding_type": "FEDERAL_GRANT",
    "salary_floor_policy": "NIH_SCALE",
    "award_start_date": "2026-09-01",
    "award_end_date": "2027-12-31",
    "annual_budget_usd": 300000.00,
}

# Nothing below resolves: the role gate must answer before the lookup does.
_NOWHERE_POSTDOC = "00000000-0000-4000-8000-000000000101"
_NOWHERE_MENTOR = "00000000-0000-4000-8000-000000000102"
_NOWHERE_AWARD = "00000000-0000-4000-8000-000000000103"
_NOWHERE_AWARD_TO_VERIFY = "00000000-0000-4000-8000-000000000104"
_NOWHERE_APPOINTMENT = "00000000-0000-4000-8000-000000000105"
_NOWHERE_LABORATORY = "00000000-0000-4000-8000-000000000106"
_NOWHERE_VISA_CASE = "00000000-0000-4000-8000-000000000107"
_NOWHERE_SCREENING = "00000000-0000-4000-8000-000000000108"

_STARTUP_CLOCK = "2026-08-01T00:00:00Z"


def test_every_role_reaches_its_own_exclusive_operation_and_the_shared_read_surface():
    """One lifecycle in which each of the six roles does the thing only it may do.

    PRD 2.1: "A `PostdocAffairsOfficer` maintains the registries, drafts
    appointments, issues offers, activates and withdraws them, reviews development
    documents, opens and finalizes reappointment reviews, resolves grievances, and
    initiates exit processing."

    PRD 2.1: "Read access is deliberately broad: every listed retrieval operation,
    and the logical-clock capability described in section 2.4, is available to all
    six roles."

    PRD 3.6: "A created grant starts with `status` `PROVISIONED`, a
    `suspension_reason` of `NONE`, and `requested_by_user_id` stamped with the
    requesting mentor's `X-User-ID`."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_operations_and_the_shared_read_surface
    """
    officer = make_officer_headers("officer-pa-69")
    approver = make_hr_approver_headers("hr-approver-24")
    reviewer = make_export_reviewer_headers("export-reviewer-24")
    advisor = make_scholar_advisor_headers("scholar-advisor-9")

    scholar = register_postdoc(
        officer, full_name="Gita Ramaswamy", email="gita.r@example.edu",
        citizenship_country="IN", requires_sponsorship=True,
        phd_award_date="2026-07-04",
    )
    # PRD 3.1 seeds a freshly registered scholar at PROSPECTIVE; only activation
    # advances the person's own record, and this appointment never activates.
    assert scholar["status"] == "PROSPECTIVE", (
        f"A newly registered scholar is PROSPECTIVE, got {scholar['status']}"
    )
    mentor = register_faculty_mentor(
        officer, full_name="C. Nkosi", department="Neuroscience",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        verify=False, headers=officer, sponsor_name="NINDS-6900",
        funding_type="FEDERAL_GRANT", salary_floor_policy="NIH_SCALE",
        award_start_date="2026-09-01", award_end_date="2028-12-31",
        annual_budget_usd=300000.00,
    )
    laboratory = register_laboratory(
        officer, name="Neuro BSL1 Bay", biosafety_level="BSL1", bench_capacity=10,
    )

    mentor_headers = make_faculty_mentor_headers(mentor["id"])
    scholar_headers = make_postdoc_headers(scholar["id"])

    # The compensation approver owns award verification, and nobody else does.
    verified = validate_success(
        api_client.verify_funding_source(
            award["id"], verification_payload("VERIFY"), approver
        )
    )
    assert verified["verification_status"] == "VERIFIED", (
        f"Expected VERIFIED, got {verified['verification_status']}"
    )
    assert verified["verified_by_user_id"] == "hr-approver-24", (
        f"Expected the approver's own id, got {verified['verified_by_user_id']}"
    )

    # The officer drafts and issues.
    appointment = validate_success(
        api_client.create_appointment(
            create_appointment_payload(
                scholar["id"], mentor["id"], award["id"], **_ASSOCIATE_TERM
            ),
            officer,
        ),
        expected_status=201,
    )
    issued = validate_success(api_client.issue_offer(appointment["id"], officer))
    assert issued["appointment_status"] == "OFFER_ISSUED", (
        f"Expected OFFER_ISSUED, got {issued['appointment_status']}"
    )

    # The scholar accepts on their own behalf.
    accepted = validate_success(
        api_client.accept_offer(
            appointment["id"], scholar_headers, accept_offer_payload("STANDARD")
        )
    )
    assert accepted["appointment_status"] == "OFFER_ACCEPTED", (
        f"Expected OFFER_ACCEPTED, got {accepted['appointment_status']}"
    )

    # The clock is shared: a reviewer who owns none of this data may move it.
    validate_success(api_client.set_clock("2026-08-10T00:00:00Z", reviewer))

    # The advisor owns petition filing.
    cases, case_meta = validate_paginated(
        api_client.list_visa_cases_for_appointment(appointment["id"], advisor)
    )
    assert case_meta["total_count"] == 1, (
        f"A sponsored acceptance creates exactly one case, got "
        f"{case_meta['total_count']}"
    )
    filed = validate_success(
        api_client.submit_petition(
            cases[0]["id"], advisor, submit_petition_payload("STANDARD")
        )
    )
    assert filed["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {filed['status']}"
    )
    assert filed["visa_category"] == "J1_RESEARCH_SCHOLAR", (
        f"No bar and no endorsement selects J1_RESEARCH_SCHOLAR, got "
        f"{filed['visa_category']}"
    )
    assert_timestamp_equals(
        filed["filed_at"], "2026-08-10T00:00:00Z", "filed_at"
    )
    assert filed["projected_decision_date"] == "2026-08-31", (
        f"21 STANDARD days from 2026-08-10 is 2026-08-31, got "
        f"{filed['projected_decision_date']}"
    )
    assert filed["earliest_lawful_start_date"] == "2026-09-10", (
        f"10 further lead days give 2026-09-10, got "
        f"{filed['earliest_lawful_start_date']}"
    )

    # The export-control reviewer owns the screening decision.
    cycle = queued_screening_cycle(appointment["id"], reviewer)
    decided = validate_success(
        api_client.decide_export_control_review(
            cycle["id"], screening_decision_payload(False, False), reviewer
        )
    )
    assert decided["screening_tier"] == "TIER_1_STANDARD", (
        f"A first cycle with no findings is TIER_1_STANDARD, got "
        f"{decided['screening_tier']}"
    )
    assert_risk_score(decided["risk_score"], 25.0)
    assert decided["status"] == "CLEARED", (
        f"Expected CLEARED, got {decided['status']}"
    )
    assert decided["reviewer_user_id"] == "export-reviewer-24", (
        f"Expected the reviewer's own id, got {decided['reviewer_user_id']}"
    )

    # The mentor owns the bench request, and reads the version they must carry.
    seen_by_mentor = validate_success(
        api_client.get_appointment(appointment["id"], mentor_headers)
    )
    assert seen_by_mentor["compliance_status"] == "CLEARED", (
        f"Expected CLEARED, got {seen_by_mentor['compliance_status']}"
    )
    grant = validate_success(
        api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment["id"], laboratory["id"], seen_by_mentor["version"],
                bench_seats=2, access_start_date="2026-10-01",
                access_end_date="2027-09-30",
            ),
            mentor_headers,
        ),
        expected_status=201,
    )
    assert grant["status"] == "PROVISIONED", (
        f"Expected PROVISIONED, got {grant['status']}"
    )
    assert grant["suspension_reason"] == "NONE", (
        f"Expected NONE, got {grant['suspension_reason']}"
    )
    assert grant["bench_seats"] == 2, (
        f"A CLEARED posture allows two seats, got {grant['bench_seats']}"
    )
    assert grant["requested_by_user_id"] == mentor["id"], (
        f"Expected the requesting mentor's id, got {grant['requested_by_user_id']}"
    )

    # The read surface is shared: the same row answers all six roles.
    readers = all_role_headers(mentor_id=mentor["id"], postdoc_id=scholar["id"])
    assert sorted(readers) == sorted(ALL_ROLE_HEADER_KEYS), (
        f"Expected all six declared roles, got {sorted(readers)}"
    )
    for role, headers in readers.items():
        row = validate_success(api_client.get_appointment(appointment["id"], headers))
        assert row["id"] == appointment["id"], (
            f"{role} read a different appointment: {row['id']}"
        )
        assert row["appointment_status"] == "OFFER_ACCEPTED", (
            f"{role} saw {row['appointment_status']} rather than OFFER_ACCEPTED"
        )


def test_one_roles_exclusive_operation_cannot_be_reached_by_any_other_role():
    """The role gate answers first, so nothing in these paths needs to exist.

    PRD 2.1: "If the headers are well formed but the acting role is not among the
    roles authorised for the requested operation, the rejection is
    `ERR_FORBIDDEN_ROLE` (403)."

    PRD 2.11 rule 2: "Role authorisation: the acting role appears in the
    operation's authorised list — `ERR_FORBIDDEN_ROLE` (403), on every operation."

    PRD 2.11 rule 3: "Existence of every referenced identifier, path identifiers
    first in path order and then body foreign keys in declaration order — the
    entity-specific 404 codes listed in section 2.7, on every operation that
    carries a path identifier or a foreign-key body field."

    Design: Corner/rbac/one_roles_exclusive_operation_cannot_be_reached_by_any_other_role
    """
    officer = make_officer_headers("officer-pa-70")
    approver = make_hr_approver_headers("hr-approver-25")
    reviewer = make_export_reviewer_headers("export-reviewer-25")
    advisor = make_scholar_advisor_headers("scholar-advisor-10")

    # Each row is one role's exclusive operation attempted by a role without it.
    attempts = [
        (
            "drafting as the compensation approver",
            api_client.create_appointment(
                create_appointment_payload(
                    _NOWHERE_POSTDOC, _NOWHERE_MENTOR, _NOWHERE_AWARD,
                    **_ASSOCIATE_TERM
                ),
                approver,
            ),
        ),
        (
            "award verification as the officer",
            api_client.verify_funding_source(
                _NOWHERE_AWARD_TO_VERIFY, verification_payload("VERIFY"), officer
            ),
        ),
        (
            "activation as the mentor",
            api_client.activate_appointment(
                _NOWHERE_APPOINTMENT, make_faculty_mentor_headers(_NOWHERE_MENTOR)
            ),
        ),
        (
            "a bench request as the scholar",
            api_client.create_lab_access_grant(
                create_lab_access_grant_payload(
                    _NOWHERE_APPOINTMENT, _NOWHERE_LABORATORY
                ),
                make_postdoc_headers(_NOWHERE_POSTDOC),
            ),
        ),
        (
            "petition filing as the export-control reviewer",
            api_client.submit_petition(
                _NOWHERE_VISA_CASE, reviewer, submit_petition_payload("STANDARD")
            ),
        ),
        (
            "a screening decision as the scholar advisor",
            api_client.decide_export_control_review(
                _NOWHERE_SCREENING, screening_decision_payload(False, False), advisor
            ),
        ),
        (
            "offer acceptance as the officer",
            api_client.accept_offer(
                _NOWHERE_APPOINTMENT, officer, accept_offer_payload("STANDARD")
            ),
        ),
    ]

    for label, response in attempts:
        reported = validate_error(
            response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403
        )
        assert reported["error_id"] == ApiErrorId.ERR_FORBIDDEN_ROLE.value, (
            f"{label} must report ERR_FORBIDDEN_ROLE rather than leaking a 404, "
            f"got {reported['error_id']}"
        )

    # A refused request writes nothing, and no cascade child can exist either
    # because no appointment was ever created to own one.
    _, appointment_meta = validate_paginated(api_client.list_appointments(officer))
    assert appointment_meta["total_count"] == 0, (
        f"No appointment may survive the seven refusals, got "
        f"{appointment_meta['total_count']}"
    )
    _, grant_meta = validate_paginated(api_client.list_lab_access_grants(officer))
    assert grant_meta["total_count"] == 0, (
        f"No bench-access grant may survive the seven refusals, got "
        f"{grant_meta['total_count']}"
    )


def test_a_missing_or_undeclared_role_header_is_unauthenticated_before_the_role_gate():
    """Three header defects, one code, and no trace left behind by any of them.

    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of those
    six strings, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

    PRD 2.11 rule 1: "Authentication: both headers present and `X-User-Role` one of
    the six declared roles — `ERR_UNAUTHENTICATED` (401), on every operation."

    PRD 2.4: "Every stamped instant in the system — `verified_at`, `filed_at`,
    `decided_at`, `approved_at`, `notice_issued_at`, `initiated_at`,
    `ip_assignment_signed_at`, and the `filed_at` of a grievance — is the logical
    clock's value at the moment of the write, and every deadline comparison (award
    expiry, grievance window, notice timeliness) is made against the same source."

    Design: Corner/rbac/a_missing_or_undeclared_role_header_is_unauthenticated_before_the_role_gate
    """
    probes = [
        (
            "a read with no role header",
            api_client.raw(
                "GET", "/appointments",
                headers=headers_without_role("officer-pa-70"),
            ),
        ),
        (
            "a read with no user id header",
            api_client.raw(
                "GET", "/appointments",
                headers=headers_without_user_id("PostdocAffairsOfficer"),
            ),
        ),
        (
            "a write carrying an undeclared role",
            api_client.raw(
                "POST", "/postdocs",
                create_postdoc_payload(
                    full_name="Header Probe", email="header.probe@example.edu",
                    citizenship_country="US", requires_sponsorship=False,
                    phd_award_date="2026-07-05",
                ),
                headers_with_undeclared_role("registrar-1", "Registrar"),
            ),
        ),
        (
            "a clock advance with no role header",
            api_client.raw(
                "POST", "/_clock/set_current_utc",
                {"current_utc": "2026-09-01T00:00:00Z"},
                headers_without_role("officer-pa-70"),
            ),
        ),
    ]

    for label, response in probes:
        reported = validate_error(
            response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401
        )
        assert reported["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value, (
            f"{label} must report ERR_UNAUTHENTICATED and never ERR_FORBIDDEN_ROLE, "
            f"got {reported['error_id']}"
        )

    officer = make_officer_headers("officer-pa-70")
    approver = make_hr_approver_headers("hr-approver-25")

    # The undeclared-role write never reached the uniqueness check, so the email
    # it carried is still free.
    replayed = validate_success(
        api_client.create_postdoc(
            create_postdoc_payload(
                full_name="Header Probe", email="header.probe@example.edu",
                citizenship_country="US", requires_sponsorship=False,
                phd_award_date="2026-07-05",
            ),
            officer,
        ),
        expected_status=201,
    )
    assert replayed["email"] == "header.probe@example.edu", (
        f"Expected the probe email to be free, got {replayed['email']}"
    )

    # The refused clock advance never landed: the next stamped instant is still
    # the startup value rather than 2026-09-01.
    award = register_funding_source(
        verify=False, headers=officer, sponsor_name="NIA-7000", **_FEDERAL_AWARD
    )
    verified = validate_success(
        api_client.verify_funding_source(
            award["id"], verification_payload("VERIFY"), approver
        )
    )
    assert_timestamp_equals(verified["verified_at"], _STARTUP_CLOCK, "verified_at")


def test_the_same_user_id_cannot_prepare_and_price_or_recommend_and_finalize():
    """Two separations enforced on the user id, each refused under an allowed role.

    PRD 2.10: "Four separations are enforced, all of them on `X-User-ID` rather
    than on `X-User-Role`, because in each case both parties hold the same role."

    PRD 2.10: "The `HRCompensationApprover` who approves a salary-minimum exception
    must not be the appointment's `prepared_by_user_id`."

    PRD 3.8: "Finalization is a `PostdocAffairsOfficer`'s action carrying a
    `decision` of `RENEW` or `NON_RENEW`, and the officer may not be the same
    person recorded in `recommended_by_user_id`."

    PRD 2.11 rule 23: "Segregation of duties as set out in section 2.10 —
    `ERR_SEGREGATION_OF_DUTIES` (403), on salary-exception approval, reappointment
    finalization, grievance resolution and screening decisions."

    Design: Corner/rbac/the_same_user_id_cannot_prepare_and_price_or_recommend_and_finalize
    """
    officer = make_officer_headers("officer-pa-71")
    approver = make_hr_approver_headers("hr-approver-26")
    reviewer = make_export_reviewer_headers("export-reviewer-26")

    mentor = register_faculty_mentor(
        officer, full_name="D. Sorensen", department="Genetics",
        mentor_training_valid_through="2029-12-31",
    )
    award = register_funding_source(
        headers=officer, approver_headers=approver, sponsor_name="NHGRI-7100",
        **_FEDERAL_AWARD,
    )
    scholar = register_postdoc(
        officer, full_name="Hana Yildiz", email="hana.y@example.edu",
        citizenship_country="US", requires_sponsorship=False,
        phd_award_date="2026-07-06",
    )
    appointment = draft_appointment(
        scholar["id"], mentor["id"], award["id"], officer, **_ASSOCIATE_TERM
    )
    assert appointment["prepared_by_user_id"] == "officer-pa-71", (
        f"Expected the drafting officer's id, got "
        f"{appointment['prepared_by_user_id']}"
    )
    assert_money(appointment["salary_floor_usd"], 61008.00, "salary_floor_usd")
    drafted_version = appointment["version"]

    # The preparer wearing the approver's role is still the preparer.
    self_approval = api_client.approve_salary_exception(
        appointment["id"],
        salary_exception_payload(
            drafted_version, 60000.00, "Self-approval attempt by the preparer."
        ),
        make_hr_approver_headers("officer-pa-71"),
    )
    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    after_refusal = read_appointment(appointment["id"], approver)
    assert after_refusal["salary_exception_floor_usd"] is None, (
        f"The refusal must write no floor, got "
        f"{after_refusal['salary_exception_floor_usd']}"
    )
    assert after_refusal["version"] == drafted_version, (
        f"A 403 must not bump the version: expected {drafted_version}, got "
        f"{after_refusal['version']}"
    )

    # An independent approver carrying the same still-live version succeeds.
    priced = validate_success(
        api_client.approve_salary_exception(
            appointment["id"],
            salary_exception_payload(
                after_refusal["version"], 60000.00,
                "Approved by an independent compensation analyst.",
            ),
            approver,
        )
    )
    assert_money(
        priced["salary_exception_floor_usd"], 60000.00, "salary_exception_floor_usd"
    )
    assert priced["salary_exception_approved_by_user_id"] == "hr-approver-26", (
        f"Expected the independent approver's id, got "
        f"{priced['salary_exception_approved_by_user_id']}"
    )
    assert priced["version"] == drafted_version + 1, (
        f"The accepted exception moves the version by one: expected "
        f"{drafted_version + 1}, got {priced['version']}"
    )

    issue_offer(appointment["id"], officer)
    accept_offer(appointment["id"], scholar["id"])
    clear_pending_screening(appointment["id"], headers=reviewer)
    activate_appointment(appointment["id"], officer)

    set_clock("2027-05-01T10:00:00Z", officer)
    review = validate_success(
        api_client.open_reappointment_review(appointment["id"], officer),
        expected_status=201,
    )
    recommended = validate_success(
        api_client.record_recommendation(
            review["id"],
            recommendation_payload(
                "RENEW", "Productive year; renewal recommended."
            ),
            make_faculty_mentor_headers(mentor["id"]),
        )
    )
    assert recommended["status"] == "RECOMMENDED_RENEW", (
        f"Expected RECOMMENDED_RENEW, got {recommended['status']}"
    )
    assert recommended["recommended_by_user_id"] == mentor["id"], (
        f"Expected the recommending mentor's id, got "
        f"{recommended['recommended_by_user_id']}"
    )

    version_before_finalize = read_appointment(appointment["id"], officer)["version"]

    # The officer's role is authorised; the user id is the recommender's.
    refused_finalize = api_client.finalize_reappointment_review(
        review["id"], finalize_payload("RENEW"), make_officer_headers(mentor["id"])
    )
    validate_error(refused_finalize, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    mid = validate_success(
        api_client.get_reappointment_review(review["id"], officer)
    )
    assert mid["status"] == "RECOMMENDED_RENEW", (
        f"The refusal must leave the review at RECOMMENDED_RENEW, got "
        f"{mid['status']}"
    )
    assert mid["finalized_by_user_id"] is None, (
        f"The refusal must stamp nobody, got {mid['finalized_by_user_id']}"
    )
    assert read_appointment(appointment["id"], officer)["version"] == (
        version_before_finalize
    ), "A refused finalization must not bump the appointment version"

    finalized = validate_success(
        api_client.finalize_reappointment_review(
            review["id"], finalize_payload("RENEW"), officer
        )
    )
    assert finalized["status"] == "FINALIZED_RENEWED", (
        f"Expected FINALIZED_RENEWED, got {finalized['status']}"
    )
    assert finalized["finalized_by_user_id"] == "officer-pa-71", (
        f"Expected the finalizing officer's id, got "
        f"{finalized['finalized_by_user_id']}"
    )
