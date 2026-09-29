"""Guarded transitions that read a neighbouring aggregate rather than their own row.

Approving a case authorization is refused by the representative's access state, and
releasing a tray set is refused by the approved product's state, in both cases while
the row being written has not changed at all since it was created.
"""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    ACCESS_STATUS_SUSPENDED,
    AUTH_STATUS_APPROVED,
    AUTH_STATUS_REQUESTED,
    COMPLEXITY_SIMPLE,
    COVERAGE_COVERED,
    COVERAGE_NOT_REQUIRED,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_COI,
    CREDENTIAL_TYPE_INFLUENZA,
    ERR_PRODUCT_NOT_APPROVED,
    ERR_REP_ACCESS_SUSPENDED,
    LOANER_STATUS_DELIVERED_ON_TIME,
    LOANER_STATUS_RELEASED,
    OR_COORDINATOR,
    PIR_STATUS_APPROVED,
    POSTURE_COMPLIANT,
    POSTURE_LAPSED,
    PRODUCT_STATUS_ACTIVE,
    PRODUCT_STATUS_SUSPENDED,
    READINESS_PENDING,
    READINESS_READY,
    STERILE_PROCESSING_TECH,
    SUSPENDED_REASON_NONE,
    SUSPENDED_REASON_SUPERSEDED,
    SUSPENSION_REASON_CREDENTIAL_LAPSED,
    approved_product,
    assert_instant_equals,
    assert_instant_is_none,
    assert_integer_field,
    assert_money_cents,
    authorization_decision_payload,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    decide_authorization,
    file_credential,
    make_vendor_admin_headers,
    read_approved_product,
    read_authorization,
    read_case,
    read_loaner_set,
    read_pir,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    release_loaner_set,
    request_authorization,
    run_sweep,
    set_clock,
    validate_error,
    verify_credential,
)


class TestApprovalBlockedBySuspendedRep:
    """The coordinator's approval reads the representative, not the request it decides."""

    @staticmethod
    def _setup(api):
        """A pending request whose representative was suspended after it was opened."""
        facility = create_facility(
            api,
            "CE-13",
            name="Centre East Surgical Hospital",
            spd_turnaround_hours=6,
            spd_bay_count=3,
        )
        vendor = create_vendor(api, "CROSSA", legal_name="Crossarc Surgical Inc")
        rep = create_vendor_rep(
            api, vendor["id"], "Tom Vega", email="tom.vega@crossarc.example"
        )

        # The influenza shot lapses on the first of September; the other three
        # attestations run well into next summer.
        influenza = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc="2025-09-01T00:00:00Z",
            expires_at_utc="2026-09-01T00:00:00Z",
            document_reference="IMM-TOM-01",
        )
        verify_credential(api, influenza["id"])
        for credential_type, reference in (
            (CREDENTIAL_TYPE_BLOODBORNE, "BBP-TOM-01"),
            (CREDENTIAL_TYPE_BACKGROUND, "BGC-TOM-01"),
            (CREDENTIAL_TYPE_COI, "COI-TOM-01"),
        ):
            filed = file_credential(
                api,
                rep["id"],
                credential_type,
                issued_at_utc="2026-07-01T00:00:00Z",
                expires_at_utc="2027-07-01T00:00:00Z",
                document_reference=reference,
            )
            verify_credential(api, filed["id"])

        cleared = read_vendor_rep(api, rep["id"])
        assert cleared["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert cleared["credential_posture"] == POSTURE_COMPLIANT

        case = create_case(
            api,
            facility["id"],
            "CASE-10001",
            "2026-09-20T08:00:00Z",
            "2026-09-20T10:00:00Z",
            procedure_name="Laparoscopic Cholecystectomy",
        )
        # The vendor company asks for the slot while its representative is still cleared.
        authorization = request_authorization(
            api,
            case["id"],
            rep["id"],
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        assert authorization["status"] == AUTH_STATUS_REQUESTED

        # The influenza attestation lapses on the nose and the sweep observes it.
        set_clock(api, "2026-09-01T00:00:00Z")
        sweep = run_sweep(api)
        return vendor, rep, case, authorization, sweep

    def test_approval_is_refused_by_the_representatives_suspension(self, api):
        """The untouched request is refused on the representative's access state, not its own.

        "Representative not suspended — the referenced representative's
        `access_status` is not `SUSPENDED`, else `ERR_REP_ACCESS_SUSPENDED`
        (409). Applies to two operations: deciding a case authorization and
        kiosk check-in."

        Design: Difficulty/cross_entity_state_dependency/authorization_approval_blocked_by_suspended_rep_returns_409
        """
        vendor, rep, case, authorization, _sweep = self._setup(api)

        validate_error(
            api.decide_authorization(
                authorization["id"],
                authorization_decision_payload("APPROVE"),
                OR_COORDINATOR,
            ),
            ERR_REP_ACCESS_SUSPENDED,
        )

        # The state rung wins over the credential-posture rung even though the
        # lapsed influenza shot would also have refused the approval, at 422.
        suspended = read_vendor_rep(api, rep["id"])
        assert suspended["access_status"] == ACCESS_STATUS_SUSPENDED
        assert suspended["suspension_reason"] == SUSPENSION_REASON_CREDENTIAL_LAPSED
        assert suspended["credential_posture"] == POSTURE_LAPSED

        refused = read_authorization(api, authorization["id"])
        assert refused["status"] == AUTH_STATUS_REQUESTED
        assert refused["decided_by_user_id"] is None
        assert_instant_is_none(refused, "badge_window_start_utc")
        assert_instant_is_none(refused, "badge_window_end_utc")
        assert refused["epoch_number"] is None

        # Not one of the three approval counters moved, on either side of the junction.
        assert_integer_field(read_vendor(api, vendor["id"]), "authorizations_used_epoch", 0)
        assert_integer_field(suspended, "open_authorization_count", 0)
        stored_case = read_case(api, case["id"])
        assert_integer_field(stored_case, "approved_rep_count", 0)
        assert stored_case["vendor_coverage_status"] == COVERAGE_NOT_REQUIRED

    def test_the_sweep_moved_the_representative_and_left_the_request_alone(self, api):
        """The sweep suspended the representative without revoking anything.

        "For each representative newly suspended in phase 3, every `APPROVED`
        authorization of that representative whose case's `scheduled_start_utc`
        is at or after `swept_at_utc` moves `APPROVED → REVOKED`" — this request
        is merely `REQUESTED`, so the sweep passes over it.

        Design: Difficulty/cross_entity_state_dependency/authorization_approval_blocked_by_suspended_rep_returns_409
        """
        _vendor, rep, _case, authorization, sweep = self._setup(api)

        assert_integer_field(sweep, "credentials_expired_count", 1)
        assert_integer_field(sweep, "reps_suspended_count", 1)
        assert_integer_field(sweep, "authorizations_revoked_count", 0)
        assert_integer_field(sweep, "badges_voided_count", 0)
        assert_instant_equals(sweep["swept_at_utc"], "2026-09-01T00:00:00Z", "swept_at_utc")

        untouched = read_authorization(api, authorization["id"])
        assert untouched["status"] == AUTH_STATUS_REQUESTED
        assert untouched["version"] == authorization["version"], (
            "phase 4 only revokes approved rows, so the request was never rewritten"
        )
        assert read_vendor_rep(api, rep["id"])["access_status"] == ACCESS_STATUS_SUSPENDED

    def test_replacing_the_lapsed_attestation_lets_the_same_approval_through(self, api):
        """Clearing the representative's suspension admits the very same approval call.

        "The same verification, applied to a representative already sitting in
        `SUSPENDED`, moves it `SUSPENDED → CREDENTIALED` and stamps
        `reinstated_at_utc` with the logical clock's current instant — but
        **only** when the existing `suspension_reason` is `CREDENTIAL_LAPSED`."

        Design: Difficulty/cross_entity_state_dependency/authorization_approval_blocked_by_suspended_rep_returns_409
        """
        vendor, rep, case, authorization, _sweep = self._setup(api)

        validate_error(
            api.decide_authorization(
                authorization["id"],
                authorization_decision_payload("APPROVE"),
                OR_COORDINATOR,
            ),
            ERR_REP_ACCESS_SUSPENDED,
        )

        # The vendor files a fresh influenza shot; the expired one no longer blocks
        # a replacement of the same type.
        replacement = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc="2026-08-25T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
            document_reference="IMM-TOM-02",
        )
        verify_credential(api, replacement["id"])

        reinstated = read_vendor_rep(api, rep["id"])
        assert reinstated["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert reinstated["credential_posture"] == POSTURE_COMPLIANT
        assert_instant_equals(
            reinstated["reinstated_at_utc"], "2026-09-01T00:00:00Z", "reinstated_at_utc"
        )

        # The identical decision now lands, which is what shows the earlier refusal
        # came from the representative's record rather than from the request itself.
        approved = decide_authorization(
            api, authorization["id"], "APPROVE", headers=OR_COORDINATOR
        )
        assert approved["status"] == AUTH_STATUS_APPROVED
        assert_instant_equals(
            approved["badge_window_start_utc"],
            "2026-09-20T07:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            approved["badge_window_end_utc"],
            "2026-09-20T10:30:00Z",
            "badge_window_end_utc",
        )
        assert_integer_field(approved, "epoch_number", 1)

        assert_integer_field(read_vendor(api, vendor["id"]), "authorizations_used_epoch", 1)
        assert_integer_field(
            read_vendor_rep(api, rep["id"]), "open_authorization_count", 1
        )
        covered = read_case(api, case["id"])
        assert_integer_field(covered, "approved_rep_count", 1)
        assert covered["vendor_coverage_status"] == COVERAGE_COVERED


class TestReleaseBlockedBySupersededProduct:
    """Releasing a tray set reads the approved product it carries, not its own branch."""

    @staticmethod
    def _delivered_set(api):
        """A four-tray set delivered two hours early against an ACTIVE implant product."""
        facility = create_facility(
            api,
            "CE-14",
            name="Centre East Ambulatory Annex",
            spd_turnaround_hours=6,
            spd_bay_count=3,
        )
        vendor = create_vendor(api, "SUPRA", legal_name="Supralink Implants Oy")
        first_request, first_product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "CP-C4-A",
            280000,
            is_implant=True,
            product_name="Cervical Plate C4 Rev A",
            manufacturer="Supralink",
        )
        assert first_product["status"] == PRODUCT_STATUS_ACTIVE

        case = create_case(
            api,
            facility["id"],
            "CASE-10101",
            "2026-09-28T10:00:00Z",
            "2026-09-28T14:00:00Z",
            procedure_name="Anterior Cervical Discectomy and Fusion",
            implant_required=True,
        )
        tray_set = register_loaner_set(
            api, vendor["id"], case["id"], first_product["id"], 4, COMPLEXITY_SIMPLE
        )
        # Six hours of turnaround plus two for a simple reprocess is under the
        # 24-hour implant floor, so the trays are due a full day before the knife.
        assert_instant_equals(
            tray_set["required_delivery_deadline_utc"],
            "2026-09-27T10:00:00Z",
            "required_delivery_deadline_utc",
        )
        received = receive_loaner_set(api, tray_set["id"], "2026-09-27T08:00:00Z")
        assert received["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        return facility, vendor, first_request, first_product, case, tray_set

    @staticmethod
    def _supersede(api, vendor, facility, first_request):
        """Approve a successor request that supersedes the first one."""
        return approved_product(
            api,
            vendor["id"],
            facility["id"],
            "CP-C4-B",
            295000,
            is_implant=True,
            product_name="Cervical Plate C4 Rev B",
            manufacturer="Supralink",
            supersedes_request_id=first_request["id"],
        )

    def test_release_is_refused_once_the_successor_supersedes_the_product(self, api):
        """A set still sitting on time is refused because its product was superseded.

        "the referenced approved product must still be `ACTIVE`, else the release
        is refused with `ERR_PRODUCT_NOT_APPROVED`", and "the approved product
        belonging to that superseded predecessor, if it is currently `ACTIVE`,
        moves `ACTIVE → SUSPENDED` with `suspended_reason` set to `SUPERSEDED`.
        That supersession path deliberately does **not** hold any loaner sets".

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_superseded_product_returns_422
        """
        facility, vendor, first_request, first_product, case, tray_set = self._delivered_set(api)
        second_request, second_product = self._supersede(
            api, vendor, facility, first_request
        )

        validate_error(
            api.release_loaner_set(tray_set["id"], {}, STERILE_PROCESSING_TECH),
            ERR_PRODUCT_NOT_APPROVED,
        )

        superseded = read_approved_product(api, first_product["id"])
        assert superseded["status"] == PRODUCT_STATUS_SUSPENDED
        assert superseded["suspended_reason"] == SUSPENDED_REASON_SUPERSEDED

        successor = read_approved_product(api, second_product["id"])
        assert successor["status"] == PRODUCT_STATUS_ACTIVE
        assert successor["suspended_reason"] == SUSPENDED_REASON_NONE
        assert_instant_equals(
            successor["approval_expires_at_utc"],
            "2027-08-01T00:00:00Z",
            "approval_expires_at_utc",
        )

        # The set's own branch is untouched, so the loaner-set state rung cannot
        # have masked the referential refusal.
        stored_set = read_loaner_set(api, tray_set["id"])
        assert stored_set["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert_integer_field(stored_set, "late_minutes_current_basis", 0)
        assert read_case(api, case["id"])["implant_readiness_status"] == READINESS_PENDING

        stored_request = read_pir(api, second_request["id"])
        assert stored_request["status"] == PIR_STATUS_APPROVED
        assert stored_request["supersedes_request_id"] == first_request["id"]

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "open_pir_count", 0)
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 0)
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 100)

    def test_the_same_set_releases_while_its_product_stays_active(self, api):
        """With no successor request approved, the identical release call succeeds.

        "Both `DELIVERED_ON_TIME → RELEASED_TO_OR` and `DELIVERED_LATE →
        RELEASED_TO_OR` are admissible", and "if the case has at least one set
        and every one of them is `RELEASED_TO_OR`, the posture is `READY`".

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_superseded_product_returns_422
        """
        _facility, _vendor, _first_request, first_product, case, tray_set = self._delivered_set(api)

        released = release_loaner_set(api, tray_set["id"])
        assert released["status"] == LOANER_STATUS_RELEASED

        # The product the set carries is the only thing that differs from the
        # refused call, and it is still ACTIVE here.
        assert read_approved_product(api, first_product["id"])["status"] == PRODUCT_STATUS_ACTIVE
        assert read_case(api, case["id"])["implant_readiness_status"] == READINESS_READY

    def test_a_set_on_the_successor_product_releases_while_the_older_set_stays_blocked(self, api):
        """Two sets on one case diverge purely on which product each of them carries.

        "Registration is refused unless the referenced approved product is
        `ACTIVE`", and release likewise "requires the underlying approved product
        to still be `ACTIVE`", so the newly minted successor admits both.

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_superseded_product_returns_422
        """
        facility, vendor, first_request, _first_product, case, tray_set = self._delivered_set(api)
        _second_request, second_product = self._supersede(
            api, vendor, facility, first_request
        )

        successor_set = register_loaner_set(
            api, vendor["id"], case["id"], second_product["id"], 4, COMPLEXITY_SIMPLE
        )
        receive_loaner_set(api, successor_set["id"], "2026-09-27T09:00:00Z")
        released = release_loaner_set(api, successor_set["id"])
        assert released["status"] == LOANER_STATUS_RELEASED

        validate_error(
            api.release_loaner_set(tray_set["id"], {}, STERILE_PROCESSING_TECH),
            ERR_PRODUCT_NOT_APPROVED,
        )
        assert read_loaner_set(api, tray_set["id"])["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert read_case(api, case["id"])["implant_readiness_status"] == READINESS_PENDING
