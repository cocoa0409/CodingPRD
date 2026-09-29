"""Chains that travel hop by hop from a lapsed attestation and from a finding.

One sweep call at the instant an influenza attestation lapses walks the whole
access aggregate — credential, representative, authorization, badge, vendor — and
one substantiated finding walks the product and instrument aggregate instead —
product, tray set, case readiness — without ever touching the representative.
"""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    ACCESS_STATUS_PENDING,
    ACCESS_STATUS_SUSPENDED,
    AUTH_STATUS_REVOKED,
    BADGE_STATUS_ISSUED,
    BADGE_STATUS_VOIDED,
    COMPLEXITY_SIMPLE,
    COMPLIANCE_ADMIN,
    COVERAGE_COVERED,
    COVERAGE_NOT_REQUIRED,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_COI,
    CREDENTIAL_TYPE_INFLUENZA,
    FEE_STATUS_NONE,
    INCIDENT_STATUS_SUBSTANTIATED,
    INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
    LOANER_STATUS_DELIVERED_ON_TIME,
    LOANER_STATUS_HELD,
    OR_COORDINATOR,
    OUTCOME_SUBSTANTIATED,
    POSTURE_COMPLIANT,
    POSTURE_LAPSED,
    PRODUCT_STATUS_ACTIVE,
    PRODUCT_STATUS_SUSPENDED,
    READINESS_BLOCKED,
    READINESS_PENDING,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    REVOKED_REASON_REP_SUSPENDED,
    SEVERITY_MAJOR,
    STATUS_IN_GOOD_STANDING,
    SUSPENDED_REASON_INCIDENT,
    SUSPENSION_REASON_CREDENTIAL_LAPSED,
    SUSPENSION_REASON_NONE,
    TIER_PLATINUM,
    adjudicate_incident,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    check_in,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    decide_authorization,
    file_credential,
    find_by_id,
    list_rows,
    make_vendor_admin_headers,
    read_approved_product,
    read_authorization,
    read_case,
    read_check_in,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    report_incident,
    request_authorization,
    run_sweep,
    set_clock,
    verify_credential,
)


class TestSweepCredentialExpiryCascade:
    """A lapsing influenza shot reaches all the way to the badge in one sweep call."""

    @staticmethod
    def _read_credential(api, rep_id, credential_id):
        """Read one attestation back through the representative's credential listing."""
        rows = list_rows(api.list_rep_credentials(rep_id, COMPLIANCE_ADMIN))
        return find_by_id(rows, credential_id)

    @staticmethod
    def _setup(api):
        """Stage a badged representative whose influenza shot lapses at 08:45."""
        facility = create_facility(
            api,
            "WD-07",
            name="Westdale General Hospital",
            spd_turnaround_hours=6,
            spd_bay_count=3,
        )
        vendor = create_vendor(api, "ENDOS", legal_name="Endoscopia Systems BV")
        rep = create_vendor_rep(api, vendor["id"], "Lena Fischer")

        influenza = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc="2025-10-01T08:45:00Z",
            expires_at_utc="2026-10-01T08:45:00Z",
            document_reference="IMM-LENA-01",
        )
        verify_credential(api, influenza["id"])
        for credential_type, reference in (
            (CREDENTIAL_TYPE_BLOODBORNE, "BBP-LENA-01"),
            (CREDENTIAL_TYPE_BACKGROUND, "BGC-LENA-01"),
            (CREDENTIAL_TYPE_COI, "COI-LENA-01"),
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

        # At the startup instant the influenza shot is still 61 days out, so the
        # whole gating set is covered and the representative may be put on a case.
        cleared = read_vendor_rep(api, rep["id"])
        assert cleared["credential_posture"] == POSTURE_COMPLIANT
        assert cleared["access_status"] == ACCESS_STATUS_CREDENTIALED

        case = create_case(
            api,
            facility["id"],
            "CASE-9501",
            "2026-10-01T09:00:00Z",
            "2026-10-01T11:00:00Z",
            procedure_name="Diagnostic Colonoscopy Suite Support",
        )
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_TECHNICAL_SUPPORT,
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        authorization = decide_authorization(
            api, requested["id"], "APPROVE", headers=OR_COORDINATOR
        )
        assert_instant_equals(
            authorization["badge_window_start_utc"],
            "2026-10-01T08:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            authorization["badge_window_end_utc"],
            "2026-10-01T11:30:00Z",
            "badge_window_end_utc",
        )

        # The representative badges in half an hour before the knife, while every
        # attestation is still live, so a badge is in hand before anything lapses.
        set_clock(api, "2026-10-01T08:30:00Z")
        badge = check_in(api, authorization["id"], rep["id"])
        assert badge["badge_status"] == BADGE_STATUS_ISSUED

        # Moving the clock onto the expiry instant itself transitions nothing:
        # every ageing decision in this system is taken by the sweep.
        set_clock(api, "2026-10-01T08:45:00Z")
        still_live = read_vendor_rep(api, rep["id"])
        assert still_live["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert still_live["credential_posture"] == POSTURE_COMPLIANT
        pre_sweep_case = read_case(api, case["id"])
        assert pre_sweep_case["vendor_coverage_status"] == COVERAGE_COVERED

        return vendor, rep, case, authorization, badge, influenza

    def test_expiry_at_the_boundary_lapses_the_posture_and_suspends_the_rep(self, api):
        """The first three hops: the shot expires, the posture lapses, access is suspended.

        "Every `VERIFIED` credential whose `expires_at_utc` is at or before
        `swept_at_utc` moves to `EXPIRED` — equality expires, the boundary is
        inclusive", and then "a `CREDENTIALED` representative whose posture is now
        `LAPSED` moves `CREDENTIALED → SUSPENDED` with `suspension_reason` set to
        `CREDENTIAL_LAPSED`, incrementing `reps_suspended_count`".

        Design: Difficulty/transitive_cascade/sweep_credential_expiry_cascades_five_hops_to_voided_badge
        """
        _vendor, rep, _case, _authorization, _badge, influenza = self._setup(api)

        sweep = run_sweep(api)

        lapsed = self._read_credential(api, rep["id"], influenza["id"])
        assert lapsed["status"] == "EXPIRED", (
            "an attestation whose expiry instant equals the observation instant expires"
        )

        suspended = read_vendor_rep(api, rep["id"])
        assert suspended["credential_posture"] == POSTURE_LAPSED, (
            "one uncovered gating type on a rep that was once cleared reads LAPSED"
        )
        assert suspended["access_status"] == ACCESS_STATUS_SUSPENDED
        assert suspended["suspension_reason"] == SUSPENSION_REASON_CREDENTIAL_LAPSED

        assert_integer_field(sweep, "credentials_expired_count", 1)
        assert_integer_field(sweep, "credentials_warned_count", 0)
        assert_integer_field(sweep, "reps_suspended_count", 1)

    def test_suspension_revokes_the_future_authorization_and_voids_the_badge(self, api):
        """The last two hops: the approval is revoked and its badge is voided, not expired.

        "Every badge voided as a consequence of a phase-4 revocation increments
        `badges_voided_count`", while "a badge voided in phase 4 is already out of
        `ISSUED` and cannot also be expired here, so the two badge counters never
        double-count the same row" — even though this badge's own window had
        closed too.

        Design: Difficulty/transitive_cascade/sweep_credential_expiry_cascades_five_hops_to_voided_badge
        """
        _vendor, rep, case, authorization, badge, _influenza = self._setup(api)

        sweep = run_sweep(api)

        revoked = read_authorization(api, authorization["id"])
        assert revoked["status"] == AUTH_STATUS_REVOKED
        assert revoked["revoked_reason"] == REVOKED_REASON_REP_SUSPENDED

        voided = read_check_in(api, badge["id"])
        assert voided["badge_status"] == BADGE_STATUS_VOIDED, (
            "the badge left ISSUED through the revocation path, not the expiry path"
        )

        assert_integer_field(sweep, "authorizations_revoked_count", 1)
        assert_integer_field(sweep, "badges_voided_count", 1)
        assert_integer_field(sweep, "badges_expired_count", 0)

        stored_rep = read_vendor_rep(api, rep["id"])
        assert_integer_field(stored_rep, "open_authorization_count", 0)

        stored_case = read_case(api, case["id"])
        assert_integer_field(stored_case, "approved_rep_count", 0)
        assert_integer_field(stored_case, "revoked_authorization_count", 1)
        assert stored_case["vendor_coverage_status"] == COVERAGE_NOT_REQUIRED, (
            "with no approved cover left, a case that needs no implant reads NOT_REQUIRED"
        )

    def test_rescoring_charges_the_lapsed_rep_and_hands_the_quota_slot_back(self, api):
        """The counter fan-out: one lapsed representative costs six points and no overage.

        The rescoring takes "the lapsed-representative count as the number of this
        vendor's representatives whose `credential_posture` is `LAPSED` **after**
        phase 3 has run", and the revocation of the only approval means
        `authorizations_used_epoch` is already back to zero when the ratio is taken.

        Design: Difficulty/transitive_cascade/sweep_credential_expiry_cascades_five_hops_to_voided_badge
        """
        vendor, _rep, _case, _authorization, _badge, _influenza = self._setup(api)

        sweep = run_sweep(api)
        assert_integer_field(sweep, "epoch_number", 1)
        assert_integer_field(sweep, "vendors_rescored_count", 1)

        rescored = read_vendor(api, vendor["id"])
        assert_integer_field(rescored, "adjudicated_compliance_score", 94)
        assert rescored["scorecard_tier"] == TIER_PLATINUM
        assert_integer_field(rescored, "access_quota_in_effect", 6)
        assert_integer_field(rescored, "authorizations_used_epoch", 0)
        assert rescored["compliance_status"] == STATUS_IN_GOOD_STANDING
        assert_integer_field(rescored, "last_sweep_epoch", 1)


class TestIncidentSubstantiationCascade:
    """A substantiated finding walks the product aggregate and leaves the rep alone."""

    @staticmethod
    def _setup(api):
        """Stage an on-time tray set and a MAJOR finding against the implant it carries."""
        facility = create_facility(
            api,
            "HS-08",
            name="Hillside Orthopaedic Hospital",
            spd_turnaround_hours=8,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "ORTHOP", legal_name="Orthoprime Trauma Inc")
        # The representative is deliberately left uncredentialed: reporting a
        # finding against somebody does not require that somebody to hold a badge.
        rep = create_vendor_rep(api, vendor["id"], "Sam Okoye")
        assert rep["access_status"] == ACCESS_STATUS_PENDING

        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "TN-T7-330",
            380000,
            is_implant=True,
            product_name="Tibial Nail System T7",
            manufacturer="Orthoprime",
        )
        assert product["status"] == PRODUCT_STATUS_ACTIVE

        case = create_case(
            api,
            facility["id"],
            "CASE-9601",
            "2026-09-20T10:00:00Z",
            "2026-09-20T14:00:00Z",
            procedure_name="Tibial Nailing",
            implant_required=True,
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 4, COMPLEXITY_SIMPLE
        )
        # Eight turnaround hours plus two for a SIMPLE reprocess and no tray
        # surcharge is ten, which the implant floor of twenty-four hours overrides.
        assert_instant_equals(
            loaner["required_delivery_deadline_utc"],
            "2026-09-19T10:00:00Z",
            "required_delivery_deadline_utc",
        )
        received = receive_loaner_set(api, loaner["id"], "2026-09-19T09:00:00Z")
        assert received["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert received["fee_status"] == FEE_STATUS_NONE

        staged_case = read_case(api, case["id"])
        assert staged_case["implant_readiness_status"] == READINESS_PENDING, (
            "an implant case whose only tray set is received but not released is PENDING"
        )

        incident = report_incident(
            api,
            case["id"],
            rep["id"],
            INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
            SEVERITY_MAJOR,
            headers=OR_COORDINATOR,
            approved_product_id=product["id"],
            narrative="Nail of a non-catalogued length opened from the loaner set.",
        )
        assert_integer_field(incident, "score_weight", 8)

        return vendor, rep, case, product, loaner, incident

    def test_substantiation_suspends_the_product_and_holds_the_tray_set(self, api):
        """The first three hops: the finding stands, the implant is suspended, the trays are held.

        "Because the incident names an `approved_product_id`, that approved product
        moves `ACTIVE → SUSPENDED` with `suspended_reason` set to
        `INCIDENT_SUBSTANTIATED`. Because that product is now suspended, every
        loaner set referencing it whose `status` is `EXPECTED`,
        `DELIVERED_ON_TIME` or `DELIVERED_LATE` moves to `HELD`".

        Design: Difficulty/transitive_cascade/incident_substantiation_cascades_four_hops_to_blocked_case
        """
        _vendor, _rep, _case, product, loaner, incident = self._setup(api)

        adjudicated = adjudicate_incident(
            api, incident["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN
        )
        assert adjudicated["status"] == INCIDENT_STATUS_SUBSTANTIATED
        assert adjudicated["adjudicated_outcome"] == OUTCOME_SUBSTANTIATED

        suspended = read_approved_product(api, product["id"])
        assert suspended["status"] == PRODUCT_STATUS_SUSPENDED
        assert suspended["suspended_reason"] == SUSPENDED_REASON_INCIDENT

        held = read_loaner_set(api, loaner["id"])
        assert held["status"] == LOANER_STATUS_HELD, (
            "a set delivered on time is still pulled out of its branch by the hold"
        )
        assert_instant_equals(
            held["required_delivery_deadline_utc"],
            "2026-09-19T10:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_integer_field(held, "late_minutes_current_basis", 0)
        assert_money_cents(held, "assessed_late_fee_cents", 0)

    def test_the_hold_blocks_the_case_and_scores_the_vendor_without_touching_the_rep(
        self, api
    ):
        """The fourth hop blocks the case, the score adopts the weight, the rep stands still.

        "if any set of the case is `HELD` or `REJECTED_LATE`, the posture is
        `BLOCKED`", and "a substantiated `MAJOR` unapproved-product-use incident
        ... does not suspend the representative", so the eight points land on the
        vendor and nowhere else.

        Design: Difficulty/transitive_cascade/incident_substantiation_cascades_four_hops_to_blocked_case
        """
        vendor, rep, case, _product, _loaner, incident = self._setup(api)

        before = read_vendor(api, vendor["id"])
        assert_integer_field(before, "adjudicated_compliance_score", 100)
        assert_integer_field(before, "provisional_compliance_score", 92)

        adjudicate_incident(api, incident["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN)

        blocked = read_case(api, case["id"])
        assert blocked["implant_readiness_status"] == READINESS_BLOCKED

        scored = read_vendor(api, vendor["id"])
        assert_integer_field(scored, "adjudicated_compliance_score", 92)
        assert_integer_field(scored, "provisional_compliance_score", 92)
        assert_money_cents(scored, "late_fee_balance_cents", 0)

        untouched = read_vendor_rep(api, rep["id"])
        assert untouched["access_status"] == ACCESS_STATUS_PENDING, (
            "only a CRITICAL unapproved-product-use finding reaches the rep lifecycle"
        )
        assert untouched["suspension_reason"] == SUSPENSION_REASON_NONE
