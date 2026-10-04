"""Partner lifecycle, credit box windows and OCC, supersede chains, and the
partner offboard cascade into boxes and securitization pools."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_partner,
    attach_active_credit_box,
    create_active_model,
    create_credit_box_payload,
    create_partner,
    create_securitization_pool_payload,
    get_success_data,
    setup_funded_loan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPartnerRetrieval:

    def test_partner_get_returns_stored_fields_unchanged(self, api, partner_admin_headers,
                                                         auditor_headers):
        """PRD 3.3: "A `PartnerAdmin` onboards a funding partner by registering its `legal_name`, its `partner_type` - one of `BANK`, `CREDIT_UNION`, `LOAN_BUYER`, or `SECURITIZATION_TRUST` - and the two-letter `home_state` of its charter. A new partner begins in `ONBOARDING`"
        PRD 3.3: "the partner's `funded_balance_cents` - the sum of `principal_cents` across all loans the partner currently holds in `CURRENT`, `DELINQUENT`, or `CHARGED_OFF` status"

        Design: Corner/entities/partner_get_returns_stored_fields_unchanged
        """
        partner = create_partner(
            legal_name="Roundtrip CU", partner_type="CREDIT_UNION", home_state="WA",
            activated=False,
        )
        resp = api.get_partner(partner["id"], auditor_headers)
        data = validate_success(resp, expected_status=200)
        assert_partner(data)
        assert data["legal_name"] == "Roundtrip CU"
        assert data["partner_type"] == "CREDIT_UNION"
        assert data["home_state"] == "WA"
        assert data["status"] == "ONBOARDING"
        assert data["originated_this_month_count"] == 0
        assert data["funded_balance_cents"] == 0
        assert data["active_credit_box_id"] is None


class TestCreditBoxRetrieval:

    def test_credit_box_get_with_unknown_id_returns_not_found(self, api, auditor_headers):
        """PRD 2.7: "The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)"
        PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/credit_box_get_with_unknown_id_returns_not_found
        """
        resp = api.get_credit_box("00000000-0000-4000-8000-0000000000ff", auditor_headers)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.json()["response_type"] == "error"
        assert err.get("message"), "error data must carry a human-readable message"


class TestCreditBoxActivationWindow:

    def test_activation_one_second_past_window_rejected_then_boundary_succeeds(
        self, api, partner_admin_headers, platform_admin_headers
    ):
        """PRD 3.3: "requires the logical clock to read within the inclusive window from `effective_from` to `effective_to` - outside it the attempt fails with `ERR_CREDIT_BOX_NOT_IN_WINDOW`"

        Design: Difficulty/resource_temporal_overlap/credit_box_activation_window_rejects_outside_clock
        """
        partner = create_partner(legal_name="Window Bank")
        resp = api.create_credit_box(
            partner["id"],
            create_credit_box_payload(
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z",
            ),
            partner_admin_headers,
        )
        box = validate_success(resp, expected_status=201)

        # One second past effective_to: outside the inclusive window.
        validate_success(
            api.set_clock({"to_iso8601": "2026-09-01T00:00:01Z"}, platform_admin_headers)
        )
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        resp = api.activate_credit_box(
            partner["id"], box["id"],
            {"expected_partner_version": partner["version"]},
            partner_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_BOX_NOT_IN_WINDOW)

        # Exactly at effective_to: the boundary is inclusive.
        validate_success(
            api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, platform_admin_headers)
        )
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        resp = api.activate_credit_box(
            partner["id"], box["id"],
            {"expected_partner_version": partner["version"]},
            partner_admin_headers,
        )
        box = validate_success(resp, expected_status=200)
        assert box["status"] == "ACTIVE"
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["active_credit_box_id"] == box["id"]

    def test_activation_before_window_also_rejected(
        self, api, partner_admin_headers, platform_admin_headers
    ):
        """PRD 3.3: "requires the logical clock to read within the inclusive window from `effective_from` to `effective_to` - outside it the attempt fails with `ERR_CREDIT_BOX_NOT_IN_WINDOW`"

        Design: Difficulty/resource_temporal_overlap/credit_box_activation_window_rejects_outside_clock
        """
        partner = create_partner(legal_name="Early Window Bank")
        resp = api.create_credit_box(
            partner["id"],
            create_credit_box_payload(
                effective_from="2026-09-02T00:00:00Z",   # starts after the default clock
                effective_to="2026-12-31T00:00:00Z",
            ),
            partner_admin_headers,
        )
        box = validate_success(resp, expected_status=201)
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        resp = api.activate_credit_box(
            partner["id"], box["id"],
            {"expected_partner_version": partner["version"]},
            partner_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_BOX_NOT_IN_WINDOW)
        box = get_success_data(api.get_credit_box(box["id"], partner_admin_headers))
        assert box["status"] == "DRAFT"


class TestCreditBoxPartnerGate:

    def test_activation_rejected_while_partner_suspended(
        self, api, partner_admin_headers
    ):
        """PRD 3.3: "Activating a draft box requires the owning partner to be `ACTIVE`"
        PRD 3.3: "Any lifecycle call against a partner not in the state the transition requires fails with `ERR_PARTNER_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/credit_box_activation_gated_by_partner_state
        """
        partner = create_partner(legal_name="Gate Bank")
        resp = api.create_credit_box(
            partner["id"], create_credit_box_payload(), partner_admin_headers
        )
        box = validate_success(resp, expected_status=201)
        validate_success(api.suspend_partner(partner["id"], partner_admin_headers))

        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        resp = api.activate_credit_box(
            partner["id"], box["id"],
            {"expected_partner_version": partner["version"]},
            partner_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PARTNER_INVALID_STATE)
        box = get_success_data(api.get_credit_box(box["id"], partner_admin_headers))
        assert box["status"] == "DRAFT"
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["active_credit_box_id"] is None

    def test_activation_succeeds_again_after_reactivation(
        self, api, partner_admin_headers
    ):
        """PRD 3.3: "Activating a draft box requires the owning partner to be `ACTIVE`"
        PRD 3.3: "An active partner may be suspended and later reactivated"

        Design: Difficulty/cross_entity_state_dependency/credit_box_activation_gated_by_partner_state
        """
        partner = create_partner(legal_name="Gate Bank Two")
        resp = api.create_credit_box(
            partner["id"], create_credit_box_payload(), partner_admin_headers
        )
        box = validate_success(resp, expected_status=201)

        validate_success(api.suspend_partner(partner["id"], partner_admin_headers))
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        resp = api.activate_credit_box(
            partner["id"], box["id"],
            {"expected_partner_version": partner["version"]},
            partner_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PARTNER_INVALID_STATE)

        validate_success(api.activate_partner(partner["id"], partner_admin_headers))
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        resp = api.activate_credit_box(
            partner["id"], box["id"],
            {"expected_partner_version": partner["version"]},
            partner_admin_headers,
        )
        box = validate_success(resp, expected_status=200)
        assert box["status"] == "ACTIVE"


class TestCreditBoxOcc:

    def test_stale_partner_version_on_box_activate_returns_412(
        self, api, partner_admin_headers
    ):
        """PRD 2.8: "Activating a credit box requires `expected_partner_version` matching the owning partner's current `version`"
        PRD 2.8: "In all three cases a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_partner_version_on_box_activate_returns_412
        """
        partner = create_partner(legal_name="OCC Bank")
        resp = api.create_credit_box(
            partner["id"], create_credit_box_payload(), partner_admin_headers
        )
        box1 = validate_success(resp, expected_status=201)
        resp = api.create_credit_box(
            partner["id"],
            create_credit_box_payload(allowed_states=["TX", "CA"]),
            partner_admin_headers,
        )
        box2 = validate_success(resp, expected_status=201)

        # First activation against the current partner version succeeds.
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        observed_version = partner["version"]
        resp = api.activate_credit_box(
            partner["id"], box1["id"],
            {"expected_partner_version": observed_version},
            partner_admin_headers,
        )
        box1 = validate_success(resp, expected_status=200)
        assert box1["status"] == "ACTIVE"
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["version"] == observed_version + 1
        assert partner["active_credit_box_id"] == box1["id"]

        # Second activation carrying the pre-first-activation version is stale.
        resp = api.activate_credit_box(
            partner["id"], box2["id"],
            {"expected_partner_version": observed_version},
            partner_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        box2 = get_success_data(api.get_credit_box(box2["id"], partner_admin_headers))
        assert box2["status"] == "DRAFT"
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["active_credit_box_id"] == box1["id"]


class TestCreditBoxSupersedeCycle:

    def test_supersede_chain_replaces_active_box_b1_b2_b3(
        self, api, partner_admin_headers
    ):
        """PRD 3.3: "On activation the partner's previously active box, if one exists, moves from `ACTIVE` to `SUPERSEDED`, the partner's `active_credit_box_id` is set to the newly activated box, and the partner's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/credit_box_supersede_cycle_replaces_active_box
        """
        partner = create_partner(legal_name="Supersede Bank")
        box1 = attach_active_credit_box(partner["id"], allowed_states=["TX"])
        box2 = attach_active_credit_box(partner["id"], allowed_states=["TX", "CA"])
        box3 = attach_active_credit_box(partner["id"], allowed_states=["TX", "CA", "NV"])

        box1 = get_success_data(api.get_credit_box(box1["id"], partner_admin_headers))
        box2 = get_success_data(api.get_credit_box(box2["id"], partner_admin_headers))
        box3 = get_success_data(api.get_credit_box(box3["id"], partner_admin_headers))
        assert box1["status"] == "SUPERSEDED"
        assert box2["status"] == "SUPERSEDED"
        assert box3["status"] == "ACTIVE"

        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["active_credit_box_id"] == box3["id"]

        # The chain permits no parallel ACTIVE boxes.
        data, meta = validate_paginated(
            api.list_credit_boxes(partner["id"], partner_admin_headers, params={"status": "ACTIVE"})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == box3["id"]

    def test_partner_version_advances_once_per_activation(
        self, api, partner_admin_headers
    ):
        """PRD 3.3: "the partner's `active_credit_box_id` is set to the newly activated box, and the partner's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/credit_box_supersede_cycle_replaces_active_box
        """
        partner = create_partner(legal_name="Supersede Bank Version")
        v0 = get_success_data(api.get_partner(partner["id"], partner_admin_headers))["version"]
        attach_active_credit_box(partner["id"], allowed_states=["TX"])
        attach_active_credit_box(partner["id"], allowed_states=["TX", "CA"])
        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["version"] == v0 + 2


class TestPartnerOffboardCascade:

    def test_offboard_cascades_boxes_and_pools(
        self, api, partner_admin_headers
    ):
        """PRD 3.3: "When offboarding succeeds, its effects cascade: any of the partner's credit boxes in `ACTIVE` move to `SUPERSEDED`, any in `DRAFT` move to `RETIRED`, and every securitization pool the partner owns that is still `OPEN` moves to `CLOSED`."

        Design: Difficulty/transitive_cascade/offboard_cascades_partner_to_boxes_to_pools
        """
        trust = create_partner(
            legal_name="Cascade Trust", partner_type="SECURITIZATION_TRUST", home_state="DE"
        )
        box1 = attach_active_credit_box(trust["id"])

        resp = api.create_credit_box(
            trust["id"], create_credit_box_payload(), partner_admin_headers
        )
        box2 = validate_success(resp, expected_status=201)
        assert box2["status"] == "DRAFT"

        resp = api.create_securitization_pool(
            create_securitization_pool_payload(trust["id"], pool_label="TR-2026-A"),
            partner_admin_headers,
        )
        pool = validate_success(resp, expected_status=201)
        assert pool["status"] == "OPEN"

        resp = api.offboard_partner(trust["id"], partner_admin_headers)
        trust = validate_success(resp, expected_status=200)
        assert trust["status"] == "OFFBOARDED"

        box1 = get_success_data(api.get_credit_box(box1["id"], partner_admin_headers))
        box2 = get_success_data(api.get_credit_box(box2["id"], partner_admin_headers))
        pool = get_success_data(api.get_securitization_pool(pool["id"], partner_admin_headers))
        assert box1["status"] == "SUPERSEDED"
        assert box2["status"] == "RETIRED"
        assert pool["status"] == "CLOSED"

    def test_offboarded_trust_can_never_be_selected_again(
        self, api, partner_admin_headers
    ):
        """PRD 3.3: "Offboarding is the terminal step"
        PRD 3.9: "Fourth, securitization: every `OPEN` `SecuritizationPool` whose owning trust partner is `ACTIVE`"

        Design: Difficulty/transitive_cascade/offboard_cascades_partner_to_boxes_to_pools
        """
        trust = create_partner(
            legal_name="Cascade Trust Two", partner_type="SECURITIZATION_TRUST", home_state="DE"
        )
        box1 = attach_active_credit_box(trust["id"])
        validate_success(api.offboard_partner(trust["id"], partner_admin_headers))

        box1 = get_success_data(api.get_credit_box(box1["id"], partner_admin_headers))
        assert box1["status"] != "ACTIVE"
        trust = get_success_data(api.get_partner(trust["id"], partner_admin_headers))
        assert trust["status"] == "OFFBOARDED"


class TestSecuritizationPoolLifecycle:

    def test_pool_close_from_closed_is_rejected(self, api, partner_admin_headers):
        """PRD 3.3: "A pool opens in `OPEN` status with `allocated_principal_cents` at zero, accumulates principal as loans are placed into it, and may be closed by an administrator; a pool not in `OPEN` rejects closure with `ERR_POOL_INVALID_STATE`."

        Design: Corner/state_machines/securitization_pool_close_from_closed_is_rejected
        """
        trust = create_partner(
            legal_name="Close Trust", partner_type="SECURITIZATION_TRUST", home_state="DE"
        )
        resp = api.create_securitization_pool(
            create_securitization_pool_payload(trust["id"], pool_label="TR-CLOSE"),
            partner_admin_headers,
        )
        pool = validate_success(resp, expected_status=201)
        assert pool["status"] == "OPEN"

        validate_success(api.close_securitization_pool(pool["id"], partner_admin_headers))

        resp = api.close_securitization_pool(pool["id"], partner_admin_headers)
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)

        pool = get_success_data(api.get_securitization_pool(pool["id"], partner_admin_headers))
        assert pool["status"] == "CLOSED"


class TestPartnerTerminalState:

    def test_offboarded_partner_rejects_further_lifecycle_calls(
        self, api, partner_admin_headers
    ):
        """PRD 3.3: "Any lifecycle call against a partner not in the state the transition requires fails with `ERR_PARTNER_INVALID_STATE` (HTTP 409)."
        PRD 3.3: "Offboarding is the terminal step"

        Design: Corner/state_machines/partner_offboard_from_terminal_state_is_rejected
        """
        partner = create_partner(
            legal_name="Terminal Trust", partner_type="CREDIT_UNION", home_state="WA"
        )
        validate_success(api.offboard_partner(partner["id"], partner_admin_headers))

        resp = api.offboard_partner(partner["id"], partner_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PARTNER_INVALID_STATE)
        resp = api.suspend_partner(partner["id"], partner_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PARTNER_INVALID_STATE)

        partner = get_success_data(api.get_partner(partner["id"], partner_admin_headers))
        assert partner["status"] == "OFFBOARDED"


class TestOffboardFiscalGuard:

    def test_offboard_blocked_while_partner_holds_loans(self, api, partner_admin_headers):
        """PRD 3.3: "the partner's `funded_balance_cents` - the sum of `principal_cents` across all loans the partner currently holds in `CURRENT`, `DELINQUENT`, or `CHARGED_OFF` status - must be exactly zero, or the offboard is rejected with `ERR_PARTNER_HOLDS_LOANS`."

        Design: Corner/validations/offboard_blocked_while_partner_holds_loans
        """
        bundle = setup_funded_loan()
        partner_id = bundle["partner"]["id"]

        resp = api.offboard_partner(partner_id, partner_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PARTNER_HOLDS_LOANS)

        partner = get_success_data(api.get_partner(partner_id, partner_admin_headers))
        assert partner["status"] == "ACTIVE"
        assert partner["funded_balance_cents"] == 5000000

    def test_offboard_allowed_again_once_balance_is_zero(
        self, api, partner_admin_headers, servicing_agent_headers
    ):
        """PRD 3.3: "the partner's `funded_balance_cents` - the sum of `principal_cents` across all loans the partner currently holds in `CURRENT`, `DELINQUENT`, or `CHARGED_OFF` status - must be exactly zero, or the offboard is rejected with `ERR_PARTNER_HOLDS_LOANS`."

        Design: Corner/validations/offboard_blocked_while_partner_holds_loans
        """
        bundle = setup_funded_loan()
        partner_id = bundle["partner"]["id"]
        loan = bundle["loan"]

        resp = api.offboard_partner(partner_id, partner_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PARTNER_HOLDS_LOANS)

        # Full payoff moves the loan to PAID_OFF, outside the counted set.
        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 6000000, "expected_loan_version": loan["version"]},
            servicing_agent_headers,
        )
        validate_success(resp, expected_status=200)
        partner = get_success_data(api.get_partner(partner_id, partner_admin_headers))
        assert partner["funded_balance_cents"] == 0

        resp = api.offboard_partner(partner_id, partner_admin_headers)
        partner = validate_success(resp, expected_status=200)
        assert partner["status"] == "OFFBOARDED"
