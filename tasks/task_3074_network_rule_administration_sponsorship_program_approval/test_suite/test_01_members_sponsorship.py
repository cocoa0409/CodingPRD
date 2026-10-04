"""Membership administration, sponsorship, and merchant boarding tests."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_member,
    create_active_member,
    create_member_payload,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OP = TEST_USERS["network_operator_headers"]
SM = TEST_USERS["sponsorship_manager_headers"]
FA = TEST_USERS["fraud_analyst_headers"]


class TestMemberCreation:
    def test_member_creation_defaults_and_system_fields(self, api):
        """PRD §3.1: "A financial institution enters the network when a
        `NetworkOperator` applies for principal membership on its behalf,
        supplying the institution's `legal_name`, its `member_kind` — one of
        `ISSUER`, `ACQUIRER`, or `BOTH`, immutable after creation — and its
        home regulatory `region` (one of `NA`, `EU`, `APAC`, `LATAM`, or
        `CEMEA`)."
        PRD §3.1: "The new `Member` begins life in `APPLICATION` status with a
        `settled_balance_cents` of zero and a null `suspension_reason`."
        PRD §2.5: "Every resource carries an `id` (a server-minted UUID string
        with no type prefix) and a `created_at` (an ISO 8601 UTC timestamp
        with three fractional digits, assigned at creation)."

        Design: Corner/entities/member_creation_defaults_and_system_fields
        """
        res = api.create_member(
            create_member_payload(legal_name="New Bank", member_kind="ISSUER",
                                  region="NA"), OP)
        data = validate_success(res, 201)
        assert_member(data)
        assert data["status"] == "APPLICATION"
        assert data["settled_balance_cents"] == 0
        assert data["suspension_reason"] is None
        assert data["version"] == 1

    def test_member_creation_invalid_enum_rejected(self, api):
        """PRD §3.1: "its `member_kind` — one of `ISSUER`, `ACQUIRER`, or
        `BOTH`, immutable after creation".
        PRD §2.7: "(7) structural field constraints such as code lengths,
        sponsor eligibility, and boarding linkage (`ERR_VALIDATION`)".
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        An out-of-enum `member_kind` is rejected; the PRD does not uniquely
        assign enum rejection to a single error id (§2.7 names structural
        constraints as `ERR_VALIDATION` while §5 reserves `ERR_INVALID_REQUEST`
        for malformed requests), so either is accepted.

        Design: Corner/entities/member_creation_invalid_enum_rejected
        """
        api.create_member(create_member_payload(member_kind="ISSUER"), OP)
        res = api.create_member(
            create_member_payload(legal_name="X", member_kind="OPERATOR"), OP)
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_VALIDATION, ApiErrorId.ERR_INVALID_REQUEST])

    def test_member_creation_missing_required_field(self, api):
        """PRD §3.1: "supplying the institution's `legal_name`, its
        `member_kind` — one of `ISSUER`, `ACQUIRER`, or `BOTH`, immutable
        after creation — and its home regulatory `region` (one of `NA`, `EU`,
        `APAC`, `LATAM`, or `CEMEA`)".
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/member_creation_missing_required_field
        """
        api.create_member(create_member_payload(member_kind="ISSUER"), OP)
        payload = {"legal_name": "X", "member_kind": "ISSUER"}
        res = api.create_member(payload, OP)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_not_found_on_unknown_member_id(self, api):
        """PRD §2.10: "The first identifier in the path that does not
        correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404)
        and no further validation occurs."

        Design: Corner/entities/not_found_on_unknown_member_id
        """
        api.create_member(create_member_payload(member_kind="ISSUER"), OP)
        res = api.get_member(NON_EXISTENT_UUID, OP)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_members_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, accepts a minimum of 1 and a maximum
        of 100."
        PRD §2.3: "Every list response reports `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` object of the
        envelope."

        Design: Corner/entities/members_list_pagination_envelope
        """
        api.create_member(create_member_payload(legal_name="P1",
                                                member_kind="ISSUER",
                                                region="NA"), OP)
        api.create_member(create_member_payload(legal_name="P2",
                                                member_kind="ACQUIRER",
                                                region="EU"), OP)
        res = api.list_members(OP, params={"limit": 1})
        data, meta = validate_paginated(res)
        assert len(data) == 1, f"Expected 1 row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestMemberLifecycle:
    def test_member_approve_from_active_rejected(self, api):
        """PRD §3.1: "Approval by a `NetworkOperator` moves the member from
        `APPLICATION` to `ACTIVE` and increments its `version`."
        PRD §2.7: "(5) the target resource being in a state from which the
        requested transition exists (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/member_approve_from_active_rejected
        """
        member = create_active_member(member_kind="BOTH")
        res = api.approve_member(member["id"], OP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_member(member["id"], OP))
        assert current["status"] == "ACTIVE"

    def test_member_terminal_lockdown(self, api):
        """PRD §3.1: "Termination is only available from `SUSPENDED`, is
        irreversible, and carries the member's still-suspended sponsored
        participants to `TERMINATED`; `TERMINATED` is terminal."
        PRD §2.7: "(5) the target resource being in a state from which the
        requested transition exists (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/member_terminal_lockdown
        """
        member = create_active_member(member_kind="BOTH")
        get_success_data(api.suspend_member(member["id"], {"reason": "R"}, OP))
        get_success_data(api.terminate_member(member["id"], OP))
        triggers = (
            lambda: api.suspend_member(member["id"], {"reason": "R"}, OP),
            lambda: api.reinstate_member(member["id"], OP),
            lambda: api.terminate_member(member["id"], OP),
        )
        for trigger in triggers:
            # All three transitions are absent from TERMINATED, so each must
            # draw ERR_INVALID_STATE — the state check (priority 5) precedes
            # structural payload validation (priority 7).
            validate_error(trigger(), ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_member(member["id"], OP))
        assert current["status"] == "TERMINATED"


class TestSuspensionCascade:
    def test_member_suspend_depth3_cascade(self, api):
        """PRD §2.8: "Suspending a member pushes `SUSPENDED` down through
        three hops: every participant it sponsors that is currently `ACTIVE`
        becomes `SUSPENDED`, every merchant operating under one of those
        just-suspended participants becomes `SUSPENDED`, and every BIN range
        the member owns as issuer that is currently `ACTIVE` becomes
        `SUSPENDED`."
        PRD §3.1: "Suspending an `ACTIVE` member requires a `reason` in the
        request, which is recorded into `suspension_reason`".

        Design: Difficulty/transitive_cascade/member_suspend_depth3_cascade
        """
        member = create_active_member(legal_name="Cascade Bank",
                                      member_kind="BOTH", region="APAC")
        participant = get_success_data(api.create_participant(
            {"name": "P Co", "sponsor_member_id": member["id"],
             "program_name": "PP"}, SM))
        get_success_data(api.approve_participant(participant["id"], SM))
        merchant = get_success_data(api.create_merchant(
            {"participant_id": participant["id"], "mcc": "5411",
             "region": "APAC", "declared_monthly_volume_cents": 10000000}, SM))

        res = api.suspend_member(member["id"], {"reason": "COMPLIANCE_HOLD"},
                                 OP)
        data = validate_success(res)
        assert data["status"] == "SUSPENDED"
        assert data["suspension_reason"] == "COMPLIANCE_HOLD"

        p_now = get_success_data(api.get_participant(participant["id"], OP))
        m_now = get_success_data(api.get_merchant(merchant["id"], OP))
        assert p_now["status"] == "SUSPENDED", \
            "participant must suspend as hop 1 of the cascade"
        assert m_now["status"] == "SUSPENDED", \
            "merchant must suspend as the depth-3 hop of the cascade"

    def test_member_suspend_cascade_preserves_unrelated_participants(self, api):
        """PRD §2.8: "Suspending a member pushes `SUSPENDED` down through
        three hops: every participant it sponsors that is currently `ACTIVE`
        becomes `SUSPENDED`".

        Design: Difficulty/transitive_cascade/member_suspend_depth3_cascade
        """
        suspended = create_active_member(legal_name="Cascade Bank",
                                         member_kind="BOTH", region="APAC")
        bystander = create_active_member(legal_name="Other Bank",
                                         member_kind="BOTH", region="APAC")
        p_hit = get_success_data(api.create_participant(
            {"name": "P Hit", "sponsor_member_id": suspended["id"],
             "program_name": "PP"}, SM))
        p_safe = get_success_data(api.create_participant(
            {"name": "P Safe", "sponsor_member_id": bystander["id"],
             "program_name": "PP"}, SM))
        get_success_data(api.approve_participant(p_hit["id"], SM))
        get_success_data(api.approve_participant(p_safe["id"], SM))

        validate_success(api.suspend_member(suspended["id"],
                                            {"reason": "COMPLIANCE_HOLD"}, OP))
        hit_now = get_success_data(api.get_participant(p_hit["id"], OP))
        safe_now = get_success_data(api.get_participant(p_safe["id"], OP))
        assert hit_now["status"] == "SUSPENDED"
        assert safe_now["status"] == "ACTIVE", \
            "the cascade must touch only the suspended member's own tree"


class TestSponsorship:
    def test_participant_registration_rejected_when_sponsor_not_active(self, api):
        """PRD §3.2: "the sponsor must be an `ACTIVE` member whose
        `member_kind` is `ACQUIRER` or `BOTH`, and a sponsor that fails either
        condition causes the registration to be rejected with
        `ERR_VALIDATION`."

        Design: Difficulty/cross_entity_state_dependency/participant_approval_gated_on_sponsor_member_state
        """
        # Sponsor still in APPLICATION (never approved): registration fails.
        member = get_success_data(api.create_member(
            {"legal_name": "Sponsor Bank", "member_kind": "ACQUIRER",
             "region": "LATAM"}, OP))
        res = api.create_participant(
            {"name": "P Co", "sponsor_member_id": member["id"],
             "program_name": "PP"}, SM)
        validate_error(res, ApiErrorId.ERR_VALIDATION)

        # An ACTIVE sponsor of kind ISSUER fails the second condition.
        issuer = create_active_member(legal_name="Issuer Only Bank",
                                      member_kind="ISSUER", region="LATAM")
        res = api.create_participant(
            {"name": "P Co", "sponsor_member_id": issuer["id"],
             "program_name": "PP"}, SM)
        validate_error(res, ApiErrorId.ERR_VALIDATION)

        # Once the sponsor is ACTIVE and of an eligible kind, the identical
        # registration succeeds and the participant starts in PENDING_REVIEW.
        get_success_data(api.approve_member(member["id"], OP))
        res = api.create_participant(
            {"name": "P Co", "sponsor_member_id": member["id"],
             "program_name": "PP"}, SM)
        data = validate_success(res, 201)
        assert data["status"] == "PENDING_REVIEW"

    def test_participant_approve_rejected_when_sponsor_suspended(self, api):
        """PRD §3.2: "Approval by a `SponsorshipManager` moves the participant
        from `PENDING_REVIEW` to `ACTIVE`, but only while the sponsoring
        member is itself `ACTIVE`; if the sponsor has been suspended in the
        meantime the approval is rejected with `ERR_SPONSOR_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/participant_approval_gated_on_sponsor_member_state
        """
        member = create_active_member(member_kind="ACQUIRER", region="LATAM")
        participant = get_success_data(api.create_participant(
            {"name": "P Co", "sponsor_member_id": member["id"],
             "program_name": "PP"}, SM))
        get_success_data(api.suspend_member(member["id"], {"reason": "R"}, OP))
        res = api.approve_participant(participant["id"], SM)
        validate_error(res, ApiErrorId.ERR_SPONSOR_INACTIVE)
        p_now = get_success_data(api.get_participant(participant["id"], SM))
        assert p_now["status"] == "PENDING_REVIEW"


class TestMerchantBoarding:
    def test_merchant_xor_boarding_constraint(self, api):
        """PRD §3.2: "Merchants board in one of exactly two ways, and exactly
        one of the two linkage fields must be non-null on creation: a merchant
        boards under a participant via `participant_id`, or directly under an
        acquirer member via `acquirer_member_id`. A payload that sets both, or
        neither, is rejected with `ERR_VALIDATION`".

        Design: Corner/entities/merchant_xor_boarding_constraint
        """
        member = create_active_member(legal_name="A Bank",
                                      member_kind="ACQUIRER", region="NA")
        participant = get_success_data(api.create_participant(
            {"name": "P Co", "sponsor_member_id": member["id"],
             "program_name": "PP"}, SM))
        get_success_data(api.approve_participant(participant["id"], SM))

        # Both linkage fields set -> rejected.
        res = api.create_merchant(
            {"participant_id": participant["id"],
             "acquirer_member_id": member["id"], "mcc": "5411", "region": "NA",
             "declared_monthly_volume_cents": 1000000}, SM)
        validate_error(res, ApiErrorId.ERR_VALIDATION)

        # Neither linkage field set -> rejected.
        res = api.create_merchant(
            {"mcc": "5411", "region": "NA",
             "declared_monthly_volume_cents": 1000000}, SM)
        validate_error(res, ApiErrorId.ERR_VALIDATION)

    def test_participant_computed_fraud_count_increments(self, api):
        """PRD §3.2: "Each participant carries a computed
        `fraud_attributed_count`, starting at zero, that increments by one
        every time a fraud case against one of its merchants is confirmed."
        PRD §3.8: "when the merchant's `participant_id` is non-null, that
        participant's `fraud_attributed_count` increments by one."

        Design: Corner/entities/participant_computed_fraud_count_increments
        """
        acquirer = create_active_member(legal_name="A Bank",
                                        member_kind="ACQUIRER", region="NA")
        participant = get_success_data(api.create_participant(
            {"name": "P Co", "sponsor_member_id": acquirer["id"],
             "program_name": "PP"}, SM))
        get_success_data(api.approve_participant(participant["id"], SM))
        merchant = get_success_data(api.create_merchant(
            {"participant_id": participant["id"], "mcc": "5411",
             "region": "NA", "declared_monthly_volume_cents": 5000000}, SM))
        case = get_success_data(api.create_fraud_case(
            {"merchant_id": merchant["id"],
             "reported_by_member_id": acquirer["id"],
             "fraud_amount_cents": 2000}, FA))

        before = get_success_data(api.get_participant(participant["id"], FA))
        assert before["fraud_attributed_count"] == 0

        validate_success(api.confirm_fraud_case(case["id"], FA))
        after = get_success_data(api.get_participant(participant["id"], FA))
        assert after["fraud_attributed_count"] == 1

    def test_reverse_reachability_lists_children(self, api):
        """PRD §4: "GET | `/network/members/{id}/participants` | List
        participants sponsored by this member".
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by `created_at` in ascending order."

        Design: Corner/endpoints/reverse_reachability_lists_children
        """
        m1 = create_active_member(legal_name="B1", member_kind="ACQUIRER",
                                  region="NA")
        m2 = create_active_member(legal_name="B2", member_kind="ACQUIRER",
                                  region="EU")
        p1 = get_success_data(api.create_participant(
            {"name": "P1", "sponsor_member_id": m1["id"],
             "program_name": "x"}, SM))
        p2 = get_success_data(api.create_participant(
            {"name": "P2", "sponsor_member_id": m1["id"],
             "program_name": "y"}, SM))
        get_success_data(api.create_participant(
            {"name": "P3", "sponsor_member_id": m2["id"],
             "program_name": "z"}, SM))

        res = api.list_member_participants(m1["id"], SM)
        data, meta = validate_paginated(res)
        ids = {row["id"] for row in data}
        assert ids == {p1["id"], p2["id"]}, \
            f"Expected exactly P1 and P2, got {ids}"
        assert meta["total_count"] == 2
