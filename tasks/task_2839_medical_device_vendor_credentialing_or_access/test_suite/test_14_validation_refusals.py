"""Refusals raised by the uniqueness, temporal, custody and quota gates."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_REVOKED,
    APPEAL_STATUS_SUBMITTED,
    APPEAL_WINDOW_DAYS,
    AUTH_STATUS_APPROVED,
    AUTH_STATUS_REQUESTED,
    BADGE_STATUS_CHECKED_OUT,
    BADGE_STATUS_ISSUED,
    BASE_QUOTA,
    COMPLIANCE_ADMIN,
    COVERAGE_NOT_REQUIRED,
    COVERAGE_UNCOVERED,
    CREDENTIALING_OFFICER,
    CREDENTIAL_TYPE_BACKGROUND,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_CHECK_IN_ALREADY_ACTIVE,
    ERR_DUPLICATE_AUTHORIZATION,
    ERR_DUPLICATE_CREDENTIAL,
    ERR_DUPLICATE_VENDOR_CODE,
    ERR_ESCORT_REQUIRED,
    ERR_IMPLANT_REQUIRES_APPROVED_PRODUCT,
    ERR_INVALID_TIME_RANGE,
    ERR_VENDOR_ACCESS_QUOTA_EXCEEDED,
    ESCORT_NOT_REQUIRED,
    ESCORT_PENDING,
    ESCORT_RELEASED,
    OR_COORDINATOR,
    POSTURE_INCOMPLETE,
    PRODUCT_STATUS_ACTIVE,
    REQUESTED_ROLE_IMPLANT_SUPPORT,
    REQUESTED_ROLE_OBSERVATION,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    RESTRICTION_RESTRICTED,
    USER_ORC_1,
    access_appeal_payload,
    approved_product,
    assert_instant_equals,
    assert_instant_is_none,
    assert_integer_field,
    assert_total_count,
    attach_escort,
    authorization_decision_payload,
    authorization_payload,
    badge_serial,
    check_in,
    check_in_payload,
    check_out,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credential_payload,
    credentialed_rep,
    decide_authorization,
    file_appeal,
    file_credential,
    list_rows_and_meta,
    make_vendor_admin_headers,
    make_vendor_rep_headers,
    quota_hard_cap,
    read_authorization,
    read_case,
    read_check_in,
    read_vendor,
    read_vendor_rep,
    request_authorization,
    revoke_rep,
    set_clock,
    shift_instant,
    surgical_case_payload,
    validate_error,
    vendor_payload,
)


class TestDuplicateRegistrationRefusals:
    """The uniqueness gates that guard a natural key and two occupied slots."""

    def test_second_vendor_carrying_the_same_vendor_code_is_refused(self, api):
        """A different legal name does not buy a second vendor the code DUPV.

        "a facility `code`, a `vendor_code` and a `case_number` must each be
        unused, else `ERR_DUPLICATE_FACILITY_CODE`, `ERR_DUPLICATE_VENDOR_CODE`
        or `ERR_DUPLICATE_CASE_NUMBER` (409)".

        Design: Corner/validations/duplicate_vendor_code_rejected
        """
        enrolled = create_vendor(api, "DUPV", legal_name="Duplicate Devices One")

        validate_error(
            api.create_vendor(
                vendor_payload("DUPV", legal_name="Duplicate Devices Two"),
                CREDENTIALING_OFFICER,
            ),
            ERR_DUPLICATE_VENDOR_CODE,
        )

        survivor = read_vendor(api, enrolled["id"])
        assert survivor["id"] == enrolled["id"]
        assert survivor["vendor_code"] == "DUPV"
        assert survivor["legal_name"] == "Duplicate Devices One", (
            "the refused enrolment must not have overwritten the vendor holding the code"
        )
        assert survivor["version"] == enrolled["version"], (
            "a refused enrolment leaves the surviving vendor row untouched"
        )

    def test_second_pending_background_check_for_one_rep_is_refused(self, api):
        """An unverified background check still occupies its type slot.

        "a representative may not hold a second credential of the same
        `credential_type` while an existing one is in `PENDING_VERIFICATION`,
        `VERIFIED` or `EXPIRING_SOON`".

        Design: Corner/validations/duplicate_pending_credential_of_the_same_type_rejected
        """
        vendor = create_vendor(api, "DUPCV", legal_name="Duplicate Credential Devices")
        rep = create_vendor_rep(api, vendor["id"], "Dana Dup")
        filed = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BACKGROUND,
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
            document_reference="BGC-DUP-01",
        )
        assert filed["status"] == "PENDING_VERIFICATION"

        validate_error(
            api.create_credential(
                credential_payload(
                    rep["id"],
                    CREDENTIAL_TYPE_BACKGROUND,
                    issued_at_utc="2026-07-10T00:00:00Z",
                    expires_at_utc="2027-07-10T00:00:00Z",
                    document_reference="BGC-DUP-02",
                ),
                CREDENTIALING_OFFICER,
            ),
            ERR_DUPLICATE_CREDENTIAL,
        )

        rows, meta = list_rows_and_meta(
            api.list_rep_credentials(
                rep["id"],
                COMPLIANCE_ADMIN,
                {"credential_type": CREDENTIAL_TYPE_BACKGROUND},
            )
        )
        assert_total_count(meta, 1)
        assert rows[0]["id"] == filed["id"]
        assert rows[0]["document_reference"] == "BGC-DUP-01"

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["credential_posture"] == POSTURE_INCOMPLETE, (
            "a pending attestation covers nothing, so the posture has not moved"
        )

    def test_second_authorization_for_the_same_case_and_rep_is_refused(self, api):
        """The first request is still awaiting a decision and already blocks the pair.

        "A duplicate request for a case-and-representative pair that already has
        one in `REQUESTED` or `APPROVED` is refused".

        Design: Corner/validations/duplicate_authorization_for_the_same_case_and_rep_rejected
        """
        facility = create_facility(
            api,
            "DA-46",
            name="Duplicate Authorization Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(
            api, "DUPAV", legal_name="Duplicate Authorization Devices"
        )
        rep = credentialed_rep(api, vendor["id"], "Dale Dup")
        case = create_case(
            api,
            facility["id"],
            "CASE-15035",
            "2026-09-12T08:00:00Z",
            "2026-09-12T10:00:00Z",
            procedure_name="Duplicate Authorization Case",
        )
        vendor_headers = make_vendor_admin_headers(vendor["id"])
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_TECHNICAL_SUPPORT,
            headers=vendor_headers,
        )
        assert requested["status"] == AUTH_STATUS_REQUESTED

        validate_error(
            api.create_authorization(
                authorization_payload(
                    case["id"], rep["id"], REQUESTED_ROLE_OBSERVATION
                ),
                vendor_headers,
            ),
            ERR_DUPLICATE_AUTHORIZATION,
        )

        rows, meta = list_rows_and_meta(
            api.list_authorizations(
                COMPLIANCE_ADMIN, {"surgical_case_id": case["id"]}
            )
        )
        assert_total_count(meta, 1)
        assert rows[0]["id"] == requested["id"]
        assert rows[0]["requested_role"] == REQUESTED_ROLE_TECHNICAL_SUPPORT, (
            "the refused observation request must not have rewritten the standing one"
        )

        stored_case = read_case(api, case["id"])
        assert_integer_field(stored_case, "approved_rep_count", 0)


class TestScheduleInstantOrdering:
    """The instant-ordering rung fires before any business judgement."""

    def test_case_ending_one_second_before_it_starts_is_refused(self, api):
        """A backwards operating window is a malformed schedule, not a business conflict.

        "any pair of instants supplied together must be correctly ordered, else
        `ERR_INVALID_TIME_RANGE` (400)", and for a surgical case "the end must be
        strictly after the start".

        Design: Corner/validations/case_end_before_start_rejects_with_invalid_time_range
        """
        facility = create_facility(
            api,
            "TR-45",
            name="Time Range Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )

        validate_error(
            api.create_surgical_case(
                surgical_case_payload(
                    facility["id"],
                    "CASE-15030",
                    "2026-09-10T08:00:00Z",
                    "2026-09-10T07:59:59Z",
                    procedure_name="Backwards Window Case",
                ),
                OR_COORDINATOR,
            ),
            ERR_INVALID_TIME_RANGE,
        )

        rows, meta = list_rows_and_meta(
            api.list_surgical_cases(COMPLIANCE_ADMIN, {"facility_id": facility["id"]})
        )
        assert_total_count(meta, 0)
        assert rows == [], "the refused schedule must not have left a case behind"


class TestOneLiveBadgePerAuthorization:
    """A second kiosk visit inside an open badge window mints nothing."""

    def test_second_check_in_while_the_first_badge_is_issued_is_refused(self, api):
        """Ada already holds badge AC-47-0001, so the kiosk turns her away.

        "the authorization has no other check-in whose `badge_status` is
        `ISSUED`, else `ERR_CHECK_IN_ALREADY_ACTIVE` (409)".

        Design: Corner/validations/second_kiosk_check_in_while_a_badge_is_issued_rejected
        """
        facility = create_facility(
            api,
            "AC-47",
            name="Active Badge Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "ACTV", legal_name="Active Badge Devices")
        rep = credentialed_rep(api, vendor["id"], "Ada Active")
        case = create_case(
            api,
            facility["id"],
            "CASE-15040",
            "2026-08-25T09:00:00Z",
            "2026-08-25T11:00:00Z",
            procedure_name="Active Badge Case",
        )
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_TECHNICAL_SUPPORT,
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        decide_authorization(api, requested["id"], "APPROVE", OR_COORDINATOR)

        set_clock(api, "2026-08-25T09:30:00Z")
        badge = check_in(api, requested["id"], rep["id"])
        assert badge["badge_serial"] == badge_serial("AC-47", 1)

        validate_error(
            api.create_check_in(
                check_in_payload(requested["id"]), make_vendor_rep_headers(rep["id"])
            ),
            ERR_CHECK_IN_ALREADY_ACTIVE,
        )

        rows, meta = list_rows_and_meta(
            api.list_authorization_check_ins(requested["id"], COMPLIANCE_ADMIN)
        )
        assert_total_count(meta, 1)
        assert rows[0]["id"] == badge["id"], "no second badge serial was minted"

        stored = read_check_in(api, badge["id"])
        assert stored["badge_status"] == BADGE_STATUS_ISSUED
        assert stored["escort_status"] == ESCORT_NOT_REQUIRED, (
            "a standard case needs no escort, so that dimension is already terminal"
        )
        assert_instant_equals(
            stored["valid_from_utc"], "2026-08-25T08:00:00Z", "valid_from_utc"
        )
        assert_instant_equals(
            stored["valid_until_utc"], "2026-08-25T11:30:00Z", "valid_until_utc"
        )


class TestAppealWindowBoundary:
    """Fourteen days after a revocation, one second decides the outcome."""

    @staticmethod
    def _revoked_rep(api, vendor_code, legal_name, full_name, reason):
        """Enrol a vendor, register a rep and revoke its access at 2026-08-15T00:00:00Z."""
        vendor = create_vendor(api, vendor_code, legal_name=legal_name)
        rep = create_vendor_rep(api, vendor["id"], full_name)
        set_clock(api, "2026-08-15T00:00:00Z")
        revoked = revoke_rep(api, rep["id"], CREDENTIALING_OFFICER, reason=reason)
        assert revoked["access_status"] == ACCESS_STATUS_REVOKED
        return vendor, rep, revoked["revoked_at_utc"]

    def test_appeal_filed_exactly_on_the_deadline_instant_is_accepted(self, api):
        """Abe files at the closing instant of his fourteen-day window and is heard.

        "The filing must fall no later than the representative's
        `revoked_at_utc` plus fourteen days, with filing at exactly that instant
        still accepted".

        Design: Corner/validations/appeal_filed_exactly_on_the_deadline_instant_is_accepted
        """
        vendor, rep, revoked_at = self._revoked_rep(
            api,
            "APPV",
            "Appeal Boundary Devices",
            "Abe Appeal",
            "Falsified training attestation",
        )
        deadline = shift_instant(revoked_at, days=APPEAL_WINDOW_DAYS)
        set_clock(api, deadline)

        appeal = file_appeal(
            api,
            vendor["id"],
            rep["id"],
            grounds="The training record was filed under a former surname",
        )

        assert appeal["status"] == APPEAL_STATUS_SUBMITTED
        assert_instant_equals(appeal["filed_at_utc"], deadline, "filed_at_utc")
        assert_instant_equals(
            appeal["filed_for_revoked_at_utc"], revoked_at, "filed_for_revoked_at_utc"
        )
        assert_instant_equals(
            appeal["appeal_deadline_utc"], deadline, "appeal_deadline_utc"
        )

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_REVOKED, (
            "filing an appeal contests the revocation without lifting it"
        )

    def test_appeal_filed_one_second_past_the_deadline_is_refused(self, api):
        """One second later the same filing is out of time and leaves no row behind.

        "anything past it refused with `ERR_APPEAL_WINDOW_CLOSED`".

        Design: Corner/validations/appeal_filed_one_second_past_the_deadline_rejected
        """
        vendor, rep, revoked_at = self._revoked_rep(
            api,
            "LATEV",
            "Late Appeal Devices",
            "Lou Late",
            "Repeated unescorted entry into a restricted suite",
        )
        set_clock(api, shift_instant(revoked_at, days=APPEAL_WINDOW_DAYS, seconds=1))

        validate_error(
            api.create_access_appeal(
                access_appeal_payload(
                    rep["id"],
                    grounds="The escort was present but not recorded at the kiosk",
                ),
                make_vendor_admin_headers(vendor["id"]),
            ),
            ERR_APPEAL_WINDOW_CLOSED,
        )

        rows, meta = list_rows_and_meta(
            api.list_rep_access_appeals(rep["id"], COMPLIANCE_ADMIN)
        )
        assert_total_count(meta, 0)
        assert rows == [], "a late filing must not leave an appeal on the record"

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_REVOKED


class TestImplantBackingRefusal:
    """An implant case wants an implantable product, not merely an approved one."""

    def test_implant_case_approval_without_an_active_implant_product_is_refused(self, api):
        """The vendor's only active product is a retractor, so Ida cannot be approved.

        "when the case's `implant_required` is true, the representative's
        employing vendor owns at least one approved product that is
        simultaneously `ACTIVE` and flagged `is_implant`".

        Design: Corner/validations/implant_case_approval_without_an_active_implant_product_rejected
        """
        facility = create_facility(
            api,
            "IR-48",
            name="Implant Referential Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "IMPRV", legal_name="Implant Referential Devices")
        _request, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "NR-1200",
            40000,
            is_implant=False,
            product_name="Non Implant Retractor",
            manufacturer="Imprv",
        )
        assert product["status"] == PRODUCT_STATUS_ACTIVE
        assert product["is_implant"] is False, (
            "the catalogue entry is live but is not an implant"
        )

        rep = credentialed_rep(api, vendor["id"], "Ida Implant")
        case = create_case(
            api,
            facility["id"],
            "CASE-15050",
            "2026-09-14T08:00:00Z",
            "2026-09-14T10:00:00Z",
            procedure_name="Implant Referential Case",
            implant_required=True,
        )
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_IMPLANT_SUPPORT,
            headers=make_vendor_admin_headers(vendor["id"]),
        )

        validate_error(
            api.decide_authorization(
                requested["id"],
                authorization_decision_payload("APPROVE"),
                OR_COORDINATOR,
            ),
            ERR_IMPLANT_REQUIRES_APPROVED_PRODUCT,
        )

        stored_auth = read_authorization(api, requested["id"])
        assert stored_auth["status"] == AUTH_STATUS_REQUESTED
        assert stored_auth["decided_by_user_id"] is None
        assert_instant_is_none(stored_auth, "badge_window_start_utc")
        assert stored_auth["epoch_number"] is None, (
            "a refused approval stamps no quota epoch on the authorization"
        )

        stored_case = read_case(api, case["id"])
        assert_integer_field(stored_case, "approved_rep_count", 0)
        assert stored_case["vendor_coverage_status"] == COVERAGE_UNCOVERED

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "authorizations_used_epoch", 0)


class TestEscortCustodyOnCheckOut:
    """A restricted suite will not let a badge leave without a logged escort."""

    def test_check_out_before_the_escort_is_attached_is_refused(self, api):
        """Eve's badge issues, but she may not walk out while the escort is pending.

        "If `escort_status` is still `ESCORT_PENDING`, the check-out is refused
        with `ERR_ESCORT_REQUIRED`".

        Design: Corner/validations/check_out_before_the_escort_is_attached_rejected
        """
        facility = create_facility(
            api,
            "EQ-50",
            name="Escort Required Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
            restricted_escort_required=True,
        )
        vendor = create_vendor(api, "ESCV", legal_name="Escort Required Devices")
        rep = credentialed_rep(api, vendor["id"], "Eve Escort")
        case = create_case(
            api,
            facility["id"],
            "CASE-15060",
            "2026-08-27T09:00:00Z",
            "2026-08-27T11:00:00Z",
            restriction_level=RESTRICTION_RESTRICTED,
            procedure_name="Restricted Suite Case",
        )
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_TECHNICAL_SUPPORT,
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        approved = decide_authorization(api, requested["id"], "APPROVE", OR_COORDINATOR)
        assert approved["escort_required"] is True, (
            "a restricted case at a site that demands escorts needs one named"
        )

        set_clock(api, "2026-08-27T09:30:00Z")
        badge = check_in(api, requested["id"], rep["id"])
        assert badge["escort_status"] == ESCORT_PENDING

        validate_error(
            api.check_out(badge["id"], {}, make_vendor_rep_headers(rep["id"])),
            ERR_ESCORT_REQUIRED,
        )

        stored_auth = read_authorization(api, requested["id"])
        assert stored_auth["escort_required"] is True
        assert stored_auth["escort_user_id"] is None, (
            "the approval named nobody, which is why the kiosk is still waiting"
        )

        held = read_check_in(api, badge["id"])
        assert held["badge_status"] == BADGE_STATUS_ISSUED
        assert held["escort_status"] == ESCORT_PENDING
        assert held["checked_out_at_utc"] is None

        attach_escort(api, badge["id"], USER_ORC_1)
        released = check_out(api, badge["id"], rep["id"])
        assert released["badge_status"] == BADGE_STATUS_CHECKED_OUT
        assert released["escort_status"] == ESCORT_RELEASED, (
            "the one point at which the two dimensions interact"
        )


class TestAccessQuotaHardCap:
    """Six approvals fill the epoch's allowance and the seventh is turned away."""

    def test_seventh_authorization_approval_is_refused_by_the_quota_hard_cap(self, api):
        """Quinn's seventh compliant, non-overlapping case cannot be approved this epoch.

        "With the enrolment quota of four, the cap is six, so the seventh
        approval inside a single epoch is the first one refused."

        Design: Corner/validations/seventh_authorization_approval_rejected_by_the_quota_hard_cap
        """
        facility = create_facility(
            api,
            "QC-49",
            name="Quota Cap Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "QUOTV", legal_name="Quota Cap Devices")
        rep = credentialed_rep(api, vendor["id"], "Quinn Quota")
        vendor_headers = make_vendor_admin_headers(vendor["id"])

        # Seven cases on seven consecutive days, so no two badge windows overlap.
        authorizations = []
        cases = []
        for offset in range(7):
            day = f"2026-09-0{offset + 1}"
            case = create_case(
                api,
                facility["id"],
                f"CASE-1507{offset}",
                f"{day}T08:00:00Z",
                f"{day}T10:00:00Z",
                procedure_name=f"Quota Case {offset + 1}",
            )
            cases.append(case)
            authorizations.append(
                request_authorization(
                    api,
                    case["id"],
                    rep["id"],
                    REQUESTED_ROLE_TECHNICAL_SUPPORT,
                    headers=vendor_headers,
                )
            )

        for authorization in authorizations[:6]:
            decide_authorization(api, authorization["id"], "APPROVE", OR_COORDINATOR)

        before = read_vendor(api, vendor["id"])
        assert_integer_field(before, "access_quota_in_effect", BASE_QUOTA)
        assert_integer_field(
            before, "authorizations_used_epoch", quota_hard_cap(BASE_QUOTA)
        )

        seventh = authorizations[6]
        validate_error(
            api.decide_authorization(
                seventh["id"],
                authorization_decision_payload("APPROVE"),
                OR_COORDINATOR,
            ),
            ERR_VENDOR_ACCESS_QUOTA_EXCEEDED,
        )

        refused = read_authorization(api, seventh["id"])
        assert refused["status"] == AUTH_STATUS_REQUESTED
        assert refused["epoch_number"] is None

        after = read_vendor(api, vendor["id"])
        assert_integer_field(after, "authorizations_used_epoch", 6)

        seventh_case = read_case(api, cases[6]["id"])
        assert_integer_field(seventh_case, "approved_rep_count", 0)
        assert seventh_case["vendor_coverage_status"] == COVERAGE_NOT_REQUIRED, (
            "a non-implant case with no approved representative needs no cover"
        )

        _rows, meta = list_rows_and_meta(
            api.list_authorizations(
                COMPLIANCE_ADMIN,
                {"vendor_rep_id": rep["id"], "status": AUTH_STATUS_APPROVED},
            )
        )
        assert_total_count(meta, 6)
