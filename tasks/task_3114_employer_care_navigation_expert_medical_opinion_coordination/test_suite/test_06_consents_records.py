"""Consents and record requests: scoped uniqueness, retry exhaustion, expiry
boundary, and the consent-loss cascade."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_consent_payload,
    set_clock, setup_employer_with_member, setup_provider,
    grant_consent, setup_record_request, setup_received_record_request,
    setup_navigation_case,
)
from test_helpers.test_users import (
    make_member_headers,
    make_records_specialist_headers,
    make_nurse_navigator_headers,
)


class TestConsentUniqueness:
    def test_consent_duplicate_active_scope_rejected(self, api):
        """PRD §2.8: "A member may hold at most one `ACTIVE` grant per scope; a
        second grant for the same scope is rejected with
        `ERR_CONSENT_ALREADY_ACTIVE` (409)."

        Design: Corner/entities/consent_duplicate_active_scope_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "APPOINTMENT_BOOKING",
                      expires_at="2027-01-01T00:00:00Z")

        dup = api.create_consent(
            member["id"],
            create_consent_payload(scope="APPOINTMENT_BOOKING",
                                   expires_at="2028-01-01T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_error(dup, ApiErrorId.ERR_CONSENT_ALREADY_ACTIVE,
                       expected_status=409)

        other = api.create_consent(
            member["id"],
            create_consent_payload(scope="BILLING_ADVOCACY",
                                   expires_at="2028-01-01T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_success(other, expected_status=201)


class TestRecordRequestRetries:
    def test_record_request_retry_cycle_with_exhaustion(self, api):
        """PRD §3.5: "It can be marked failed, moving to `FAILED`; and a failed
        request can be retried, moving back to `REQUESTED` — but only while
        `retry_count` is below two, so a third retry is rejected with
        `ERR_RETRY_EXHAUSTED` (422), and only while the member still holds an
        `ACTIVE` `RECORD_RETRIEVAL` consent (else `ERR_CONSENT_REQUIRED`). Each
        retry increments `retry_count`."

        Design: Corner/state_machines/record_request_retry_cycle_with_exhaustion
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "RECORD_RETRIEVAL")
        provider = setup_provider(name="Skynet Medical")
        rr = setup_record_request(member, provider)
        rs = make_records_specialist_headers("rs-1")

        validate_success(api.fail_record_request(rr["id"], rs))
        r1 = validate_success(api.retry_record_request(rr["id"], rs))
        assert r1["status"] == "REQUESTED"
        assert r1["retry_count"] == 1

        validate_success(api.fail_record_request(rr["id"], rs))
        r2 = validate_success(api.retry_record_request(rr["id"], rs))
        assert r2["status"] == "REQUESTED"
        assert r2["retry_count"] == 2

        validate_success(api.fail_record_request(rr["id"], rs))
        third = api.retry_record_request(rr["id"], rs)
        validate_error(third, ApiErrorId.ERR_RETRY_EXHAUSTED,
                       expected_status=422)
        current = validate_success(api.get_record_request(rr["id"], rs))
        assert current["status"] == "FAILED"
        assert current["retry_count"] == 2


class TestConsentCascade:
    def test_consent_revoke_cancels_requests_blocks_opinion_escalates_case(
            self, api, platform_admin_headers):
        """PRD §3.5: "when the member revokes their `RECORD_RETRIEVAL` consent
        — which stamps `revoked_at` with the logical clock time and moves the
        grant to `REVOKED` — or when that consent expires, every one of the
        member's requests still in `REQUESTED` moves to `CANCELLED`. Requests
        already `RECEIVED` or `FAILED` are untouched."
        PRD §3.5: "Cancellation of a pending request then propagates: for each
        of the member's expert opinion cases sitting in `RECORDS_COLLECTION`
        whose `attached_received_count` has fallen below three and which no
        longer has any request in `REQUESTED`, the case moves to
        `RECORDS_BLOCKED` — and that blockage escalates the linked navigation
        case per §3.3."

        Design: Difficulty/transitive_cascade/consent_revoke_cancels_requests_blocks_opinion_escalates_case
        """
        set_clock()
        _, member = setup_employer_with_member(emo_benefit_enabled=True)
        consent = grant_consent(member, "RECORD_RETRIEVAL")
        grant_consent(member, "EMO_REVIEW")

        nc = setup_navigation_case(
            member, {"question_type": "CLINICAL", "acuity": "MEDIUM"},
            navigator_id="nn-1", navigator_role="NurseNavigator", start=True)

        p1 = setup_provider(name="Spine Center A", specialty="NEUROSURGERY")
        p2 = setup_provider(name="Spine Center B", specialty="NEUROSURGERY")
        rr1 = setup_received_record_request(member, p1, pages=30)
        rr2 = setup_record_request(member, p2)

        emo = validate_success(api.create_expert_opinion(
            member["id"],
            {"condition_summary": "Disc herniation review",
             "navigation_case_id": nc["id"]},
            make_member_headers(member["id"])), expected_status=201)
        validate_success(api.attach_records(
            emo["id"], {"record_request_id": rr1["id"]},
            make_records_specialist_headers("rs-1")), expected_status=201)

        revoked = validate_success(api.revoke_consent(
            consent["id"], make_member_headers(member["id"])))
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_at"] == "2026-09-01T00:00:00Z"

        rs = make_records_specialist_headers("rs-1")
        rr2_after = validate_success(api.get_record_request(rr2["id"], rs))
        assert rr2_after["status"] == "CANCELLED"
        rr1_after = validate_success(api.get_record_request(rr1["id"], rs))
        assert rr1_after["status"] == "RECEIVED"

        emo_after = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert emo_after["status"] == "RECORDS_BLOCKED"

        nc_after = validate_success(api.get_navigation_case(
            nc["id"], make_nurse_navigator_headers("nn-1")))
        assert nc_after["status"] == "ESCALATED"
        assert nc_after["escalation_count"] == 1
        assert nc_after["assigned_user_id"] is None

    def test_consent_revoke_cascade_leaves_received_records_attached(
            self, api, platform_admin_headers):
        """PRD §3.5: "when the member revokes their `RECORD_RETRIEVAL` consent
        — which stamps `revoked_at` with the logical clock time and moves the
        grant to `REVOKED` — or when that consent expires, every one of the
        member's requests still in `REQUESTED` moves to `CANCELLED`. Requests
        already `RECEIVED` or `FAILED` are untouched."

        Design: Difficulty/transitive_cascade/consent_revoke_cancels_requests_blocks_opinion_escalates_case
        """
        set_clock()
        _, member = setup_employer_with_member(emo_benefit_enabled=True)
        consent = grant_consent(member, "RECORD_RETRIEVAL")
        grant_consent(member, "EMO_REVIEW")
        p1 = setup_provider(name="Spine Center A", specialty="NEUROSURGERY")
        rr1 = setup_received_record_request(member, p1, pages=30)
        emo = validate_success(api.create_expert_opinion(
            member["id"], {"condition_summary": "Disc herniation review"},
            make_member_headers(member["id"])), expected_status=201)
        validate_success(api.attach_records(
            emo["id"], {"record_request_id": rr1["id"]},
            make_records_specialist_headers("rs-1")), expected_status=201)

        validate_success(api.revoke_consent(
            consent["id"], make_member_headers(member["id"])))

        rr1_after = validate_success(api.get_record_request(
            rr1["id"], make_records_specialist_headers("rs-1")))
        assert rr1_after["status"] == "RECEIVED"

        items = validate_success(api.list_opinion_record_items(
            emo["id"], make_records_specialist_headers("rs-1")))
        assert [i["record_request_id"] for i in items] == [rr1["id"]]

    def test_consent_expiry_inclusive_boundary_at_exact_expires_at(
            self, api, platform_admin_headers):
        """PRD §2.8: "Expiry is driven by the logical clock: whenever the clock
        advances — and whenever a consent is read — any grant whose
        `expires_at` is at or before the current logical time transitions to
        `EXPIRED` (the boundary is inclusive: an `expires_at` exactly equal to
        now expires the grant)."

        Design: Corner/calculations/consent_expiry_inclusive_boundary_at_exact_expires_at
        """
        set_clock()
        _, member = setup_employer_with_member()
        consent = grant_consent(member, "RECORD_RETRIEVAL",
                                expires_at="2026-09-15T00:00:00Z")
        provider = setup_provider(name="Time Clinic")
        rr = setup_record_request(member, provider)

        set_clock("2026-09-14T23:59:59Z")
        rows = validate_success(api.list_consents(
            member["id"], make_member_headers(member["id"]),
            params={"scope": "RECORD_RETRIEVAL"}))
        assert rows[0]["status"] == "ACTIVE"

        set_clock("2026-09-15T00:00:00Z")
        rows2 = validate_success(api.list_consents(
            member["id"], make_member_headers(member["id"]),
            params={"scope": "RECORD_RETRIEVAL"}))
        assert rows2[0]["id"] == consent["id"]
        assert rows2[0]["status"] == "EXPIRED"

        rr_after = validate_success(api.get_record_request(
            rr["id"], make_records_specialist_headers("rs-1")))
        assert rr_after["status"] == "CANCELLED"

    def test_record_request_cancel_endpoint_drives_same_block_cascade(
            self, api, platform_admin_headers):
        """PRD §3.5: "A pending request can be cancelled directly by a records
        specialist, or automatically by the consent cascade".
        PRD §3.5: "Cancellation of a pending request then propagates: for each
        of the member's expert opinion cases sitting in `RECORDS_COLLECTION`
        whose `attached_received_count` has fallen below three and which no
        longer has any request in `REQUESTED`, the case moves to
        `RECORDS_BLOCKED`".

        Design: Corner/endpoints/record_request_cancel_endpoint_drives_same_block_cascade
        """
        set_clock()
        _, member = setup_employer_with_member(emo_benefit_enabled=True)
        grant_consent(member, "RECORD_RETRIEVAL")
        grant_consent(member, "EMO_REVIEW")
        provider = setup_provider(name="Cancel Clinic")
        rr_done = setup_received_record_request(member, provider, pages=5)
        rr_pend = setup_record_request(member, provider)

        emo = validate_success(api.create_expert_opinion(
            member["id"], {"condition_summary": "Cancel cascade test"},
            make_member_headers(member["id"])), expected_status=201)
        validate_success(api.attach_records(
            emo["id"], {"record_request_id": rr_done["id"]},
            make_records_specialist_headers("rs-1")), expected_status=201)

        cancelled = validate_success(api.cancel_record_request(
            rr_pend["id"], make_records_specialist_headers("rs-1")))
        assert cancelled["status"] == "CANCELLED"

        emo_after = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert emo_after["status"] == "RECORDS_BLOCKED"

    def test_cascade_side_effect_partial_state_unaffected(
            self, api, platform_admin_headers):
        """PRD §3.5: "every one of the member's requests still in `REQUESTED`
        moves to `CANCELLED`. Requests already `RECEIVED` or `FAILED` are
        untouched."

        Design: Corner/cross_cutting_layers/cascade_side_effect_partial_state_unaffected
        """
        set_clock()
        emp, m1 = setup_employer_with_member(member_overrides={
            "full_name": "Sel One", "external_member_ref": "SL-1"})
        m2 = validate_success(api.create_member(
            emp["id"],
            {"full_name": "Sel Two", "date_of_birth": "1981-01-01",
             "relationship": "SELF", "external_member_ref": "SL-2",
             "deductible_limit_cents": 100000, "oop_max_cents": 500000},
            platform_admin_headers), expected_status=201)

        cons1 = grant_consent(m1, "RECORD_RETRIEVAL")
        grant_consent(m2, "RECORD_RETRIEVAL")
        provider = setup_provider(name="Sel Clinic")

        r1 = setup_received_record_request(m1, provider, pages=1)
        r2 = setup_record_request(m1, provider)
        r3 = setup_record_request(m1, provider)
        validate_success(api.fail_record_request(
            r3["id"], make_records_specialist_headers("rs-1")))
        r4 = setup_record_request(m2, provider)

        validate_success(api.revoke_consent(
            cons1["id"], make_member_headers(m1["id"])))

        rs = make_records_specialist_headers("rs-1")
        assert validate_success(api.get_record_request(r2["id"], rs))["status"] == "CANCELLED"
        assert validate_success(api.get_record_request(r1["id"], rs))["status"] == "RECEIVED"
        assert validate_success(api.get_record_request(r3["id"], rs))["status"] == "FAILED"
        assert validate_success(api.get_record_request(r4["id"], rs))["status"] == "REQUESTED"
