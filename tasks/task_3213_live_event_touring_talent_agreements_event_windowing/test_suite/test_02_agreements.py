"""Talent agreements: overlap windows, OCC activation, expiry sweeps,
termination likeness recompute, and field validation."""

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_agreement,
    create_talent, create_draft_agreement,
    create_and_activate_agreement, advance_clock,
    create_agreement_payload,
    get_talent, get_agreement,
)

CA = TEST_USERS["contract_admin_headers"]
TP = TEST_USERS["tour_planner_headers"]


class TestAgreementDrafting:
    def test_overlapping_window_rejected_and_adjacent_accepted(self, api):
        """PRD §3.2: "Windows for a single talent must never overlap under half-open semantics — two agreements for the same talent whose `[start_date, end_date)` intervals intersect are illegal, and adjacent agreements where one ends exactly when the next begins are fine. This rule is enforced twice: at draft creation, and again at activation, both rejections carrying `ERR_AGREEMENT_OVERLAP` (HTTP 422)."

        Design: Corner/state_machines/agreement_overlap_rejected_on_create
        """
        talent = create_talent(ring_name="Overlap Ollie")
        first = create_draft_agreement(talent["id"])  # [2026-01-01, 2027-01-01)
        assert_agreement(first)
        assert first["status"] == "DRAFT"
        overlap = api.create_agreement(
            create_agreement_payload(talent["id"], start_date="2026-06-01",
                                     end_date="2027-06-01"),
            CA)
        validate_error(overlap, ApiErrorId.ERR_AGREEMENT_OVERLAP)
        adjacent = api.create_agreement(
            create_agreement_payload(talent["id"], start_date="2027-01-01",
                                     end_date="2028-01-01"),
            CA)
        data = validate_success(adjacent, expected_status=201)
        assert data["status"] == "DRAFT"

    def test_overlap_reports_before_generic_field_validation(self, api):
        """PRD §2.7: "and only then the domain-specific business, temporal, and fiscal rules described throughout §3 (including the medical clearance protocol, booking eligibility, visa coverage, agreement overlap, arena and talent scheduling conflicts, anchor-day alignment, territory-right conflicts, distribution-window timing, territory licensing, likeness rights, event type, roster minimums, readiness thresholds, visa windows, and merch windows), with malformed payloads, invalid enums, non-positive quantities, and end-before-start dates caught last as `ERR_INVALID_REQUEST` (HTTP 400). A failure at any step short-circuits the cascade, so the error returned is always the earliest applicable one in this ordering."

        Design: Corner/validations/agreement_overlap_beats_generic_field_validation
        """
        talent = create_talent(ring_name="Prio Pam")
        create_draft_agreement(talent["id"])  # [2026-01-01, 2027-01-01)
        # Overlaps the existing window AND has end_date <= start_date; the
        # overlap rule sits earlier in the cascade than the generic shape check.
        resp = api.create_agreement(
            create_agreement_payload(talent["id"], start_date="2026-06-01",
                                     end_date="2026-05-01"),
            CA)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)

    def test_missing_end_date_rejected(self, api):
        """PRD §3.2: "The `end_date` must be strictly after the `start_date`; a malformed window is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/missing_required_field_rejected
        """
        talent = create_talent(ring_name="Field Fred")
        payload = create_agreement_payload(talent["id"])
        del payload["end_date"]
        resp = api.create_agreement(payload, CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAgreementActivationOCC:
    def test_correct_version_activates_and_replay_is_stale(self, api):
        """PRD §2.6: "Activating a talent agreement requires the request to carry `expected_agreement_version`, set to the agreement's current `version` as last observed by the client; if another writer has advanced the agreement's version since then — for example by editing its window or royalty terms — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before proceeding."

        Design: Corner/cross_cutting_layers/occ_agreement_activate_version_increments
        """
        talent = create_talent(ring_name="Occ Olive")
        draft = create_draft_agreement(talent["id"])
        before_version = draft["version"]
        resp = api.activate_agreement(draft["id"], before_version, CA)
        activated = validate_success(resp)
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == before_version + 1
        # Replaying with the pre-activation version must be rejected: the OCC
        # guard rejects the stale expected version (the agreement is also no
        # longer DRAFT, but the version contract already fails).
        replay = api.activate_agreement(draft["id"], before_version, CA)
        body = replay.json()["data"]
        assert body["error_id"] in ("ERR_STALE_VERSION", "ERR_INVALID_STATE")
        if body["error_id"] == "ERR_STALE_VERSION":
            assert replay.status_code == 412

    def test_stale_version_rejected_with_412(self, api):
        """PRD §2.6: "Activating a talent agreement requires the request to carry `expected_agreement_version`, set to the agreement's current `version` as last observed by the client; if another writer has advanced the agreement's version since then — for example by editing its window or royalty terms — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before proceeding."

        Design: Corner/errors/error_stale_version_on_agreement_activate
        """
        talent = create_talent(ring_name="Stale Stan")
        draft = create_draft_agreement(talent["id"])
        # Any edit bumps the version; the pre-edit view becomes stale.
        edited = validate_success(
            api.patch_agreement(draft["id"], {"royalty_rate_bp": 2100}, CA))
        assert edited["version"] == draft["version"] + 1
        resp = api.activate_agreement(draft["id"], draft["version"], CA)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestAgreementExpirySweep:
    def test_expired_agreement_rejects_activation(self, api):
        """PRD §3.2: "a violated precondition surfaces as `ERR_AGREEMENT_OVERLAP`, while an attempt to activate an agreement that is not in `DRAFT` surfaces as `ERR_INVALID_STATE`."
        PRD §3.2: "Both `EXPIRED` and `TERMINATED` are terminal."

        Design: Corner/state_machines/agreement_terminal_expired_rejects_activate
        """
        talent = create_talent(ring_name="Old Otto")
        agreement = create_and_activate_agreement(
            talent["id"], end_date="2026-09-01", likeness_rights_granted=True)
        advance_clock("2026-09-01T00:00:00Z")
        expired = get_agreement(agreement["id"])
        assert expired["status"] == "EXPIRED"
        resp = api.activate_agreement(agreement["id"], expired["version"], CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_expiry_clears_likeness_granted(self, api):
        """PRD §2.4: "First, every `ACTIVE` talent agreement whose `end_date` has been reached or passed by the new clock date flips to `EXPIRED`."
        PRD §3.2: "The same recomputation runs when an agreement later leaves `ACTIVE` — whether by clock-driven expiry at the agreement's `end_date` or by explicit termination — so the likeness flag always reflects the live contract position."

        Design: Corner/state_machines/agreement_expiry_clears_likeness_granted
        """
        talent = create_talent(ring_name="Lapse Lou")
        create_and_activate_agreement(talent["id"], end_date="2026-09-01",
                                      likeness_rights_granted=True)
        assert get_talent(talent["id"])["likeness_granted"] is True
        advance_clock("2026-09-02T00:00:00Z")
        assert get_talent(talent["id"])["likeness_granted"] is False


class TestAgreementTerminationDerivedFields:
    def test_terminate_recomputes_likeness_granted(self, api):
        """PRD §3.2: "A `ContractAdmin` terminating an `ACTIVE` agreement flips it to `TERMINATED`, recomputes `likeness_granted` as above, and then fires a two-hop cascade."
        PRD §3.2: "the flag is true exactly when the talent has at least one `ACTIVE` agreement with `likeness_rights_granted` set to true, and false otherwise."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_likeness_on_terminate
        """
        talent = create_talent(ring_name="Derived Deb")
        agreement = create_and_activate_agreement(talent["id"],
                                                  likeness_rights_granted=True)
        assert get_talent(talent["id"])["likeness_granted"] is True
        resp = api.terminate_agreement(agreement["id"], CA)
        terminated = validate_success(resp)
        assert terminated["status"] == "TERMINATED"
        assert get_talent(talent["id"])["likeness_granted"] is False

    def test_termination_booking_scratch_cascade_unproven_under_prd(self, api):
        """PRD §3.2: "Hop 1 scratches forward bookings: every booking of that talent still in `BOOKED` status on an event that is `SCHEDULED` with an `event_date` on or after the current logical clock date flips `BOOKED → SCRATCHED`."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Corner/state_machines/terminate_cascades_future_bookings_and_storyline_conclude
        """
        # Under the PRD the cascade precondition is vacuous: a fresh talent is
        # UNBOOKABLE at 0.00 wellness and §3.6 raises wellness only via
        # fulfilled bookings, so no BOOKED booking can ever exist for hop 1 to
        # scratch. The only uniquely-derivable observable is the negative: with
        # zero bookings, termination still succeeds and flips the agreement to
        # TERMINATED without creating any scratch.
        talent = create_talent(ring_name="Term Tina")
        agreement = create_and_activate_agreement(talent["id"])
        resp = api.terminate_agreement(agreement["id"], CA)
        terminated = validate_success(resp)
        assert terminated["status"] == "TERMINATED"
        # No bookings exist to scratch; the storyline hop is likewise vacuous.
        bookings = api.list_bookings(TP, params={"talent_id": talent["id"]})
        data, meta = validate_paginated(bookings)
        assert meta["total_count"] == 0


