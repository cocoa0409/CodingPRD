"""Tier progression, onboarding, payments, and enterprise agreement tests."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    BILLING,
    NON_EXISTENT_UUID,
    create_and_activate_organization,
    create_claimed_case,
    create_organization,
    create_pending_payment,
    create_settled_payment,
    issue_action,
    make_organization_admin_headers,
    make_trust_analyst_headers,
    set_clock,
    setup_enterprise_org,
    setup_org_with_pending_appeal,
    setup_restricted_org,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTierPreviewVariants:
    def test_preview_tier_counts_pending_payment(self, api):
        """PRD §3.1: "Fetching a single organization accepts an optional `preview` query flag: when `preview` is true, the returned tier is a forward-looking projection that additionally counts `PENDING` payments as if they will settle, and so may exceed the settled tier."
        PRD §3.1: "`TIER_2` requires lifetime spend of at least 5,000,000 cents (fifty thousand dollars) and at least 5 qualifying payments."

        Design: Difficulty/dual_variant_calc/tier_progression_forward_looking_vs_settled_only
        """
        set_clock()
        org = create_organization(legal_name="Tier Preview Corp")
        for _ in range(4):
            create_settled_payment(org["id"], amount_cents=1000000)
        create_pending_payment(org["id"], amount_cents=2000000)

        preview = validate_success(
            api.get_organization(org["id"], BILLING, params={"preview": "true"})
        )
        assert preview["tier"] == "TIER_2", (
            f"preview must count the PENDING 2,000,000-cent topup toward TIER_2, got {preview['tier']}"
        )

    def test_settled_tier_ignores_pending_payment(self, api):
        """PRD §3.1: "The authoritative, persisted tier always counts only `SETTLED` payments."
        PRD §3.1: "The projected value is returned only in that preview response and is never persisted."

        Design: Difficulty/dual_variant_calc/tier_progression_forward_looking_vs_settled_only
        """
        set_clock()
        org = create_organization(legal_name="Tier Settled Corp")
        for _ in range(4):
            create_settled_payment(org["id"], amount_cents=1000000)
        create_pending_payment(org["id"], amount_cents=2000000)

        settled = validate_success(api.get_organization(org["id"], BILLING))
        assert settled["lifetime_spend_cents"] == 4000000
        assert settled["qualifying_payment_count"] == 4
        assert settled["tier"] == "TIER_1", (
            f"persisted tier must ignore the PENDING payment, got {settled['tier']}"
        )


class TestTier2InclusiveBoundary:
    def test_spend_exactly_at_threshold_promotes(self, api):
        """PRD §3.1: "`TIER_2` requires lifetime spend of at least 5,000,000 cents (fifty thousand dollars) and at least 5 qualifying payments."
        PRD §2.6: "Tier comparisons and progression thresholds are integer comparisons with inclusive boundaries — meeting a threshold exactly is sufficient."

        Design: Difficulty/boundary_precision_check/tier_2_threshold_inclusive_boundary
        """
        set_clock()
        org = create_organization(legal_name="Boundary At Corp")
        for _ in range(5):
            create_settled_payment(org["id"], amount_cents=1000000)
        data = validate_success(api.get_organization(org["id"], ADMIN))
        assert data["lifetime_spend_cents"] == 5000000
        assert data["qualifying_payment_count"] == 5
        assert data["tier"] == "TIER_2", (
            f"exactly at the 5,000,000-cent / 5-payment threshold must promote to TIER_2, got {data['tier']}"
        )

    def test_one_cent_below_threshold_does_not_promote(self, api):
        """PRD §3.1: "`TIER_2` requires lifetime spend of at least 5,000,000 cents (fifty thousand dollars) and at least 5 qualifying payments."
        PRD §2.6: "Tier comparisons and progression thresholds are integer comparisons with inclusive boundaries — meeting a threshold exactly is sufficient."

        Design: Difficulty/boundary_precision_check/tier_2_threshold_inclusive_boundary
        """
        set_clock()
        org = create_organization(legal_name="Boundary Below Corp")
        for _ in range(4):
            create_settled_payment(org["id"], amount_cents=1000000)
        create_settled_payment(org["id"], amount_cents=999999)
        data = validate_success(api.get_organization(org["id"], ADMIN))
        assert data["lifetime_spend_cents"] == 4999999
        assert data["qualifying_payment_count"] == 5
        assert data["tier"] == "TIER_1", (
            f"one cent below threshold must not promote, got {data['tier']}"
        )


class TestTierProgressionBasics:
    def test_both_spend_and_count_legs_required(self, api):
        """PRD §3.1: "The thresholds are cumulative and conjunctive — both the spend leg and the count leg must be met"

        Design: Corner/calculations/tier_progression_requires_both_spend_and_count
        """
        set_clock()
        org = create_organization(legal_name="Count Only Corp")
        for _ in range(5):
            create_settled_payment(org["id"], amount_cents=1000)
        data = validate_success(api.get_organization(org["id"], ADMIN))
        assert data["qualifying_payment_count"] == 5
        assert data["tier"] == "TIER_1", (
            f"count of 5 with spend 5000 < 5,000,000 must remain TIER_1, got {data['tier']}"
        )

    def test_pending_payments_excluded_from_aggregates(self, api):
        """PRD §3.1: "The authoritative, persisted tier always counts only `SETTLED` payments."
        PRD §3.1: "On settlement, the payment's `amount_cents` is added to the organization's `lifetime_spend_cents` — refunds, being negative, subtract from it."

        Design: Corner/calculations/input_set_filtering_excludes_pending_payments
        """
        set_clock()
        org = create_organization(legal_name="Input Set Corp")
        create_settled_payment(org["id"], amount_cents=1000)
        create_pending_payment(org["id"], amount_cents=999999)
        data = validate_success(api.get_organization(org["id"], ADMIN))
        assert data["lifetime_spend_cents"] == 1000, (
            f"PENDING payment must be excluded, got spend {data['lifetime_spend_cents']}"
        )
        assert data["qualifying_payment_count"] == 1


class TestOrganizationCreation:
    def test_create_returns_declared_fields_and_starts_provisional(self, api):
        """PRD §3.1: "New organizations begin in `PROVISIONAL` status with all aggregates at zero: `lifetime_spend_cents` and `qualifying_payment_count` start at 0, `credit_balance_cents` starts at 0, `enterprise_agreement_id` is unset, and the computed `tier` starts at `TIER_1`."

        Design: Corner/entities/organization_create_returns_declared_fields_and_starts_provisional
        """
        set_clock()
        resp = api.create_organization({"legal_name": "Fresh Onboard Inc"}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PROVISIONAL"
        assert data["tier"] == "TIER_1"
        assert data["lifetime_spend_cents"] == 0
        assert data["qualifying_payment_count"] == 0
        assert data["credit_balance_cents"] == 0
        assert data["version"] == 1
        assert data["id"]
        assert data["created_at"]
        assert data["updated_at"]

    def test_get_round_trips_stored_fields(self, api):
        """PRD §3.1: "A `PlatformAdmin` onboards a new customer by supplying the organization's `legal_name` — immutable once recorded — and, optionally, a `pinned_model_version_id`."
        PRD §3.1: "`enterprise_agreement_id` is unset"

        Design: Corner/entities/organization_get_returns_stored_data_unchanged
        """
        set_clock()
        created = validate_success(
            api.create_organization({"legal_name": "Fresh Onboard Inc"}, ADMIN),
            expected_status=201,
        )
        fetched = validate_success(api.get_organization(created["id"], ADMIN))
        assert fetched["legal_name"] == "Fresh Onboard Inc"
        assert fetched["pinned_model_version_id"] is None
        assert fetched["enterprise_agreement_id"] is None

    def test_get_unknown_id_returns_not_found(self, api):
        """PRD §2.10: "path-resource existence third — validated left-to-right, so a missing organization surfaces as `ERR_NOT_FOUND` (HTTP 404) before any child under it is examined"

        Design: Corner/entities/organization_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_organization(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err.get("message"), "error envelope must carry a message"

    def test_missing_legal_name_rejected(self, api):
        """PRD §2.10: "request-body shape fourth — missing required fields, ill-typed values, or enum members outside the declared set yield `ERR_INVALID_REQUEST` (HTTP 400)"

        Design: Corner/entities/organization_create_missing_legal_name_returns_invalid_request
        """
        set_clock()
        resp = api.create_organization({}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPaymentSettle:
    def test_settle_twice_rejected_and_not_double_counted(self, api):
        """PRD §2.10: "state-machine admissibility of the requested transition fifth, with violations rejected as `ERR_INVALID_STATE` (HTTP 409)"
        PRD §3.1: "Settlement, performed by a `PlatformAdmin`, moves a payment from `PENDING` to `SETTLED` and is the moment the money becomes real."

        Design: Corner/state_machines/payment_settle_twice_returns_invalid_state
        """
        set_clock()
        org = create_organization(legal_name="Double Settle Co")
        payment = create_settled_payment(org["id"], amount_cents=1000)
        resp = api.settle_payment_event(payment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_organization(org["id"], ADMIN))
        assert data["lifetime_spend_cents"] == 1000, (
            f"settled amount must not be double-counted, got {data['lifetime_spend_cents']}"
        )

    def test_settle_immediately_visible_on_organization(self, api):
        """PRD §3.1: "On settlement, the payment's `amount_cents` is added to the organization's `lifetime_spend_cents` — refunds, being negative, subtract from it."

        Design: Corner/consistency_model/immediate_consistency_on_tier_update
        """
        set_clock()
        org = create_organization(legal_name="Immediate Co")
        payment = create_pending_payment(org["id"], amount_cents=1000000)
        validate_success(api.settle_payment_event(payment["id"], ADMIN))
        data = validate_success(api.get_organization(org["id"], ADMIN))
        assert data["lifetime_spend_cents"] == 1000000

    def test_payment_event_settles_via_transition_endpoint(self, api):
        """PRD §2.4: "they are never mutated after creation (PaymentEvent transitions only from `PENDING` to `SETTLED` through its settle operation, and exposes no update or delete endpoints)."

        Design: Corner/entities/payment_event_immutable_no_update_endpoint
        """
        set_clock()
        org = create_organization(legal_name="Immutable Payment Co")
        payment = create_pending_payment(org["id"], amount_cents=1000000)
        resp = api.settle_payment_event(payment["id"], ADMIN)
        data = validate_success(resp)
        assert data["status"] == "SETTLED"
        assert data["id"] == payment["id"]


class TestOrganizationActivation:
    def test_activate_requires_settled_payment(self, api):
        """PRD §3.1: "Activation requires the organization to still be `PROVISIONAL` and to have at least one `SETTLED` payment on record; it triggers a tier recomputation and increments the organization's `version`."

        Design: Corner/endpoints/action_endpoint_activate_transitions_state
        """
        set_clock()
        org_ready = create_organization(legal_name="Ready Corp")
        create_settled_payment(org_ready["id"], amount_cents=1000000)
        org_empty = create_organization(legal_name="Empty Corp")

        resp = api.activate_organization(org_empty["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data = validate_success(api.activate_organization(org_ready["id"], ADMIN))
        assert data["status"] == "ACTIVE"


class TestOrganizationTerminalLockdown:
    def test_terminated_organization_rejects_activation(self, api):
        """PRD §3.7: "`TERMINATE` is issuable only by a `TrustLead` and only on a `CRITICAL` case; it moves the organization `ACTIVE → TERMINATED` — its terminal state — cascades every agreement in `DRAFT` or `ACTIVE` to `TERMINATED`, drops every `QUEUED` request, and increments the organization's `version`."

        Design: Corner/state_machines/organization_terminated_lockdown_no_transitions
        """
        set_clock()
        org = create_and_activate_organization(legal_name="Terminal Co")
        case, case_v = create_claimed_case(org["id"], severity="CRITICAL")
        issue_action(case["id"], case_v, "TERMINATE", issuer_id="lead-1", role="lead")

        resp = api.activate_organization(org["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCountersignGating:
    def test_countersign_rejected_while_organization_provisional(self, api):
        """PRD §3.6: "It requires the agreement to be `DRAFT`, the organization to be `ACTIVE`, and the current logical time to fall at or after `effective_at` and strictly before `expires_at`."
        PRD §2.10: "state-machine admissibility of the requested transition fifth, with violations rejected as `ERR_INVALID_STATE` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/countersign_requires_organization_active
        """
        set_clock()
        org = create_organization(legal_name="Gated Countersign Co")
        create_settled_payment(org["id"], amount_cents=1000000)
        resp = api.create_enterprise_agreement(
            {
                "organization_id": org["id"],
                "committed_tpm": 5000,
                "dedicated_capacity_pct": 10,
                "effective_at": "2026-08-01T00:00:00Z",
                "expires_at": "2027-08-01T00:00:00Z",
            },
            ADMIN,
        )
        agreement = validate_success(resp, expected_status=201)

        resp = api.countersign_enterprise_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_countersign_succeeds_after_activation_and_forces_enterprise_tier(self, api):
        """PRD §3.6: "Countersigning sets the organization's `enterprise_agreement_id` to the agreement, forces the organization's tier to `ENTERPRISE` — overriding tier progression for as long as the agreement remains active — and increments the agreement's `version`."

        Design: Difficulty/cross_entity_state_dependency/countersign_requires_organization_active
        """
        set_clock()
        org = create_organization(legal_name="Countersign Co")
        create_settled_payment(org["id"], amount_cents=1000000)
        agreement = validate_success(
            api.create_enterprise_agreement(
                {
                    "organization_id": org["id"],
                    "committed_tpm": 5000,
                    "dedicated_capacity_pct": 10,
                    "effective_at": "2026-08-01T00:00:00Z",
                    "expires_at": "2027-08-01T00:00:00Z",
                },
                ADMIN,
            ),
            expected_status=201,
        )
        validate_success(api.activate_organization(org["id"], ADMIN))

        data = validate_success(api.countersign_enterprise_agreement(agreement["id"], ADMIN))
        assert data["status"] == "ACTIVE"
        org_data = validate_success(api.get_organization(org["id"], ADMIN))
        assert org_data["tier"] == "ENTERPRISE"


class TestTerminateCascade:
    def test_terminate_cascades_agreement_and_tier(self, api):
        """PRD §3.7: "`TERMINATE` is issuable only by a `TrustLead` and only on a `CRITICAL` case; it moves the organization `ACTIVE → TERMINATED` — its terminal state — cascades every agreement in `DRAFT` or `ACTIVE` to `TERMINATED`, drops every `QUEUED` request, and increments the organization's `version`."
        PRD §3.6: "Alternatively, if the organization is suspended or terminated under enforcement, every `ACTIVE` agreement it holds cascades to `TERMINATED` with the same clearing and tier-recomputation effects."

        Design: Difficulty/transitive_cascade/terminate_cascades_through_agreement_to_tier
        """
        set_clock()
        org, agreement = setup_enterprise_org(
            legal_name="Cascade Depth3 Inc", committed_tpm=10000, dedicated_capacity_pct=25
        )
        case, case_v = create_claimed_case(org["id"], severity="CRITICAL")
        issue_action(case["id"], case_v, "TERMINATE", issuer_id="lead-1", role="lead")

        org_data = validate_success(api.get_organization(org["id"], ADMIN))
        assert org_data["status"] == "TERMINATED"

        ea_data = validate_success(api.get_enterprise_agreement(agreement["id"], ADMIN))
        assert ea_data["status"] == "TERMINATED", (
            f"ACTIVE agreement must cascade to TERMINATED, got {ea_data['status']}"
        )

    def test_terminate_recomputes_tier_away_from_enterprise(self, api):
        """PRD §3.6: "Alternatively, if the organization is suspended or terminated under enforcement, every `ACTIVE` agreement it holds cascades to `TERMINATED` with the same clearing and tier-recomputation effects."
        PRD §3.1: "when the agreement ends, the tier falls back to whatever the settled aggregates dictate."

        Design: Difficulty/transitive_cascade/terminate_cascades_through_agreement_to_tier
        """
        set_clock()
        org, agreement = setup_enterprise_org(
            legal_name="Cascade Tier Inc", committed_tpm=10000, dedicated_capacity_pct=25
        )
        case, case_v = create_claimed_case(org["id"], severity="CRITICAL")
        issue_action(case["id"], case_v, "TERMINATE", issuer_id="lead-1", role="lead")

        org_data = validate_success(api.get_organization(org["id"], ADMIN))
        assert org_data["tier"] == "TIER_1", (
            f"settled spend 1,000,000 with count 1 must fall back to TIER_1, got {org_data['tier']}"
        )
        assert org_data["enterprise_agreement_id"] is None


class TestOrganizationBranching:
    def test_restrict_then_suspend_across_two_cases(self, api):
        """PRD §3.7: "`RESTRICT` moves the organization `ACTIVE → RESTRICTED`, requires a case severity whose rank is at least that of `RESTRICT`, drops every `QUEUED` request the organization holds, and increments the organization's `version`."
        PRD §3.7: "`SUSPEND` moves the organization `RESTRICTED → SUSPENDED`, requires a case severity of `HIGH` or `CRITICAL`, terminates every `ACTIVE` enterprise agreement the organization holds (with the clearing and tier-recomputation effects of §3.6), and increments the organization's `version`."

        Design: Difficulty/non_linear_state_machine/organization_status_branching_enforcement_paths
        """
        set_clock()
        org = create_and_activate_organization(legal_name="Parallel Dims Co")
        case_low, case_low_v = create_claimed_case(
            org["id"], severity="HIGH", analyst_id="analyst-1"
        )
        issue_action(case_low["id"], case_low_v, "RESTRICT", issuer_id="analyst-1")
        case_high, case_high_v = create_claimed_case(
            org["id"], severity="HIGH", analyst_id="analyst-2"
        )
        issue_action(case_high["id"], case_high_v, "SUSPEND", issuer_id="analyst-2")

        org_data = validate_success(api.get_organization(org["id"], ADMIN))
        assert org_data["status"] == "SUSPENDED", (
            f"RESTRICTED -> SUSPENDED path must land in SUSPENDED, got {org_data['status']}"
        )

    def test_suspend_directly_from_active_rejected(self, api):
        """PRD §3.7: "`SUSPEND` moves the organization `RESTRICTED → SUSPENDED`, requires a case severity of `HIGH` or `CRITICAL`, terminates every `ACTIVE` enterprise agreement the organization holds (with the clearing and tier-recomputation effects of §3.6), and increments the organization's `version`."
        PRD §2.10: "state-machine admissibility of the requested transition fifth, with violations rejected as `ERR_INVALID_STATE` (HTTP 409)"

        Design: Difficulty/non_linear_state_machine/organization_status_branching_enforcement_paths
        """
        set_clock()
        org = create_and_activate_organization(legal_name="No Skip Co")
        case, case_v = create_claimed_case(org["id"], severity="HIGH", analyst_id="analyst-2")
        resp = api.create_abuse_action(
            case["id"],
            {"action_type": "SUSPEND", "expected_abuse_case_version": case_v},
            make_trust_analyst_headers("analyst-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPaymentEventListing:
    def test_reverse_reachability_list_with_filters(self, api):
        """PRD §3.1: "Money enters the system through payment events, recorded by a `PlatformAdmin` or `BillingContact` with an `organization_id`, a `kind`, and a signed `amount_cents`."
        PRD §4: "GET | `/organizations/{id}/payment-events` | List payment events for an organization"

        Design: Corner/endpoints/reverse_reachability_get_payment_events
        """
        set_clock()
        org = create_organization(legal_name="Payment List Co")
        create_pending_payment(org["id"], amount_cents=1000, kind="PREPAID_TOPUP")
        create_pending_payment(org["id"], amount_cents=-500, kind="REFUND")

        data, meta = validate_paginated(
            api.list_organization_payment_events(org["id"], ADMIN)
        )
        assert meta["total_count"] == 2

        data, meta = validate_paginated(
            api.list_organization_payment_events(org["id"], ADMIN, params={"kind": "REFUND"})
        )
        assert meta["total_count"] == 1
        assert data[0]["kind"] == "REFUND"

        data, meta = validate_paginated(
            api.list_organization_payment_events(org["id"], ADMIN, params={"status": "PENDING"})
        )
        assert meta["total_count"] == 2


class TestEnterpriseHeaders:
    """Identity threading for the entity-backed OrganizationAdmin role."""

    def test_org_admin_identity_bound_to_org(self, api):
        """PRD §2.1: "When `X-User-Role` is `OrganizationAdmin`, `X-User-ID` is the `id` of the acting Organization; ownership checks on any resource that references an Organization compare the resource's foreign-key field (such as `organization_id`) to `X-User-ID`."

        Design: Corner/endpoints/reverse_reachability_get_payment_events
        """
        set_clock()
        org = create_organization(legal_name="Identity Co")
        create_pending_payment(org["id"], amount_cents=1000)
        resp = api.list_organization_payment_events(
            org["id"], make_organization_admin_headers(org["id"])
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
