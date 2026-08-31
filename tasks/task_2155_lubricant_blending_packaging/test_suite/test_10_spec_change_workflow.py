"""The governed specification-change workflow: the fork, the join and cascade A."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    ApiErrorId,
    TEST_USERS,
    add_order_line,
    confirm_order,
    create_active_claim,
    create_active_config,
    create_active_recipe,
    create_active_spec,
    create_customer,
    find_order_line,
    open_order,
    read_change_request,
    read_claim,
    read_config,
    read_order,
    read_recipe,
    read_spec,
    set_clock,
    setup_active_formulation,
    setup_change_request_in_review,
    setup_cleared_change_request,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
QM = TEST_USERS["quality_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _spec_with_claim_and_open_request(api):
    """An ACTIVE specification with one ACTIVE recipe, one ACTIVE claim and a
    change request to 7.700 resting at IN_REVIEW."""
    world = setup_active_formulation(with_lots=False)
    world["claim"] = create_active_claim(world["spec"]["id"])
    world["request"] = setup_change_request_in_review(world["spec"]["id"])
    return world


class TestForkAndJoin:
    def test_the_viscosity_branch_alone_leaves_the_request_in_review(self, api):
        """PRD 3.1: "Submission is where the workflow forks. A `ProductManager` submits a
        `DRAFT` request while the specification is `ACTIVE`; the request passes through
        `SUBMITTED` and lands at `IN_REVIEW` inside that single call, with both branches open at
        `PENDING`."
        PRD 3.1: "A `QualityManager` rules the viscosity branch while the request is `IN_REVIEW`
        and `viscosity_review` is still `PENDING`; the branch writes `viscosity_review` to
        `CLEARED` or `BLOCKED` and performs no claim counting whatsoever."
        PRD 3.1: "Each verdict is a self-loop — the request stays `IN_REVIEW` while a branch is
        decided — and each advances the request's `version`."
        PRD 3.1: "A freshly opened request carries `claims_to_suspend_count` at 0 and
        `effective_revision` null."

        Design: Difficulty/non_linear_state_machine/spec_change_request_fork_join_requires_both_branches
        """
        world = _spec_with_claim_and_open_request(api)
        assert world["request"]["status"] == "IN_REVIEW"
        assert world["request"]["viscosity_review"] == "PENDING"
        assert world["request"]["approval_review"] == "PENDING"

        decided = validate_success(
            api.viscosity_review(
                world["request"]["id"],
                {"decision": "CLEAR", "note": "7.614 sits inside 7.469..7.931"},
                QM,
            )
        )
        assert decided["viscosity_review"] == "CLEARED"
        assert decided["approval_review"] == "PENDING"
        assert decided["status"] == "IN_REVIEW"
        assert decided["claims_to_suspend_count"] == 0, (
            "only the certification branch counts the claims"
        )

    def test_the_certification_branch_joins_the_request_to_cleared(self, api):
        """PRD 3.1: "A `ComplianceOfficer` rules the certification branch while the request is
        `IN_REVIEW` and `approval_review` is still `PENDING`; that branch writes
        `approval_review` to `CLEARED` or `BLOCKED` and, uniquely to this branch, records
        `claims_to_suspend_count` as the number of approval claims on the specification whose
        status is `ACTIVE` at that exact instant."
        PRD 3.1: "If `viscosity_review` and `approval_review` are both `CLEARED`, the request
        moves `IN_REVIEW → CLEARED`."
        PRD 3.1: "Both `CLEARED` and `REJECTED` are reached by the system rather than by an
        operator, and both advance the request's `version`."

        Design: Difficulty/non_linear_state_machine/spec_change_request_fork_join_requires_both_branches
        """
        world = _spec_with_claim_and_open_request(api)
        validate_success(
            api.viscosity_review(world["request"]["id"], {"decision": "CLEAR"}, QM)
        )

        joined = validate_success(
            api.approval_review(
                world["request"]["id"],
                {"decision": "CLEAR", "note": "one claim will need re-approval"},
                COMPLIANCE,
            )
        )
        assert joined["approval_review"] == "CLEARED"
        assert joined["status"] == "CLEARED"
        assert joined["claims_to_suspend_count"] == 1

        assert read_spec(world["spec"]["id"])["revision"] == 1, (
            "the join does not apply the change"
        )

    def test_a_blocked_branch_joins_the_request_to_rejected(self, api):
        """PRD 3.1: "If either branch is `BLOCKED`, the request moves `IN_REVIEW → REJECTED`."
        PRD 3.1: "Making a cleared request effective is the origin of cascade A, and only a
        `ProductManager` may do it, only while the request is `CLEARED` and the specification is
        `ACTIVE`."
        PRD 3.1: "The request records `effective_revision` — null up to this point — as the newly
        produced `revision`, moves `CLEARED → EFFECTIVE` — a terminal state — and advances its
        own `version`."

        Design: Corner/state_machines/spec_change_blocked_branch_joins_to_rejected
        """
        world = setup_active_formulation(with_lots=False)
        request = setup_change_request_in_review(world["spec"]["id"])
        validate_success(api.viscosity_review(request["id"], {"decision": "CLEAR"}, QM))

        blocked = validate_success(
            api.approval_review(
                request["id"],
                {"decision": "BLOCK", "note": "OEM will not carry the change"},
                COMPLIANCE,
            )
        )
        assert blocked["approval_review"] == "BLOCKED"
        assert blocked["status"] == "REJECTED"
        assert blocked["viscosity_review"] == "CLEARED"

        refused = api.make_spec_change_effective(request["id"], PM)
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)

        spec = read_spec(world["spec"]["id"])
        assert spec["revision"] == 1
        assert spec["target_kv100_cst"] == pytest.approx(7.600, abs=0.0005)
        assert read_change_request(request["id"])["effective_revision"] is None

    def test_clearing_the_viscosity_branch_requires_every_active_recipe_in_band(self, api):
        """PRD 3.1: "When the verdict is `CLEAR`, the system derives the proposed acceptance
        band by taking the proposed viscosity multiplied by one minus the proposed tolerance
        divided by one hundred as the lower endpoint, and the proposed viscosity multiplied by
        one plus the proposed tolerance divided by one hundred as the upper endpoint, each
        rounded half up to three decimal places."
        PRD 3.1: "Every recipe on the specification whose status is `ACTIVE` must have its
        predicted viscosity sitting at or above the lower endpoint and at or below the upper
        endpoint — both ends inclusive."
        PRD 3.1: "A `CLEAR` verdict that would leave an active recipe outside the proposed band
        is refused with `ERR_VISCOSITY_REVIEW_BLOCKED`."
        PRD 3.1: "A `BLOCK` verdict is never subject to this check."

        Design: Corner/validations/viscosity_review_clear_blocked_when_active_recipe_falls_outside_requested_band
        """
        world = setup_active_formulation(with_lots=False)
        request = setup_change_request_in_review(
            world["spec"]["id"], requested_kv100_cst=7.900
        )

        # The proposed band is 7.663 .. 8.137, which excludes the active recipe's 7.614.
        refused = api.viscosity_review(request["id"], {"decision": "CLEAR"}, QM)
        validate_error(refused, ApiErrorId.ERR_VISCOSITY_REVIEW_BLOCKED.value, 422)

        after_refusal = read_change_request(request["id"])
        assert after_refusal["viscosity_review"] == "PENDING"
        assert after_refusal["status"] == "IN_REVIEW"

        blocked = validate_success(
            api.viscosity_review(
                request["id"], {"decision": "BLOCK", "note": "7.614 falls below 7.663"}, QM
            )
        )
        assert blocked["viscosity_review"] == "BLOCKED"

    def test_a_second_change_request_on_a_stale_version_is_rejected(self, api):
        """PRD 2.8: "Opening a specification change request requires a non-optional
        `expected_product_spec_version` in the request body, carrying the client's last observed
        `version` of the target specification."
        PRD 2.8: "A specification may legitimately carry more than one open change request at a
        time, so a second create is allowed on its own merits; but if the supplied value no
        longer equals the specification's current `version`, the create is rejected with
        `ERR_STALE_SPEC_VERSION` and HTTP 412."
        PRD 3.1: "A successful create advances the specification's own `version` by 1 and
        produces a **specification change request** in `DRAFT`, carrying its `product_spec_id`,
        the four proposed replacements — `requested_kv100_cst`, `requested_kv100_tolerance_pct`,
        `requested_min_additive_treat_pct` and `requested_additive_family` — and both review
        branches, `viscosity_review` and `approval_review`, sitting at `PENDING`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_spec_version_rejects_second_change_request
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        observed_version = spec["version"]
        create_active_recipe(spec["id"])

        first = validate_success(
            api.create_spec_change_request(
                spec["id"],
                {
                    "requested_kv100_cst": 7.700,
                    "requested_kv100_tolerance_pct": 3.0,
                    "requested_min_additive_treat_pct": 8.00,
                    "requested_additive_family": "ZDDP_PCMO",
                    "expected_product_spec_version": observed_version,
                },
                PM,
            ),
            201,
        )
        assert first["status"] == "DRAFT"
        assert first["viscosity_review"] == "PENDING"
        assert first["approval_review"] == "PENDING"
        assert read_spec(spec["id"])["version"] == observed_version + 1

        stale = api.create_spec_change_request(
            spec["id"],
            {
                "requested_kv100_cst": 7.650,
                "requested_kv100_tolerance_pct": 3.0,
                "requested_min_additive_treat_pct": 9.00,
                "requested_additive_family": "ZDDP_PCMO",
                "expected_product_spec_version": observed_version,
            },
            PM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_SPEC_VERSION.value, 412)

        _, meta = validate_paginated(
            api.list_spec_change_requests(PM, {"product_spec_id": spec["id"]})
        )
        assert meta["total_count"] == 1

        unchanged = read_spec(spec["id"])
        assert unchanged["target_kv100_cst"] == pytest.approx(7.600, abs=0.0005)
        assert unchanged["revision"] == 1


class TestCascadeA:
    @staticmethod
    def _estate_ready_for_the_change(api):
        """An ACTIVE claim, the label printing it, a CONFIRMED order quoting that
        label, and a change request already cleared on both branches."""
        set_clock(CLOCK_BASE)
        customer = create_customer(takeback_agreement_status="ACTIVE")
        spec = create_active_spec()
        recipe = create_active_recipe(spec["id"])
        claim = create_active_claim(spec["id"])
        config = create_active_config(
            spec["id"],
            package_type="PAIL_20L",
            label_brand="Bravo Blue",
            fill_volume_l=20.0,
            private_label=True,
            customer_id=customer["id"],
            claim_codes=["API SP"],
        )
        order = open_order(customer["id"])
        line = add_order_line(order["id"], config["id"], 37)
        confirm_order(order["id"])
        request = setup_cleared_change_request(spec["id"])
        return {
            "customer": customer,
            "spec": spec,
            "recipe": recipe,
            "claim": claim,
            "config": config,
            "order": order,
            "line": line,
            "request": request,
        }

    def test_making_the_change_effective_suspends_claims_and_blocks_labels(self, api):
        """PRD 3.1: "The specification undergoes a self-loop `ACTIVE → ACTIVE`: its `revision`
        increases by 1 and the four requested values are written through onto
        `target_kv100_cst`, `kv100_tolerance_pct`, `min_additive_treat_pct` and
        `additive_family`."
        PRD 3.1: "The request records `effective_revision` — null up to this point — as the newly
        produced `revision`, moves `CLEARED → EFFECTIVE` — a terminal state — and advances its
        own `version`."
        PRD 3.1: "Every approval claim on the specification whose status is `ACTIVE` and whose
        `pinned_spec_revision` is now behind the specification's `revision` moves
        `ACTIVE → SUSPENDED`, which in turn blocks the package configurations printing its claim
        code and puts their open order lines and confirmed orders on hold, as described in §3.6
        and §3.8."
        PRD 3.1: "Independently, every recipe on the specification whose status is `ACTIVE` and
        whose `spec_revision_pinned` is now behind the specification's `revision` moves
        `ACTIVE → RETIRED`."

        Design: Difficulty/transitive_cascade/spec_change_effective_four_hop_cascade_to_order_hold
        """
        estate = self._estate_ready_for_the_change(api)

        effective = validate_success(
            api.make_spec_change_effective(estate["request"]["id"], PM)
        )
        assert effective["status"] == "EFFECTIVE"
        assert effective["effective_revision"] == 2

        spec = read_spec(estate["spec"]["id"])
        assert spec["revision"] == 2
        assert spec["target_kv100_cst"] == pytest.approx(7.700, abs=0.0005)

        claim = read_claim(estate["claim"]["id"])
        assert claim["status"] == "SUSPENDED"
        assert claim["requires_recertification"] is True

        assert read_config(estate["config"]["id"])["status"] == "CLAIM_BLOCKED"
        assert read_recipe(estate["recipe"]["id"])["status"] == "RETIRED"

    def test_the_blocked_label_puts_its_open_line_and_confirmed_order_on_hold(self, api):
        """PRD 2.9: "**Cascade A** is the specification-change cascade: making a cleared change
        effective advances the specification's `revision` (link 1), which suspends every active
        approval claim pinned to a superseded revision (link 2), which blocks every active
        package configuration printing a suspended claim's code (link 3), which puts every open
        order line quoting a blocked configuration — and the confirmed order owning it — on hold
        (link 4), and which independently retires every active recipe pinned to a superseded
        revision (link 5)."
        PRD 3.8: "Line-level holds are always system-driven: an `OPEN` line moves
        `OPEN → HOLD` exactly when the configuration it references has become `CLAIM_BLOCKED` or
        `SUPERSEDED`."
        PRD 3.8: "The same `CONFIRMED → HOLD` hop is driven by the system as link 4 of cascade
        A, with `hold_reason` set to `CLAIM_BLOCKED_LINE`, whenever an order line on a confirmed
        order is put on hold because the configuration it quotes stopped being `ACTIVE`."
        PRD 3.1: "A `ComplianceOfficer` rules the certification branch while the request is
        `IN_REVIEW` and `approval_review` is still `PENDING`; that branch writes
        `approval_review` to `CLEARED` or `BLOCKED` and, uniquely to this branch, records
        `claims_to_suspend_count` as the number of approval claims on the specification whose
        status is `ACTIVE` at that exact instant."

        Design: Difficulty/transitive_cascade/spec_change_effective_four_hop_cascade_to_order_hold
        """
        estate = self._estate_ready_for_the_change(api)
        assert estate["request"]["claims_to_suspend_count"] == 1

        validate_success(api.make_spec_change_effective(estate["request"]["id"], PM))

        assert (
            find_order_line(estate["order"]["id"], estate["line"]["id"])["status"] == "HOLD"
        )

        order = read_order(estate["order"]["id"])
        assert order["status"] == "HOLD"
        assert order["subtotal_cents"] == 361228, "the hold does not reprice the order"
        assert order["pre_credit_total_cents"] == 400728
