"""State machines that bound a loop, cancel a theatre, and reach across entities."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    ACCESS_STATUS_PENDING,
    ACCESS_STATUS_SUSPENDED,
    APPEAL_STATUS_OVERTURNED,
    AUTH_STATUS_DENIED,
    AUTH_STATUS_REVOKED,
    BADGE_STATUS_VOIDED,
    CASE_STATUS_CANCELLED,
    COMPLEXITY_COMPLEX,
    COMPLEXITY_SIMPLE,
    COVERAGE_NOT_REQUIRED,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_COI,
    CREDENTIAL_TYPE_INFLUENZA,
    ERR_PIR_REVISION_LIMIT,
    ESCORT_NOT_REQUIRED,
    FEE_STATUS_NONE,
    INCIDENT_STATUS_SUBSTANTIATED,
    INCIDENT_STATUS_UNSUBSTANTIATED,
    INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
    LOANER_STATUS_EXPECTED,
    LOANER_STATUS_HELD,
    LOANER_STATUS_RELEASED,
    OUTCOME_SUBSTANTIATED,
    OUTCOME_UNSUBSTANTIATED,
    PIR_STATUS_APPROVED,
    PIR_STATUS_VALUE_ANALYSIS_REVIEW,
    POSTURE_COMPLIANT,
    POSTURE_LAPSED,
    PRODUCT_STATUS_ACTIVE,
    PRODUCT_STATUS_SUSPENDED,
    READINESS_BLOCKED,
    READINESS_PENDING,
    READINESS_READY,
    REQUESTED_ROLE_OBSERVATION,
    REVOKED_REASON_CASE_CANCELLED,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    STATUS_IN_GOOD_STANDING,
    SUSPENDED_REASON_INCIDENT,
    SUSPENDED_REASON_NONE,
    SUSPENSION_REASON_CREDENTIAL_LAPSED,
    TIER_PLATINUM,
    USER_COMPLIANCE_1,
    adjudicate_incident,
    appeal_decision_payload,
    approved_authorization,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    badge_serial,
    cancel_payload,
    check_in,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credentialed_rep,
    decide_value_analysis,
    endorse_pir,
    file_appeal,
    file_credential,
    find_by_id,
    list_rows,
    open_pir,
    read_approved_product,
    read_authorization,
    read_case,
    read_check_in,
    read_incident,
    read_loaner_set,
    read_pir,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    release_loaner_set,
    report_incident,
    request_authorization,
    revoke_rep,
    run_sweep,
    set_clock,
    submit_pir,
    value_analysis_payload,
    verify_credential,
    COMPLIANCE_ADMIN,
    CREDENTIALING_OFFICER,
    OR_COORDINATOR,
    VALUE_ANALYSIS_APPROVER,
    validate_error,
    validate_success,
)


class TestProductRevisionLoopIsBounded:
    """The committee may send a request back only twice before the loop is closed."""

    def test_third_change_request_is_refused_and_the_approval_route_stays_open(self, api):
        """Two full revision rounds lift the round counter to two and close the loop.

        "A change request is admissible only while `revision_round` is strictly
        below two, and the third attempt is refused with `ERR_PIR_REVISION_LIMIT`,
        which is what terminates the `CLINICAL_REVIEW → CHANGES_REQUESTED →
        CLINICAL_REVIEW` cycle at a bounded number of rounds."

        Design: Corner/state_machines/pir_revision_cycle_terminates_at_max_revision_rounds
        """
        facility = create_facility(
            api, "PR-34", name="Pir Rounds Hospital",
            spd_turnaround_hours=5, spd_bay_count=2,
        )
        vendor = create_vendor(api, "PIRV", legal_name="Pir Rounds Devices")
        pir = open_pir(
            api,
            vendor["id"],
            facility["id"],
            "RC-400",
            400000,
            is_implant=True,
            product_name="Revised Cage",
            manufacturer="Pirv",
        )

        # Each round needs a fresh endorsement, because a change request clears
        # the sponsor the committee is barred from voting as.
        for _round in range(2):
            submit_pir(api, vendor["id"], pir["id"])
            endorse_pir(api, pir["id"])
            decide_value_analysis(api, pir["id"], "REQUEST_CHANGES")
        submit_pir(api, vendor["id"], pir["id"])
        endorse_pir(api, pir["id"])

        before = read_pir(api, pir["id"])
        assert before["status"] == PIR_STATUS_VALUE_ANALYSIS_REVIEW
        assert_integer_field(before, "revision_round", 2)

        refused = api.value_analysis_decision(
            pir["id"], value_analysis_payload("REQUEST_CHANGES"), VALUE_ANALYSIS_APPROVER
        )
        validate_error(refused, ERR_PIR_REVISION_LIMIT)

        after = read_pir(api, pir["id"])
        assert after["status"] == PIR_STATUS_VALUE_ANALYSIS_REVIEW, (
            "the refused change request should leave the request awaiting the committee"
        )
        assert_integer_field(after, "revision_round", 2)
        assert_integer_field(read_vendor(api, vendor["id"]), "open_pir_count", 1)

        # The bound closes the loop, not the exit: the committee may still approve.
        approved = decide_value_analysis(api, pir["id"], "APPROVE")
        assert approved["status"] == PIR_STATUS_APPROVED


class TestCancellationCascadesThroughTheCase:
    """One cancellation reaches every child of the case, each in its own state."""

    def test_cancel_denies_the_request_revokes_the_approval_and_voids_the_badge(self, api):
        """The two authorizations of a cancelled case end in two different states.

        "every authorization of the case that is still `REQUESTED` moves
        `REQUESTED → DENIED`, and every one that is `APPROVED` moves
        `APPROVED → REVOKED` with `revoked_reason` set to `CASE_CANCELLED`
        ... Because those authorizations are now `REVOKED`, each of their kiosk
        check-ins whose `badge_status` is `ISSUED` moves to `VOIDED`."

        Design: Corner/state_machines/case_cancellation_cascades_to_authorizations_and_badges
        """
        facility = create_facility(
            api, "CD-35", name="Cascade Down Hospital",
            spd_turnaround_hours=5, spd_bay_count=2,
        )
        vendor = create_vendor(api, "CASCV", legal_name="Cascade Devices")
        cara = credentialed_rep(api, vendor["id"], "Cara Cascade")
        colin = create_vendor_rep(api, vendor["id"], "Colin Cascade")
        case = create_case(
            api,
            facility["id"],
            "CASE-13501",
            "2026-08-06T08:00:00Z",
            "2026-08-06T10:00:00Z",
            procedure_name="Cascade Case",
        )
        cara_auth = approved_authorization(api, case["id"], cara["id"])
        colin_auth = request_authorization(
            api, case["id"], colin["id"], REQUESTED_ROLE_OBSERVATION
        )

        # The badge prints inside the window the approval derived, 07:00 to 10:30.
        set_clock(api, "2026-08-06T07:30:00Z")
        badge = check_in(api, cara_auth["id"], cara["id"])
        assert badge["badge_serial"] == badge_serial("CD-35", 1)

        cancelled = validate_success(
            api.cancel_surgical_case(
                case["id"], cancel_payload("Surgeon unavailable"), OR_COORDINATOR
            ),
            200,
        )
        assert cancelled["status"] == CASE_STATUS_CANCELLED

        revoked = read_authorization(api, cara_auth["id"])
        assert revoked["status"] == AUTH_STATUS_REVOKED
        assert revoked["revoked_reason"] == REVOKED_REASON_CASE_CANCELLED
        assert read_authorization(api, colin_auth["id"])["status"] == AUTH_STATUS_DENIED

        voided = read_check_in(api, badge["id"])
        assert voided["badge_status"] == BADGE_STATUS_VOIDED
        assert voided["escort_status"] == ESCORT_NOT_REQUIRED, (
            "a cancellation never touches the escort dimension"
        )
        assert voided["checked_out_at_utc"] is None

        settled = read_case(api, case["id"])
        assert_integer_field(settled, "approved_rep_count", 0)
        assert_integer_field(settled, "revoked_authorization_count", 1)
        assert settled["vendor_coverage_status"] == COVERAGE_NOT_REQUIRED

        assert_integer_field(read_vendor(api, vendor["id"]), "authorizations_used_epoch", 0)
        stored_cara = read_vendor_rep(api, cara["id"])
        assert_integer_field(stored_cara, "open_authorization_count", 0)
        assert stored_cara["access_status"] == ACCESS_STATUS_CREDENTIALED


class TestReadinessBubblesUpFromTheTrays:
    """The case reads READY only once the last tray set has gone to theatre."""

    def test_readiness_waits_for_the_second_release_before_it_reads_ready(self, api):
        """With one of two sets released the implant case is still PENDING.

        "Otherwise, if the case has at least one set and every one of them is
        `RELEASED_TO_OR`, the posture is `READY`. Otherwise the posture is
        `PENDING`."

        Design: Corner/state_machines/case_readiness_becomes_ready_when_every_set_is_released
        """
        facility = create_facility(
            api, "BU-38", name="Bubble Up Hospital",
            spd_turnaround_hours=4, spd_bay_count=3,
        )
        vendor = create_vendor(api, "BUBBV", legal_name="Bubble Up Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "BC-500",
            500000,
            is_implant=True,
            product_name="Bubble Cage",
            manufacturer="Bubbv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-13801",
            "2026-10-12T08:00:00Z",
            "2026-10-12T10:00:00Z",
            procedure_name="Bubble Fusion",
            implant_required=True,
        )
        first = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 2, COMPLEXITY_SIMPLE
        )
        second = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 6, COMPLEXITY_COMPLEX
        )

        # Both trays hit the 24-hour implant floor rather than their own turnaround.
        for tray_set in (first, second):
            assert_instant_equals(
                tray_set["required_delivery_deadline_utc"],
                "2026-10-11T08:00:00Z",
                "required_delivery_deadline_utc",
            )

        receive_loaner_set(api, first["id"])
        receive_loaner_set(api, second["id"])
        release_loaner_set(api, first["id"])

        assert read_case(api, case["id"])["implant_readiness_status"] == READINESS_PENDING, (
            "one released set out of two leaves the theatre waiting"
        )

        release_loaner_set(api, second["id"])

        assert read_case(api, case["id"])["implant_readiness_status"] == READINESS_READY
        for set_id in (first["id"], second["id"]):
            stored = read_loaner_set(api, set_id)
            assert stored["status"] == LOANER_STATUS_RELEASED
            assert_integer_field(stored, "late_minutes_current_basis", 0)
            assert_money_cents(stored, "assessed_late_fee_cents", 0)
            assert stored["fee_status"] == FEE_STATUS_NONE

        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 0)
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 100)


class TestSubstantiationHoldsOnlyTheTraysStillInTheBay:
    """Suspending a product holds the sets it can still reach, and no others."""

    def test_the_expected_set_is_held_while_the_released_set_stands(self, api):
        """Of two sets of one suspended product only the undelivered one is held.

        "every loaner set referencing it whose `status` is `EXPECTED`,
        `DELIVERED_ON_TIME` or `DELIVERED_LATE` moves to `HELD`, processed in
        ascending creation order."

        Design: Corner/state_machines/substantiation_holds_only_non_released_sets_of_the_product
        """
        facility = create_facility(
            api, "CC-37", name="Conditional Cascade Hospital",
            spd_turnaround_hours=4, spd_bay_count=3,
        )
        vendor = create_vendor(api, "CONDV", legal_name="Conditional Devices")
        cody = create_vendor_rep(api, vendor["id"], "Cody Conditional")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "CS-600",
            250000,
            is_implant=True,
            product_name="Conditional Screw",
            manufacturer="Condv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-13701",
            "2026-10-15T08:00:00Z",
            "2026-10-15T10:00:00Z",
            procedure_name="Conditional Fusion",
            implant_required=True,
        )
        released_set = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 2, COMPLEXITY_SIMPLE
        )
        expected_set = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 3, COMPLEXITY_SIMPLE
        )
        receive_loaner_set(api, released_set["id"])
        release_loaner_set(api, released_set["id"])

        incident = report_incident(
            api,
            case["id"],
            cody["id"],
            INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
            SEVERITY_MINOR,
            headers=OR_COORDINATOR,
            narrative="Screw opened before value-analysis paperwork was confirmed",
            approved_product_id=product["id"],
        )
        adjudicated = adjudicate_incident(
            api, incident["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN
        )
        assert adjudicated["status"] == INCIDENT_STATUS_SUBSTANTIATED
        assert adjudicated["adjudicated_outcome"] == OUTCOME_SUBSTANTIATED

        suspended = read_approved_product(api, product["id"])
        assert suspended["status"] == PRODUCT_STATUS_SUSPENDED
        assert suspended["suspended_reason"] == SUSPENDED_REASON_INCIDENT

        assert read_loaner_set(api, expected_set["id"])["status"] == LOANER_STATUS_HELD
        assert read_loaner_set(api, released_set["id"])["status"] == LOANER_STATUS_RELEASED, (
            "a set that has already gone to theatre is never pulled back into a hold"
        )
        assert read_case(api, case["id"])["implant_readiness_status"] == READINESS_BLOCKED

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "provisional_compliance_score", 97)
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 97)
        assert read_vendor_rep(api, cody["id"])["access_status"] == ACCESS_STATUS_PENDING, (
            "a MINOR finding never reaches the representative's site access"
        )


class TestReversedSubstantiationUnwindsWithoutDrift:
    """Clearing a vendor puts the product, the tray and both scores back."""

    def test_unsubstantiating_restores_the_product_the_set_and_the_scores(self, api):
        """The round trip through substantiation leaves nothing behind it.

        "A product that this incident suspended returns `SUSPENDED → ACTIVE` with
        `suspended_reason` reset to `NONE` ... Each of that product's loaner sets
        in `HELD` returns to the delivery branch its own late minutes imply."

        Design: Corner/state_machines/substantiation_reversal_restores_product_and_releases_hold
        """
        facility = create_facility(
            api, "CM-36", name="Compensating Hospital",
            spd_turnaround_hours=6, spd_bay_count=2,
        )
        vendor = create_vendor(api, "COMPV", legal_name="Compensating Devices")
        cleo = create_vendor_rep(api, vendor["id"], "Cleo Compensate")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "CST-700",
            700000,
            is_implant=True,
            product_name="Compensating Stem",
            manufacturer="Compv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-13601",
            "2026-10-05T08:00:00Z",
            "2026-10-05T10:00:00Z",
            procedure_name="Compensating Arthroplasty",
            implant_required=True,
        )
        tray_set = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 5, COMPLEXITY_COMPLEX
        )
        incident = report_incident(
            api,
            case["id"],
            cleo["id"],
            INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
            SEVERITY_MAJOR,
            headers=OR_COORDINATOR,
            narrative="Stem reported as used without an approved introduction",
            approved_product_id=product["id"],
        )

        adjudicate_incident(api, incident["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN)
        after_finding = read_vendor(api, vendor["id"])
        assert_integer_field(after_finding, "provisional_compliance_score", 92)
        assert_integer_field(after_finding, "adjudicated_compliance_score", 92)
        assert read_loaner_set(api, tray_set["id"])["status"] == LOANER_STATUS_HELD

        cleared = adjudicate_incident(
            api, incident["id"], OUTCOME_UNSUBSTANTIATED, COMPLIANCE_ADMIN
        )
        assert cleared["status"] == INCIDENT_STATUS_UNSUBSTANTIATED
        assert cleared["adjudicated_outcome"] == OUTCOME_UNSUBSTANTIATED

        restored = read_approved_product(api, product["id"])
        assert restored["status"] == PRODUCT_STATUS_ACTIVE
        assert restored["suspended_reason"] == SUSPENDED_REASON_NONE

        unheld = read_loaner_set(api, tray_set["id"])
        assert unheld["status"] == LOANER_STATUS_EXPECTED, (
            "a set that was never delivered returns to the undelivered branch"
        )
        assert unheld["delivered_at_utc"] is None
        assert_instant_equals(
            unheld["required_delivery_deadline_utc"],
            "2026-10-04T08:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_money_cents(unheld, "assessed_late_fee_cents", 0)
        assert read_case(api, case["id"])["implant_readiness_status"] == READINESS_PENDING

        settled = read_vendor(api, vendor["id"])
        assert_integer_field(settled, "provisional_compliance_score", 100)
        assert_integer_field(settled, "adjudicated_compliance_score", 100)
        assert_money_cents(settled, "late_fee_balance_cents", 0)
        assert read_incident(api, incident["id"])["status"] == INCIDENT_STATUS_UNSUBSTANTIATED


class TestOverturnedAppealHonoursTheCurrentCredentials:
    """Winning the appeal buys back the record, not the immunizations.

    An overturn recomputes the representative's posture at the decision instant,
    so a representative whose influenza attestation lapsed while the appeal sat
    on the desk comes back suspended rather than credentialed.
    """

    def test_overturn_lands_the_lapsed_representative_in_suspended(self, api):
        """An overturn cannot manufacture the credentials the lapse removed.

        "When the recomputed posture is `COMPLIANT` or `EXPIRING_SOON`, the
        representative goes `REVOKED → CREDENTIALED`. When it is anything else,
        the representative goes `REVOKED → SUSPENDED` with `suspension_reason`
        set to `CREDENTIAL_LAPSED`, because an overturned revocation cannot
        manufacture credentials the representative does not hold."

        Design: Corner/state_machines/appeal_overturn_lands_lapsed_rep_in_suspended
        """
        vendor = create_vendor(api, "APPLV", legal_name="Appeal Overturn Devices")
        ada = create_vendor_rep(api, vendor["id"], "Ada Appeal")
        influenza = file_credential(
            api,
            ada["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2026-09-01T00:00:00Z",
            document_reference="FLU-AP-01",
        )
        verify_credential(api, influenza["id"])
        for credential_type, reference in (
            (CREDENTIAL_TYPE_BLOODBORNE, "BBP-AP-01"),
            (CREDENTIAL_TYPE_BACKGROUND, "BGC-AP-01"),
            (CREDENTIAL_TYPE_COI, "COI-AP-01"),
        ):
            filed = file_credential(
                api,
                ada["id"],
                credential_type,
                issued_at_utc="2026-07-01T00:00:00Z",
                expires_at_utc="2027-07-01T00:00:00Z",
                document_reference=reference,
            )
            verify_credential(api, filed["id"])
        assert read_vendor_rep(api, ada["id"])["credential_posture"] == POSTURE_COMPLIANT

        set_clock(api, "2026-08-15T00:00:00Z")
        revoke_rep(
            api,
            ada["id"],
            CREDENTIALING_OFFICER,
            "Unescorted entry reported by the OR desk",
        )
        appeal = file_appeal(
            api,
            vendor["id"],
            ada["id"],
            grounds="Badge reader misread; escort was present throughout",
        )
        assert_instant_equals(
            appeal["appeal_deadline_utc"], "2026-08-29T00:00:00Z", "appeal_deadline_utc"
        )

        # The influenza attestation lapses while the appeal waits on the desk.
        set_clock(api, "2026-09-02T00:00:00Z")
        sweep = run_sweep(api)
        assert_integer_field(sweep, "credentials_expired_count", 1)
        assert_integer_field(sweep, "reps_suspended_count", 0)
        influenza_rows = list_rows(
            api.list_rep_credentials(
                ada["id"], COMPLIANCE_ADMIN, {"credential_type": CREDENTIAL_TYPE_INFLUENZA}
            )
        )
        assert find_by_id(influenza_rows, influenza["id"])["status"] == "EXPIRED"

        decided = validate_success(
            api.decide_access_appeal(
                appeal["id"],
                appeal_decision_payload(
                    "OVERTURN", "Reader log corroborates the vendor's account"
                ),
                COMPLIANCE_ADMIN,
            ),
            200,
        )
        assert decided["status"] == APPEAL_STATUS_OVERTURNED
        assert decided["decided_by_user_id"] == USER_COMPLIANCE_1
        assert_instant_equals(
            decided["decided_at_utc"], "2026-09-02T00:00:00Z", "decided_at_utc"
        )
        assert (
            decided["decision_rationale"]
            == "Reader log corroborates the vendor's account"
        )

        reinstated = read_vendor_rep(api, ada["id"])
        assert reinstated["access_status"] == ACCESS_STATUS_SUSPENDED
        assert reinstated["suspension_reason"] == SUSPENSION_REASON_CREDENTIAL_LAPSED
        assert reinstated["credential_posture"] == POSTURE_LAPSED
        assert_instant_equals(
            reinstated["reinstated_at_utc"], "2026-09-02T00:00:00Z", "reinstated_at_utc"
        )
        assert_instant_equals(
            reinstated["revoked_at_utc"], "2026-08-15T00:00:00Z", "revoked_at_utc"
        )

        stored_vendor = read_vendor(api, vendor["id"])
        assert stored_vendor["scorecard_tier"] == TIER_PLATINUM
        assert stored_vendor["compliance_status"] == STATUS_IN_GOOD_STANDING
        assert_integer_field(stored_vendor, "access_quota_in_effect", 6)
        assert_integer_field(stored_vendor, "last_sweep_epoch", 1)
