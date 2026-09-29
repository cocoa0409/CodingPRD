"""Refusals that name one error and leave the hospital's records exactly as they were."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    ACCESS_STATUS_PENDING,
    ACCESS_STATUS_REVOKED,
    APPEAL_STATUS_UPHELD,
    AUTH_STATUS_APPROVED,
    AUTH_STATUS_REQUESTED,
    BADGE_STATUS_ISSUED,
    CASE_STATUS_CANCELLED,
    COMPLEXITY_IMPLANT_SPECIALTY,
    COMPLEXITY_SIMPLE,
    ERR_APPEAL_INVALID_STATE,
    ERR_BADGE_WINDOW_NOT_OPEN,
    ERR_CASE_NOT_SCHEDULED,
    ERR_INCIDENT_INVALID_STATE,
    ERR_PIR_INVALID_STATE,
    ERR_REP_CREDENTIALS_NOT_COMPLIANT,
    ERR_REP_NOT_REVOKED,
    ERR_UNAUTHENTICATED,
    ERR_VENDOR_FEE_HOLD,
    ERR_VENDOR_SCOPE_VIOLATION,
    FEE_HOLD_THRESHOLD_CENTS,
    FEE_STATUS_ASSESSED,
    FEE_STATUS_NONE,
    INCIDENT_STATUS_UNDER_INVESTIGATION,
    INCIDENT_TYPE_UNBADGED_ACCESS,
    LOANER_STATUS_DELIVERED_ON_TIME,
    LOANER_STATUS_REJECTED_LATE,
    OUTCOME_NONE,
    PIR_STATUS_CLINICAL_REVIEW,
    PIR_STATUS_DRAFT,
    POSTURE_COMPLIANT,
    POSTURE_INCOMPLETE,
    READINESS_NOT_APPLICABLE,
    REQUESTED_ROLE_OBSERVATION,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    SEVERITY_MINOR,
    COMPLIANCE_ADMIN,
    CREDENTIALING_OFFICER,
    NO_IDENTITY_HEADERS,
    OR_COORDINATOR,
    STERILE_PROCESSING_TECH,
    access_appeal_payload,
    appeal_decision_payload,
    approved_authorization,
    approved_product,
    assert_instant_equals,
    assert_instant_is_none,
    assert_integer_field,
    assert_money_cents,
    assert_total_count,
    authorization_decision_payload,
    cancel_payload,
    check_in,
    check_in_payload,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credentialed_rep,
    facility_payload,
    file_appeal,
    get_success_data,
    investigate_incident,
    list_rows_and_meta,
    make_vendor_admin_headers,
    make_vendor_rep_headers,
    open_pir,
    read_appeal,
    read_authorization,
    read_case,
    read_incident,
    read_loaner_set,
    read_pir,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    report_incident,
    request_authorization,
    reschedule_payload,
    revoke_rep,
    set_clock,
    submit_pir,
    validate_error,
    validate_success,
)


class TestIdentityAndScopeRefusals:
    """Who the caller is, and which vendor's paperwork the caller may touch."""

    def test_a_facility_registration_without_identity_headers_is_refused_401(self, api):
        """An anonymous caller is turned away before the perfectly good payload is read.

        "Every request must carry `X-User-ID`, identifying the acting principal,
        and `X-User-Role`, declaring the capacity in which that principal is
        acting. If either header is absent ... the request is refused with
        `ERR_UNAUTHENTICATED` (HTTP 401)." Authentication is the first rung of
        the ladder, so the well-formed body never gets a hearing.

        Design: Corner/errors/missing_identity_headers_returns_401
        """
        body = facility_payload(
            "AN-55",
            name="Anonymous Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )

        validate_error(api.create_facility(body, NO_IDENTITY_HEADERS), ERR_UNAUTHENTICATED)

        # The very same body, sent by a named credentialing officer, is accepted:
        # nothing about the facility description was wrong.
        registered = get_success_data(
            api.create_facility(body, CREDENTIALING_OFFICER), 201
        )
        assert registered["code"] == "AN-55"
        assert registered["name"] == "Anonymous Hospital"

    def test_submitting_a_sibling_vendors_request_is_refused_403(self, api):
        """A real vendor administrator still may not push another company's request forward.

        "A `VendorAdmin` may act only on rows belonging to its own vendor,
        meaning `X-User-ID` must equal the `Vendor` identifier reached through
        the target resource's `vendor_id` ... A violation is refused with
        `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403). This scope check guards exactly
        seven operations: opening a product introduction request, submitting
        one, ..."

        Design: Corner/errors/submitting_another_vendors_request_returns_403
        """
        facility = create_facility(
            api, "VS-57", name="Vendor Scope Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        owning = create_vendor(api, "OWNV", legal_name="Owning Devices")
        other = create_vendor(api, "OTHV", legal_name="Other Devices")
        request = open_pir(
            api,
            owning["id"],
            facility["id"],
            "OC-1500",
            47000,
            is_implant=False,
            product_name="Owned Cutting Block",
            manufacturer="Ownv",
        )

        validate_error(
            api.submit_pir(request["id"], {}, make_vendor_admin_headers(other["id"])),
            ERR_VENDOR_SCOPE_VIOLATION,
        )

        untouched = read_pir(api, request["id"])
        assert untouched["status"] == PIR_STATUS_DRAFT
        assert_integer_field(untouched, "revision_round", 0)

        # The owning vendor's identical submission is admitted.
        submitted = submit_pir(api, owning["id"], request["id"])
        assert submitted["status"] == PIR_STATUS_CLINICAL_REVIEW


class TestStateMachineRefusals:
    """Second bites at one-shot transitions, and transitions out of terminal states."""

    def test_an_appeal_for_a_rep_who_was_never_revoked_is_refused_409(self, api):
        """A pre-emptive appeal has no revocation to contest, so the filing is refused.

        "The representative's `access_status` must currently be `REVOKED`; a
        suspended or credentialed representative has nothing to appeal, and the
        attempt is refused with `ERR_REP_NOT_REVOKED`."

        Design: Corner/errors/appeal_for_a_rep_that_is_not_revoked_returns_409
        """
        vendor = create_vendor(api, "NRV", legal_name="Not Revoked Devices")
        rep = create_vendor_rep(api, vendor["id"], "Nick NotRevoked")

        validate_error(
            api.create_access_appeal(
                access_appeal_payload(
                    rep["id"],
                    grounds=(
                        "Pre-emptive appeal against a revocation that has not happened"
                    ),
                ),
                make_vendor_admin_headers(vendor["id"]),
            ),
            ERR_REP_NOT_REVOKED,
        )

        _appeals, meta = list_rows_and_meta(
            api.list_rep_access_appeals(rep["id"], COMPLIANCE_ADMIN)
        )
        assert_total_count(meta, 0)

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_PENDING
        assert_instant_is_none(stored_rep, "revoked_at_utc")

    def test_a_second_investigation_on_the_same_incident_is_refused_409(self, api):
        """Once the file is open, opening it again is refused and the first stamps stand.

        "A `ComplianceAdmin` may open an investigation on a `REPORTED` incident,
        moving it `REPORTED → UNDER_INVESTIGATION`", and the ladder holds that
        "investigating requires `REPORTED` ... else `ERR_INCIDENT_INVALID_STATE`
        (409)".

        Design: Corner/errors/second_investigate_on_the_same_incident_returns_409
        """
        facility = create_facility(
            api, "IN-58", name="Incident State Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "INCV", legal_name="Incident State Devices")
        rep = create_vendor_rep(api, vendor["id"], "Ivan Incident")
        case = create_case(
            api,
            facility["id"],
            "CASE-15140",
            "2026-09-18T08:00:00Z",
            "2026-09-18T10:00:00Z",
            procedure_name="Incident State Case",
        )
        incident = report_incident(
            api,
            case["id"],
            rep["id"],
            INCIDENT_TYPE_UNBADGED_ACCESS,
            SEVERITY_MINOR,
            headers=OR_COORDINATOR,
            narrative="Rep entered the sub-sterile corridor ahead of the escort",
        )
        investigate_incident(api, incident["id"], COMPLIANCE_ADMIN)

        validate_error(
            api.investigate_incident(incident["id"], {}, COMPLIANCE_ADMIN),
            ERR_INCIDENT_INVALID_STATE,
        )

        stored = read_incident(api, incident["id"])
        assert stored["status"] == INCIDENT_STATUS_UNDER_INVESTIGATION
        assert stored["adjudicated_outcome"] == OUTCOME_NONE

        # An open MINOR finding counts only in the pessimistic variant.
        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "provisional_compliance_score", 97)
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 100)

    def test_rescheduling_a_cancelled_case_is_refused_409(self, api):
        """A cancellation cannot be undone by re-timing the theatre slot.

        "Cancellation is terminal", and rescheduling "is admissible only while
        the case is `SCHEDULED` or `RESCHEDULED`", so a `CANCELLED` case trips
        the rung that answers "the case is in `SCHEDULED` or `RESCHEDULED`, else
        `ERR_CASE_NOT_SCHEDULED` (409)".

        Design: Corner/errors/reschedule_of_a_cancelled_case_returns_409
        """
        facility = create_facility(
            api, "CX-59", name="Cancelled Case Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-15150",
            "2026-09-22T08:00:00Z",
            "2026-09-22T10:00:00Z",
            procedure_name="Cancelled Case",
        )
        validate_success(
            api.cancel_surgical_case(
                case["id"],
                cancel_payload("Patient deferred the procedure"),
                OR_COORDINATOR,
            ),
            200,
        )

        validate_error(
            api.reschedule_surgical_case(
                case["id"],
                reschedule_payload("2026-09-24T08:00:00Z", "2026-09-24T10:00:00Z"),
                OR_COORDINATOR,
            ),
            ERR_CASE_NOT_SCHEDULED,
        )

        stored = read_case(api, case["id"])
        assert stored["status"] == CASE_STATUS_CANCELLED
        assert_instant_equals(
            stored["scheduled_start_utc"], "2026-09-22T08:00:00Z", "scheduled_start_utc"
        )
        assert_integer_field(stored, "reschedule_count", 0)

    def test_a_second_submission_of_the_same_request_is_refused_409(self, api):
        """The request is already in front of the clinical sponsor, and is not counted twice.

        "From `DRAFT` it advances `DRAFT → CLINICAL_REVIEW`, increments the
        vendor's `open_pir_count`", and the ladder admits a submission only from
        "`DRAFT` or `CHANGES_REQUESTED` ... else `ERR_PIR_INVALID_STATE` (409)".

        Design: Corner/errors/second_submit_of_the_same_request_returns_409
        """
        facility = create_facility(
            api, "PS-60", name="Pir State Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "PIRSV", legal_name="Pir State Devices")
        request = open_pir(
            api,
            vendor["id"],
            facility["id"],
            "PS-1600",
            26000,
            is_implant=False,
            product_name="Pir State Screw Caddy",
            manufacturer="Pirsv",
        )
        submit_pir(api, vendor["id"], request["id"])

        validate_error(
            api.submit_pir(
                request["id"], {}, make_vendor_admin_headers(vendor["id"])
            ),
            ERR_PIR_INVALID_STATE,
        )

        stored = read_pir(api, request["id"])
        assert stored["status"] == PIR_STATUS_CLINICAL_REVIEW
        assert_integer_field(stored, "revision_round", 0)

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "open_pir_count", 1)

    def test_a_second_decision_on_a_decided_appeal_is_refused_409(self, api):
        """An upheld appeal cannot be reopened and overturned on a second look.

        "Only a `SUBMITTED` appeal may be decided; both `UPHELD` and
        `OVERTURNED` are terminal, and a second decision on an already-decided
        appeal is refused with `ERR_APPEAL_INVALID_STATE`."

        Design: Corner/errors/second_decision_on_a_decided_appeal_returns_409
        """
        vendor = create_vendor(api, "APSV", legal_name="Appeal State Devices")
        rep = create_vendor_rep(api, vendor["id"], "Ann Appeal")
        revoke_rep(
            api,
            rep["id"],
            COMPLIANCE_ADMIN,
            reason="Unapproved product opened on the sterile field",
        )
        appeal = file_appeal(
            api,
            vendor["id"],
            rep["id"],
            grounds="The product had been approved at a sister facility",
        )
        rationale = "The sister-facility approval does not extend to this hospital"
        # The revoking administrator is not the decider, so segregation of duties holds.
        validate_success(
            api.decide_access_appeal(
                appeal["id"],
                appeal_decision_payload("UPHOLD", rationale),
                CREDENTIALING_OFFICER,
            ),
            200,
        )

        validate_error(
            api.decide_access_appeal(
                appeal["id"],
                appeal_decision_payload("OVERTURN", "Second look at the same record"),
                CREDENTIALING_OFFICER,
            ),
            ERR_APPEAL_INVALID_STATE,
        )

        stored = read_appeal(api, appeal["id"])
        assert stored["status"] == APPEAL_STATUS_UPHELD
        assert stored["decision_rationale"] == rationale

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_REVOKED


class TestPostureAndTemporalRefusals:
    """Attestation cover and the badge clock, each failing on its own with nothing else wrong."""

    def test_approving_a_rep_who_holds_no_attestations_is_refused_422(self, api):
        """With no state violation in play, a bare roster entry cannot be put on a case.

        "the representative's recomputed `credential_posture` is `COMPLIANT` or
        `EXPIRING_SOON`, and is neither `INCOMPLETE` nor `LAPSED`, else
        `ERR_REP_CREDENTIALS_NOT_COMPLIANT` (422). Applies to two operations:
        deciding a case authorization and kiosk check-in."

        Design: Corner/errors/approval_of_an_uncredentialed_rep_returns_422
        """
        facility = create_facility(
            api, "NC-56", name="Not Compliant Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "NOCV", legal_name="Not Compliant Devices")
        rep = create_vendor_rep(api, vendor["id"], "Nora Nocred")
        case = create_case(
            api,
            facility["id"],
            "CASE-15130",
            "2026-09-16T08:00:00Z",
            "2026-09-16T10:00:00Z",
            procedure_name="Uncredentialed Rep Case",
        )
        authorization = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_OBSERVATION,
            headers=make_vendor_admin_headers(vendor["id"]),
        )

        validate_error(
            api.decide_authorization(
                authorization["id"],
                authorization_decision_payload("APPROVE"),
                OR_COORDINATOR,
            ),
            ERR_REP_CREDENTIALS_NOT_COMPLIANT,
        )

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["credential_posture"] == POSTURE_INCOMPLETE
        assert stored_rep["access_status"] == ACCESS_STATUS_PENDING

        stored_auth = read_authorization(api, authorization["id"])
        assert stored_auth["status"] == AUTH_STATUS_REQUESTED

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "authorizations_used_epoch", 0)

    def test_a_check_in_one_second_before_the_window_opens_is_refused_422(self, api):
        """A fully credentialed rep is still one second too early for the kiosk.

        "check-in is admissible when the current instant is at or after
        `badge_window_start_utc` and at or before `badge_window_end_utc`, so
        arriving at exactly the opening instant or exactly the closing instant
        both succeed, and anything outside is refused with
        `ERR_BADGE_WINDOW_NOT_OPEN`." With the site default of sixty lead
        minutes, a 09:00 case opens its window at 08:00.

        Design: Corner/errors/check_in_one_second_before_the_badge_window_returns_422
        """
        facility = create_facility(
            api, "BW-61", name="Badge Window Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "BWNV", legal_name="Badge Window Devices")
        rep = credentialed_rep(
            api,
            vendor["id"],
            "Bea Badge",
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-15160",
            "2026-09-24T09:00:00Z",
            "2026-09-24T11:00:00Z",
            procedure_name="Badge Window Case",
        )
        authorization = approved_authorization(
            api, case["id"], rep["id"], REQUESTED_ROLE_TECHNICAL_SUPPORT
        )
        assert_instant_equals(
            authorization["badge_window_start_utc"],
            "2026-09-24T08:00:00Z",
            "badge_window_start_utc",
        )

        set_clock(api, "2026-09-24T07:59:59Z")
        validate_error(
            api.create_check_in(
                check_in_payload(authorization["id"]),
                make_vendor_rep_headers(rep["id"]),
            ),
            ERR_BADGE_WINDOW_NOT_OPEN,
        )

        _badges, meta = list_rows_and_meta(
            api.list_authorization_check_ins(authorization["id"], COMPLIANCE_ADMIN)
        )
        assert_total_count(meta, 0)

        stored_auth = read_authorization(api, authorization["id"])
        assert stored_auth["status"] == AUTH_STATUS_APPROVED

        # No state violation was in play: only the clock stood in the way.
        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert stored_rep["credential_posture"] == POSTURE_COMPLIANT

        # One second later the window is open and the same badge prints.
        set_clock(api, "2026-09-24T08:00:00Z")
        badge = check_in(api, authorization["id"], rep["id"])
        assert badge["badge_status"] == BADGE_STATUS_ISSUED


class TestFiscalRefusals:
    """The fee ledger is kept vendor-wide, so one late set can hold up a punctual sibling."""

    def test_releasing_a_punctual_set_under_a_fee_hold_is_refused_402(self, api):
        """An on-time tray set is held out of theatre by a sibling set's late fee.

        "the vendor's `late_fee_balance_cents` must be strictly below the fee
        hold threshold of 100,000 cents, else it is refused with
        `ERR_VENDOR_FEE_HOLD`." The balance "is defined as the sum of
        `assessed_late_fee_cents` over that vendor's sets in that state", so it
        spans every case the vendor supplies.

        Design: Corner/errors/release_under_a_fee_hold_returns_402
        """
        facility = create_facility(
            api, "FH-62", name="Fee Hold Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "FHOLV", legal_name="Fee Hold Devices")
        _request, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "FH-1700",
            62000,
            is_implant=False,
            product_name="Fee Hold Tray System",
            manufacturer="Fholv",
        )

        # The offending set: twelve implant-specialty trays due 15 hours before the
        # knife, delivered 2000 minutes late for a fee of 8750 cents a tray.
        late_case = create_case(
            api,
            facility["id"],
            "CASE-15170",
            "2026-11-02T08:00:00Z",
            "2026-11-02T11:00:00Z",
            procedure_name="Fee Hold Case A",
        )
        late_set = register_loaner_set(
            api,
            vendor["id"],
            late_case["id"],
            product["id"],
            12,
            COMPLEXITY_IMPLANT_SPECIALTY,
        )
        assert_instant_equals(
            late_set["required_delivery_deadline_utc"],
            "2026-11-01T17:00:00Z",
            "required_delivery_deadline_utc",
        )
        receive_loaner_set(api, late_set["id"], "2026-11-03T02:20:00Z")

        # The punctual set on a different case, an hour inside its own deadline.
        punctual_case = create_case(
            api,
            facility["id"],
            "CASE-15171",
            "2026-11-05T08:00:00Z",
            "2026-11-05T10:00:00Z",
            procedure_name="Fee Hold Case B",
        )
        punctual_set = register_loaner_set(
            api,
            vendor["id"],
            punctual_case["id"],
            product["id"],
            2,
            COMPLEXITY_SIMPLE,
        )
        assert_instant_equals(
            punctual_set["required_delivery_deadline_utc"],
            "2026-11-05T02:00:00Z",
            "required_delivery_deadline_utc",
        )
        received = receive_loaner_set(api, punctual_set["id"], "2026-11-05T01:00:00Z")
        assert received["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert_money_cents(received, "assessed_late_fee_cents", 0)
        assert received["fee_status"] == FEE_STATUS_NONE

        stored_late = read_loaner_set(api, late_set["id"])
        assert stored_late["status"] == LOANER_STATUS_REJECTED_LATE
        assert_integer_field(stored_late, "late_minutes_current_basis", 2000)
        assert_money_cents(stored_late, "assessed_late_fee_cents", 105000)
        assert stored_late["fee_status"] == FEE_STATUS_ASSESSED

        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 105000)
        assert stored_vendor["late_fee_balance_cents"] >= FEE_HOLD_THRESHOLD_CENTS

        validate_error(
            api.release_loaner_set(punctual_set["id"], {}, STERILE_PROCESSING_TECH),
            ERR_VENDOR_FEE_HOLD,
        )

        held_back = read_loaner_set(api, punctual_set["id"])
        assert held_back["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert held_back["fee_status"] == FEE_STATUS_NONE

        stored_case = read_case(api, punctual_case["id"])
        assert stored_case["implant_readiness_status"] == READINESS_NOT_APPLICABLE
