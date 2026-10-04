"""Complaints: lifecycle transitions, the escalation thresholds, the
three-link cascade, and complaint listing."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    set_clock, get_provider, get_agreement,
    create_licensed_provider, create_active_agreement,
    setup_provider_with_active_agreement, setup_member_and_agreement,
    setup_suspended_provider_five_escalations,
    create_household_with_term, file_complaint_ok, adjudicate_ok,
    file_open_complaint, escalate_complaint_ok, escalate_n_complaints,
    create_complaint_payload, make_member_headers,
)

GOV = TEST_USERS["governance_officer_headers"]
OVA = TEST_USERS["oversight_analyst_headers"]
MSA = TEST_USERS["member_services_headers"]


class TestThirdEscalationBoundary:
    def _setup(self):
        provider, agreement, _hh, member_id = setup_member_and_agreement(
            "INSURANCE_LIFE", "Beacon Life Assurance", state_code="MI")
        c1 = file_open_complaint(member_id, agreement["id"], category="CLAIMS",
                                 severity="HIGH", description="boundary complaint 1")
        c2 = file_open_complaint(member_id, agreement["id"], category="CLAIMS",
                                 severity="HIGH", description="boundary complaint 2")
        c3 = file_open_complaint(member_id, agreement["id"], category="CLAIMS",
                                 severity="HIGH", description="boundary complaint 3")
        return provider, agreement, [c1, c2, c3]

    def test_first_two_escalations_do_not_cross_threshold(self, api):
        """PRD §3.5: "When that count reaches 3 — the comparison is
        at-least, so exactly 3 fires — and the agreement is `ACTIVE`, the
        agreement moves to `PROBATION` with `probation_count` incremented by
        one and `version` advanced."

        Design: Difficulty/boundary_precision_check/third_escalation_exactly_triggers_probation
        """
        set_clock()
        _provider, agreement, (c1, c2, _c3) = self._setup()
        escalate_complaint_ok(c1["id"])
        after_1 = get_agreement(agreement["id"])
        assert after_1["status"] == "ACTIVE"
        assert after_1["escalations_trailing_12mo"] == 1

        escalate_complaint_ok(c2["id"])
        after_2 = get_agreement(agreement["id"])
        assert after_2["status"] == "ACTIVE"
        assert after_2["escalations_trailing_12mo"] == 2

    def test_third_escalation_fires_auto_probation(self, api):
        """PRD §3.5: "the count of this agreement's complaints currently in
        `ESCALATED` status whose `escalated_at` is on or after the instant
        exactly 365 days before the logical clock". PRD §3.5: "When that
        count reaches 3 — the comparison is at-least, so exactly 3 fires —
        and the agreement is `ACTIVE`, the agreement moves to `PROBATION`
        with `probation_count` incremented by one and `version` advanced."

        Design: Difficulty/boundary_precision_check/third_escalation_exactly_triggers_probation
        """
        set_clock()
        _provider, agreement, (c1, c2, c3) = self._setup()
        escalate_complaint_ok(c1["id"])
        escalate_complaint_ok(c2["id"])
        escalate_complaint_ok(c3["id"])
        after_3 = get_agreement(agreement["id"])
        assert after_3["status"] == "PROBATION"
        assert after_3["escalations_trailing_12mo"] == 3
        assert after_3["probation_count"] == 1


class TestEscalationThreeHopCascade:
    def _setup_two_agreements(self):
        set_clock()
        provider = create_licensed_provider("Homeward Mutual Group")
        a1 = create_active_agreement(provider["id"], "INSURANCE_AUTO")
        a2 = create_active_agreement(provider["id"], "HOME_SERVICES")
        household, _term, member_id = create_household_with_term(
            state_code="WA", term_years=1, primary_full_name="Hank Hale",
            primary_date_of_birth="1955-11-11")
        return provider, a1, a2, member_id

    def test_mid_chain_agreement_probation_before_suspension(self, api):
        """PRD §3.5: "Link one recomputes the agreement's
        `escalations_trailing_12mo`: the count of this agreement's complaints
        currently in `ESCALATED` status whose `escalated_at` is on or after
        the instant exactly 365 days before the logical clock — the window
        bound is inclusive, so an escalation exactly 365 days old still
        counts." PRD §3.5: "When that count reaches 3 — the comparison is
        at-least, so exactly 3 fires — and the agreement is `ACTIVE`, the
        agreement moves to `PROBATION` with `probation_count` incremented by
        one and `version` advanced."

        Design: Difficulty/transitive_cascade/complaint_escalation_three_hop_cascade
        """
        provider, a1, _a2, member_id = self._setup_two_agreements()
        escalate_n_complaints(member_id, a1["id"], 3)
        a1_after = get_agreement(a1["id"])
        assert a1_after["status"] == "PROBATION"
        assert a1_after["probation_count"] == 1
        # Provider-wide count 3 is still below the suspension threshold.
        assert get_provider(provider["id"])["status"] == "LICENSED"

    def test_fifth_escalation_suspends_and_cascades_to_sibling(self, api):
        """PRD §3.5: "when that count reaches 5 — again, exactly 5 fires —
        and the provider is `LICENSED`, the provider moves to `SUSPENDED`
        with its `version` incremented by one." PRD §3.5: "every
        still-`ACTIVE` agreement of the newly suspended provider moves to
        `PROBATION` with `probation_count` incremented by one each, while
        agreements already in `PROBATION` or `TERMINATED` are left
        untouched."

        Design: Difficulty/transitive_cascade/complaint_escalation_three_hop_cascade
        """
        provider, a1, a2, member_id = self._setup_two_agreements()
        assert a2["version"] == 2
        escalate_n_complaints(member_id, a1["id"], 5)
        assert get_provider(provider["id"])["status"] == "SUSPENDED"

        a2_after = get_agreement(a2["id"])
        assert a2_after["status"] == "PROBATION"
        assert a2_after["probation_count"] == 1
        # create 1 -> activate 2 -> cascade 3.
        assert a2_after["version"] == 3

        a1_after = get_agreement(a1["id"])
        # Escalations 4 and 5 found A1 already PROBATION and did not re-fire.
        assert a1_after["probation_count"] == 1


class TestProviderSuspendReadmitCycle:
    def test_five_escalations_suspend_provider(self, api):
        """PRD §3.5: "Link two recomputes the provider's
        `escalations_trailing_12mo` the same way across all of the provider's
        agreements; when that count reaches 5 — again, exactly 5 fires — and
        the provider is `LICENSED`, the provider moves to `SUSPENDED` with
        its `version` incremented by one."

        Design: Difficulty/non_linear_state_machine/provider_license_suspend_readmit_cycle
        """
        set_clock()
        provider, agreement, _member_id, _complaints = (
            setup_suspended_provider_five_escalations())
        assert get_provider(provider["id"])["status"] == "SUSPENDED"
        # The single agreement auto-probated at its 3rd escalation.
        assert get_agreement(agreement["id"])["status"] == "PROBATION"

    def test_readmission_gated_by_inclusive_trailing_window(self, api):
        """PRD §3.5: "the window bound is inclusive, so an escalation exactly
        365 days old still counts." PRD §3.3: "a `SUSPENDED` provider may
        return to `LICENSED` only when its `escalations_trailing_12mo` has
        fallen below 5 at readmission time — otherwise the attempt is
        rejected with `ERR_REINSTATE_BLOCKED` (HTTP 422)." PRD §3.3:
        "Re-admission deliberately does not rehabilitate the provider's
        agreements: any agreement sitting in `PROBATION` stays there until
        its own reinstatement action clears it."

        Design: Difficulty/non_linear_state_machine/provider_license_suspend_readmit_cycle
        """
        set_clock()  # escalations stamped at 2026-09-01T00:00:00Z
        provider, agreement, _member_id, _complaints = (
            setup_suspended_provider_five_escalations())

        # Exactly 365 days later the escalations still count (inclusive).
        set_clock("2027-09-01T00:00:00Z")
        resp = api.admit_provider(provider["id"], GOV)
        validate_error(resp, ApiErrorId.ERR_REINSTATE_BLOCKED)

        # One day further the window has slid past them; re-admission clears.
        set_clock("2027-09-02T00:00:00Z")
        readmitted = validate_success(api.admit_provider(provider["id"], GOV))
        assert readmitted["status"] == "LICENSED"
        assert get_agreement(agreement["id"])["status"] == "PROBATION"


class TestEscalatePriorityPair:
    def _setup_resolved_complaint_terminated_agreement(self):
        set_clock()
        provider, agreement, _hh, member_id = setup_member_and_agreement(
            "FINANCIAL_SERVICES", "Sterling Financial Services", state_code="GA")
        complaint = file_complaint_ok(
            member_id, agreement["id"], category="BILLING", severity="LOW",
            description="fee dispute")
        adjudicate_ok(complaint["id"], "OPEN_REVIEW")
        adjudicate_ok(complaint["id"], "RESOLVE", resolution_code="REFUND_ISSUED")
        adjudicated = validate_success(api_client.get_complaint(complaint["id"], OVA))
        assert adjudicated["status"] == "RESOLVED"
        validate_success(
            api_client.transition_agreement(agreement["id"], {"action": "TERMINATE"}, GOV))
        return provider, agreement, complaint

    def test_state_error_beats_constraint_error_on_escalate(self, api):
        """PRD §2.8: "Every request passes through a fixed twelve-rung
        validation pipeline, evaluated in the order below." PRD §2.8: "A
        request that would fail several rungs is rejected with the error from
        the earliest rung it fails." PRD §2.8 rung 8: "complaint transition
        valid from the current status (`ERR_COMPLAINT_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_escalate
        """
        _provider, _agreement, complaint = (
            self._setup_resolved_complaint_terminated_agreement())
        resp = api.adjudicate_complaint(complaint["id"], {"action": "ESCALATE"}, OVA)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_STATE)

    def test_failed_escalate_leaves_resolved_complaint_untouched(self, api):
        """PRD §3.5: "Every other adjudication pairing — resolving from
        `FILED`, escalating from `ESCALATED` or `RESOLVED`, or acting on a
        `RESOLVED` complaint at all — is rejected with `ERR_COMPLAINT_STATE`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_escalate
        """
        _provider, _agreement, complaint = (
            self._setup_resolved_complaint_terminated_agreement())
        resp = api.adjudicate_complaint(complaint["id"], {"action": "ESCALATE"}, OVA)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_STATE)
        after = validate_success(api.get_complaint(complaint["id"], OVA))
        assert after["status"] == "RESOLVED"
        assert after["escalated_at"] is None


class TestComplaintTransitions:
    def test_resolve_from_filed_rejected(self, api):
        """PRD §3.5: "A successfully filed complaint starts in `FILED` with
        `filed_at` stamped from the logical clock, and creation returns HTTP
        201." PRD §3.5: "Every other adjudication pairing — resolving from
        `FILED`, escalating from `ESCALATED` or `RESOLVED`, or acting on a
        `RESOLVED` complaint at all — is rejected with `ERR_COMPLAINT_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/resolve_from_filed_rejected
        """
        set_clock()
        _provider, agreement, _hh, member_id = setup_member_and_agreement(
            "HOME_SERVICES", "Peak Home Services", state_code="WY")
        complaint = file_complaint_ok(
            member_id, agreement["id"], category="SERVICE", severity="LOW",
            description="slow callback")
        assert complaint["status"] == "FILED"
        resp = api.adjudicate_complaint(
            complaint["id"], {"action": "RESOLVE", "resolution_code": "EXPLAINED"},
            OVA)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_STATE)

    def test_resolving_escalated_complaint_clears_threshold_count(self, api):
        """PRD §3.5: "Resolution (`RESOLVE`) is a sibling pair: it is
        permitted from either `UNDER_REVIEW` or `ESCALATED`, lands in the
        terminal `RESOLVED` state, and records `resolution_code` when one is
        supplied." PRD §3.5: "Only complaints currently in `ESCALATED` status
        count toward either trailing threshold — a complaint resolved after
        escalation stops counting from the moment it resolves".

        Design: Corner/state_machines/escalated_complaint_resolve_clears_threshold_count
        """
        set_clock()
        _provider, agreement, _hh, member_id = setup_member_and_agreement(
            "INSURANCE_LIFE", "Golden Years Insurance", state_code="UT")
        complaint = file_open_complaint(
            member_id, agreement["id"], category="CLAIMS", severity="HIGH",
            description="claim mishandled")
        escalate_complaint_ok(complaint["id"])
        assert get_agreement(agreement["id"])["escalations_trailing_12mo"] == 1

        resolved = adjudicate_ok(complaint["id"], "RESOLVE",
                                 resolution_code="PROVIDER_FIXED")
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_code"] == "PROVIDER_FIXED"
        agreement_after = get_agreement(agreement["id"])
        assert agreement_after["escalations_trailing_12mo"] == 0
        assert agreement_after["status"] == "ACTIVE"


class TestComplaintFilingOwnership:
    def test_member_cannot_file_for_another_member(self, api):
        """PRD §3.5: "A `Member` files a complaint as themselves: the body's
        `member_id` must equal the caller's `X-User-ID` (a mismatch is
        `ERR_FORBIDDEN`)".

        Design: Corner/rbac/member_cannot_file_for_another_member
        """
        set_clock()
        _provider, agreement, _hh, m1 = setup_member_and_agreement(
            "INSURANCE_AUTO", "Watchdog Insurance", state_code="AL")
        _hh2, _t2, m2 = create_household_with_term(
            state_code="AL", term_years=1, primary_full_name="Cat Carr",
            primary_date_of_birth="1971-01-01")
        payload = create_complaint_payload(
            m2, agreement["id"], category="SERVICE", severity="LOW",
            description="impersonated filing")
        resp = api.file_complaint(payload, make_member_headers(m1))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows, meta = validate_paginated(
            api.list_complaints(OVA, params={"license_agreement_id": agreement["id"]}))
        assert len(rows) == 0
        assert meta["total_count"] == 0


class TestComplaintListing:
    def test_complaints_list_filters_and_pagination(self, api):
        """PRD §3.5: "The complaints listing supports optional `member_id`,
        `license_agreement_id`, and `status` filters." PRD §2.3: "The `limit`
        parameter specifies the maximum number of items to return: it
        defaults to 10 when not provided, with a minimum of 1 and a maximum
        of 100." PRD §2.3: "The `offset` parameter specifies the number of
        items to skip and defaults to 0."

        Design: Corner/endpoints/complaints_list_filters_and_pagination
        """
        set_clock()
        _provider, agreement, _hh1, m1 = setup_member_and_agreement(
            "FINANCIAL_SERVICES", "Ledger Insurance", state_code="NV")
        _hh2, _t2, m2 = create_household_with_term(
            state_code="NV", term_years=1, primary_full_name="Xia Xue",
            primary_date_of_birth="1973-03-03")
        file_complaint_ok(m1, agreement["id"], category="BILLING",
                          severity="LOW", description="fee question one")
        file_complaint_ok(m1, agreement["id"], category="SERVICE",
                          severity="LOW", description="fee question two")
        file_complaint_ok(m2, agreement["id"], category="CLAIMS",
                          severity="HIGH", description="claim delay")

        page1, meta1 = validate_paginated(api.list_complaints(
            OVA, params={"license_agreement_id": agreement["id"],
                         "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_complaints(
            OVA, params={"license_agreement_id": agreement["id"],
                         "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        by_member, meta_m = validate_paginated(
            api.list_complaints(OVA, params={"member_id": m1}))
        assert len(by_member) == 2
        assert meta_m["total_count"] == 2

        default_page, meta_d = validate_paginated(api.list_complaints(
            OVA, params={"license_agreement_id": agreement["id"]}))
        assert len(default_page) == 3
        assert meta_d["limit"] == 10
        assert meta_d["offset"] == 0

        under_review, meta_u = validate_paginated(
            api.list_complaints(OVA, params={"status": "UNDER_REVIEW"}))
        assert len(under_review) == 0
        assert meta_u["total_count"] == 0
