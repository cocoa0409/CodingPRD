"""Which hats may act, and the four decisions a person may not take alone."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_PENDING,
    APPEAL_STATUS_SUBMITTED,
    APPEAL_STATUS_UPHELD,
    AUTH_STATUS_REQUESTED,
    BASE_SCORE,
    COMPLIANCE_ADMIN,
    COMPLIANCE_ADMIN_2,
    CREDENTIALING_OFFICER,
    CREDENTIAL_TYPE_INFLUENZA,
    ERR_REP_CREDENTIALS_NOT_COMPLIANT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
    INCIDENT_STATUS_SUBSTANTIATED,
    INCIDENT_STATUS_UNDER_INVESTIGATION,
    INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
    LOGICAL_CLOCK_DEFAULT_UTC,
    OR_COORDINATOR,
    OR_COORDINATOR_2,
    OUTCOME_NONE,
    OUTCOME_SUBSTANTIATED,
    PIR_STATUS_VALUE_ANALYSIS_REVIEW,
    POSTURE_INCOMPLETE,
    REQUESTED_ROLE_OBSERVATION,
    SEVERITY_MAJOR,
    TIER_PLATINUM,
    USER_COMPLIANCE_1,
    USER_CREDENTIALING_1,
    USER_ORC_1,
    USER_VAC_1,
    VALUE_ANALYSIS_APPROVER,
    VALUE_ANALYSIS_AS_SPONSOR_1,
    adjudicate_incident,
    adjudicate_payload,
    appeal_decision_payload,
    assert_instant_equals,
    assert_integer_field,
    assert_rep_birth_values,
    assert_total_count,
    authorization_decision_payload,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credential_decision_payload,
    credential_payload,
    decide_value_analysis,
    endorse_pir,
    file_appeal,
    find_by_id,
    get_success_data,
    investigate_incident,
    list_rows,
    list_rows_and_meta,
    make_vendor_admin_headers,
    open_pir,
    read_appeal,
    read_authorization,
    read_incident,
    read_pir,
    read_scorecard,
    read_vendor,
    read_vendor_rep,
    report_incident,
    request_authorization,
    revoke_rep,
    submit_pir,
    validate_error,
    validate_success,
    value_analysis_payload,
    vendor_rep_payload,
)


class TestNarrowRoleListsRefuseEveryOtherHat:
    """An endpoint whose role list is narrower than the eight turns the rest away."""

    def test_or_coordinator_cannot_read_the_vendor_scorecard(self, api):
        """The coordinator is absent from the scorecard's role list and is refused 403.

        The scorecard read is "Restricted to credentialing and compliance staff
        and to the vendor itself", and "Where a narrower set is listed, any
        other role is refused with `ERR_UNAUTHORIZED`" — "If both headers are
        well-formed but the declared role is not among the roles the target
        operation admits, the request is refused with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/or_coordinator_denied_the_vendor_scorecard_returns_403
        """
        vendor = create_vendor(api, "RBSV", legal_name="Rbac Scorecard Devices")

        validate_error(
            api.get_vendor_scorecard(vendor["id"], OR_COORDINATOR),
            ERR_UNAUTHORIZED,
        )

        # Compliance staff read the very same projection without objection.
        card = read_scorecard(api, vendor["id"])
        assert_integer_field(card, "provisional_compliance_score", BASE_SCORE)
        assert card["scorecard_tier"] == TIER_PLATINUM

        # Only the scorecard projection is out of the coordinator's reach: the
        # plain vendor read is open to all eight roles.
        plain = validate_success(api.get_vendor(vendor["id"], OR_COORDINATOR), 200)
        assert plain["id"] == vendor["id"]
        assert_integer_field(plain, "provisional_compliance_score", BASE_SCORE)

    def test_only_the_credentialing_office_may_rule_on_an_attestation(self, api):
        """The vendor that filed the attestation may not verify it itself.

        "A `CredentialingOfficer` then rules on the attestation, supplying a
        `decision` of either `VERIFY` or `REJECT`", and the decide endpoint
        lists that role alone, so "any other role is refused with
        `ERR_UNAUTHORIZED`".

        Design: Corner/rbac/credential_decision_is_exclusive_to_the_credentialing_officer
        """
        vendor = create_vendor(api, "EXCV", legal_name="Exclusive Devices")
        vendor_admin = make_vendor_admin_headers(vendor["id"])
        rep = get_success_data(
            api.create_vendor_rep(
                vendor_rep_payload(
                    vendor["id"], "Elias Exclusive", email="elias@excv.example"
                ),
                vendor_admin,
            ),
            201,
        )
        filed = get_success_data(
            api.create_credential(
                credential_payload(
                    rep["id"],
                    CREDENTIAL_TYPE_INFLUENZA,
                    issued_at_utc="2026-07-01T00:00:00Z",
                    expires_at_utc="2027-07-01T00:00:00Z",
                    document_reference="FLU-EX-01",
                ),
                vendor_admin,
            ),
            201,
        )

        validate_error(
            api.decide_credential(
                filed["id"], credential_decision_payload("VERIFY"), vendor_admin
            ),
            ERR_UNAUTHORIZED,
        )

        # The refused decision left the attestation exactly as the vendor filed it.
        untouched = find_by_id(
            list_rows(api.list_rep_credentials(rep["id"], CREDENTIALING_OFFICER)),
            filed["id"],
        )
        assert untouched["status"] == "PENDING_VERIFICATION"
        assert untouched.get("verified_by_user_id") is None

        # The credentialing office makes the identical call and the flu shot clears.
        verified = validate_success(
            api.decide_credential(
                filed["id"],
                credential_decision_payload("VERIFY"),
                CREDENTIALING_OFFICER,
            ),
            200,
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_CREDENTIALING_1

    def test_the_credentialing_office_cannot_run_the_compliance_sweep(self, api):
        """The sweep is the compliance programme's own lever and no epoch opens without it.

        "A `ComplianceAdmin` administers the vendor compliance programme: it
        investigates and adjudicates incidents, decides appeals, and runs the
        compliance sweep." The sweep endpoint lists that role alone, so "any
        other role is refused with `ERR_UNAUTHORIZED`".

        Design: Corner/rbac/compliance_sweep_denied_to_the_credentialing_officer_returns_403
        """
        vendor = create_vendor(api, "SWPV", legal_name="Sweep Denial Devices")
        assert_integer_field(vendor, "last_sweep_epoch", 0)

        validate_error(
            api.create_compliance_sweep({}, CREDENTIALING_OFFICER),
            ERR_UNAUTHORIZED,
        )

        # No epoch opened: the vendor's sweep-scoped counters stand where enrolment
        # left them, so the refusal really did stop before phase 1.
        stored = read_vendor(api, vendor["id"])
        assert_integer_field(stored, "last_sweep_epoch", 0)
        assert_integer_field(stored, "authorizations_used_epoch", 0)
        assert_integer_field(stored, "access_quota_in_effect", 4)
        assert stored["scorecard_tier"] == TIER_PLATINUM


class TestSharedRoleListsAdmitEveryNamedHat:
    """An endpoint naming two roles writes the same row whichever one calls it."""

    def test_vendor_admin_and_credentialing_officer_both_enrol_a_representative(self, api):
        """Two roster additions by two different roles land in identical birth state.

        Representative registration is open to `VendorAdmin` and
        `CredentialingOfficer` alike, and either way the row "Starts in
        `PENDING_CREDENTIALING` with posture `INCOMPLETE`" — "A freshly
        registered representative is inert".

        Design: Corner/rbac/rep_registration_is_shared_by_vendor_admin_and_credentialing_officer
        """
        vendor = create_vendor(api, "SHRV", legal_name="Shared Devices")

        by_vendor = get_success_data(
            api.create_vendor_rep(
                vendor_rep_payload(vendor["id"], "Sam Shared", email="sam@shrv.example"),
                make_vendor_admin_headers(vendor["id"]),
            ),
            201,
        )
        by_officer = get_success_data(
            api.create_vendor_rep(
                vendor_rep_payload(vendor["id"], "Sara Shared", email="sara@shrv.example"),
                CREDENTIALING_OFFICER,
            ),
            201,
        )

        for rep in (by_vendor, by_officer):
            assert_rep_birth_values(rep)
            assert rep["credential_posture"] == POSTURE_INCOMPLETE
            assert rep["access_status"] == ACCESS_STATUS_PENDING
            assert_integer_field(rep, "open_authorization_count", 0)
            assert rep.get("revoked_at_utc") is None

        rows, meta = list_rows_and_meta(
            api.list_vendor_reps(CREDENTIALING_OFFICER, {"vendor_id": vendor["id"]})
        )
        assert_total_count(meta, 2)
        assert {row["id"] for row in rows} == {by_vendor["id"], by_officer["id"]}


class TestSegregationOfDutiesComparesIdentifiersNotRoles:
    """Four decisions refuse the person who set them up, whatever hat that person wears."""

    def test_the_endorsing_sponsor_cannot_cast_the_value_analysis_vote(self, api):
        """The committee seat is refused to the very user whose endorsement opened it.

        "The value-analysis decision on a product introduction request may not
        be cast by the user recorded as that request's
        `clinical_sponsor_user_id`", and "in all four cases the comparison is on
        `X-User-ID` equality rather than on role names — two different people
        holding the same role satisfy the rule, and one person holding two roles
        does not."

        Design: Corner/rbac/value_analysis_decision_by_the_endorsing_user_returns_403
        """
        facility = create_facility(
            api, "SD-63", name="Segregation Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "SODV", legal_name="Segregation Devices")
        pir = open_pir(
            api,
            vendor["id"],
            facility["id"],
            "SR-1800",
            71000,
            product_name="Segregation Reamer",
            manufacturer="Sodv",
            is_implant=False,
        )
        submit_pir(api, vendor["id"], pir["id"])
        endorsed = endorse_pir(api, pir["id"])
        assert endorsed["status"] == PIR_STATUS_VALUE_ANALYSIS_REVIEW

        # The endorsing surgeon now sits down wearing the committee hat.
        validate_error(
            api.value_analysis_decision(
                pir["id"],
                value_analysis_payload("APPROVE"),
                VALUE_ANALYSIS_AS_SPONSOR_1,
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        waiting = read_pir(api, pir["id"])
        assert waiting["status"] == PIR_STATUS_VALUE_ANALYSIS_REVIEW
        assert waiting.get("value_analysis_user_id") is None

        _rows, meta = list_rows_and_meta(
            api.list_approved_products(
                COMPLIANCE_ADMIN, {"product_introduction_request_id": pir["id"]}
            )
        )
        assert_total_count(meta, 0)

        # A genuinely different committee member casts the identical vote and the
        # implant becomes carriable.
        approved = decide_value_analysis(
            api, pir["id"], "APPROVE", VALUE_ANALYSIS_APPROVER
        )
        assert approved["value_analysis_user_id"] == USER_VAC_1
        minted, minted_meta = list_rows_and_meta(
            api.list_approved_products(
                COMPLIANCE_ADMIN, {"product_introduction_request_id": pir["id"]}
            )
        )
        assert_total_count(minted_meta, 1)
        assert minted[0]["product_catalog_number"] == "SR-1800"

    def test_the_reporting_administrator_cannot_adjudicate_its_own_report(self, api):
        """One compliance administrator may investigate its report but not judge it.

        "The adjudication of an incident may not be performed by the user
        recorded as its `reported_by_user_id`", and the comparison is "on
        `X-User-ID` equality rather than on role names".

        Design: Corner/rbac/incident_adjudication_by_its_reporter_returns_403
        """
        facility = create_facility(
            api, "SI-64", name="Segregation Incident Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "SINCV", legal_name="Segregation Incident Devices")
        rep = create_vendor_rep(api, vendor["id"], "Sid Segregation")
        case = create_case(
            api,
            facility["id"],
            "CASE-15180",
            "2026-09-26T08:00:00Z",
            "2026-09-26T10:00:00Z",
            procedure_name="Segregation Incident Case",
        )
        incident = report_incident(
            api,
            case["id"],
            rep["id"],
            INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
            SEVERITY_MAJOR,
            headers=COMPLIANCE_ADMIN,
            narrative="Implant log sheet left unsigned at the end of the case",
        )
        assert incident["reported_by_user_id"] == USER_COMPLIANCE_1
        investigate_incident(api, incident["id"], COMPLIANCE_ADMIN)

        validate_error(
            api.adjudicate_incident(
                incident["id"],
                adjudicate_payload(OUTCOME_SUBSTANTIATED, "Self-adjudication attempt"),
                COMPLIANCE_ADMIN,
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        stalled = read_incident(api, incident["id"])
        assert stalled["status"] == INCIDENT_STATUS_UNDER_INVESTIGATION
        assert stalled["adjudicated_outcome"] == OUTCOME_NONE
        assert stalled.get("adjudicated_by_user_id") is None

        # Nothing was adjudicated, so only the pessimistic score carries the weight.
        scored = read_vendor(api, vendor["id"])
        assert_integer_field(scored, "provisional_compliance_score", 92)
        assert_integer_field(scored, "adjudicated_compliance_score", BASE_SCORE)

        # A second administrator hears the same file and substantiates it.
        judged = adjudicate_incident(
            api, incident["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN_2
        )
        assert judged["status"] == INCIDENT_STATUS_SUBSTANTIATED
        assert judged["adjudicated_outcome"] == OUTCOME_SUBSTANTIATED

    def test_the_revoking_officer_cannot_decide_the_appeal_against_the_revocation(self, api):
        """The officer who pulled the badge is barred from ruling on the protest.

        "The decision on an access appeal may not be taken by the user recorded
        as the representative's `revoked_by_user_id` — the officer who revoked
        access does not get to rule on the appeal against it."

        Design: Corner/rbac/appeal_decision_by_the_revoking_officer_returns_403
        """
        vendor = create_vendor(api, "SAPV", legal_name="Segregation Appeal Devices")
        rep = create_vendor_rep(api, vendor["id"], "Sky Segregation")
        revoked = revoke_rep(
            api,
            rep["id"],
            CREDENTIALING_OFFICER,
            reason="Background check lapsed while on site",
        )
        assert revoked["revoked_by_user_id"] == USER_CREDENTIALING_1
        assert_instant_equals(
            revoked["revoked_at_utc"], LOGICAL_CLOCK_DEFAULT_UTC, "revoked_at_utc"
        )

        appeal = file_appeal(
            api,
            vendor["id"],
            rep["id"],
            grounds="The renewed background check was already on file",
        )

        validate_error(
            api.decide_access_appeal(
                appeal["id"],
                appeal_decision_payload("UPHOLD", "Deciding my own revocation"),
                CREDENTIALING_OFFICER,
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        pending = read_appeal(api, appeal["id"])
        assert pending["status"] == APPEAL_STATUS_SUBMITTED
        assert pending.get("decided_by_user_id") is None

        # A compliance administrator who took no part in the revocation may rule.
        decided = validate_success(
            api.decide_access_appeal(
                appeal["id"],
                appeal_decision_payload("UPHOLD", "The lapse was properly evidenced"),
                COMPLIANCE_ADMIN,
            ),
            200,
        )
        assert decided["status"] == APPEAL_STATUS_UPHELD
        assert decided["decided_by_user_id"] == USER_COMPLIANCE_1

    def test_the_requesting_coordinator_is_refused_before_the_posture_is_consulted(self, api):
        """The self-decision is refused on duties, ahead of the uncredentialed rep.

        "Segregation of duties — the acting `X-User-ID` differs from the
        counterparty recorded on the same record, else
        `ERR_SEGREGATION_OF_DUTIES` (403)" sits at rung 23 of the ladder, above
        "Credential posture — the representative's recomputed
        `credential_posture` is `COMPLIANT` or `EXPIRING_SOON`" at rung 24, and
        "the first failing rung produces the response."

        Design: Corner/rbac/authorization_decided_by_its_own_requester_returns_403
        """
        facility = create_facility(
            api, "SA-65", name="Segregation Authorization Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(
            api, "SAUTV", legal_name="Segregation Authorization Devices"
        )
        rep = create_vendor_rep(api, vendor["id"], "Sean Segregation")
        case = create_case(
            api,
            facility["id"],
            "CASE-15190",
            "2026-09-28T08:00:00Z",
            "2026-09-28T10:00:00Z",
            procedure_name="Segregation Authorization Case",
        )
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_OBSERVATION,
            headers=OR_COORDINATOR,
        )
        assert requested["requested_by_user_id"] == USER_ORC_1

        validate_error(
            api.decide_authorization(
                requested["id"],
                authorization_decision_payload("APPROVE"),
                OR_COORDINATOR,
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        still_open = read_authorization(api, requested["id"])
        assert still_open["status"] == AUTH_STATUS_REQUESTED
        assert still_open["requested_by_user_id"] == USER_ORC_1
        assert still_open.get("decided_by_user_id") is None

        # The posture rule was never reached, and the rep is indeed uncredentialed.
        untouched_rep = read_vendor_rep(api, rep["id"])
        assert untouched_rep["credential_posture"] == POSTURE_INCOMPLETE
        assert untouched_rep["access_status"] == ACCESS_STATUS_PENDING

        # A colleague clears the duties rung, and only then does the missing
        # attestation surface — which is the ordering itself.
        validate_error(
            api.decide_authorization(
                requested["id"],
                authorization_decision_payload("APPROVE"),
                OR_COORDINATOR_2,
            ),
            ERR_REP_CREDENTIALS_NOT_COMPLIANT,
        )
