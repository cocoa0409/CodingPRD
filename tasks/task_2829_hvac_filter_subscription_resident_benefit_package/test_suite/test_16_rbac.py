"""
Role-based access control: the two-directional separation across the claim
pipeline, the two entity-backed roles' ownership scopes, the segregation-of-duties
bar on the individual, and the resident's narrow write surface.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.test_users import (
    ADJUSTER_A,
    ADJUSTER_B,
    OPERATOR,
    make_property_manager_headers,
    make_resident_headers,
)


class TestClaimPipelineSeparation:
    """Neither the operator nor the adjuster can walk a claim end to end."""

    def test_the_operator_cannot_adjudicate_and_the_adjuster_cannot_disburse(self, api):
        """
        The operator who funds payouts is refused at triage and at the decision,
        and the adjuster who approved the claim is refused at the payout — each
        refusal leaving the claim exactly where it was — so the pipeline only
        advances when the two roles alternate.

        PRD §2.10: "The acting role appears in the target endpoint's authorised-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

        Design: Corner/rbac/operator_cannot_adjudicate_and_adjuster_cannot_disburse
        """
        env = fx.build_base_env(api)
        claim = fx.file_claim(api, env.subscription_id)
        assert claim["status"] == "SUBMITTED"

        validate_error(api.triage_claim(claim["id"], OPERATOR), ERR_ROLE_NOT_PERMITTED, 403)
        held = validate_success(api.get_claim(claim["id"], OPERATOR))
        assert held["status"] == "SUBMITTED"
        assert held["version"] == 1

        triaged = validate_success(api.triage_claim(claim["id"], ADJUSTER_A))
        assert triaged["status"] == "UNDER_REVIEW"
        assert triaged["triaged_by_user_id"] == "adj-001"

        validate_error(
            api.decide_claim(claim["id"], f.decide_payload("APPROVE", "Covered"), OPERATOR),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert validate_success(api.get_claim(claim["id"], OPERATOR))["status"] == "UNDER_REVIEW"

        decided = validate_success(
            api.decide_claim(claim["id"], f.decide_payload("APPROVE", "Covered"), ADJUSTER_B)
        )
        assert decided["status"] == "APPROVED"
        a.assert_cents(decided["approved_amount_cents"], 30000, "approved_amount_cents")

        validate_error(api.pay_claim(claim["id"], ADJUSTER_B), ERR_ROLE_NOT_PERMITTED, 403)
        unpaid = validate_success(api.get_claim(claim["id"], OPERATOR))
        assert unpaid["status"] == "APPROVED"
        assert unpaid["paid_at"] is None
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

        paid = validate_success(api.pay_claim(claim["id"], OPERATOR))
        assert paid["status"] == "PAID"
        assert a.property_balance(api, env.property_id, OPERATOR) == -24412


class TestPeerOwnershipScopes:
    """Two entity-backed roles, two different resolution paths, one error code."""

    def _two_households(self, api):
        env = fx.build_base_env(api)
        property_b = fx.create_property(api, name="Birch Court")
        unit_b = fx.create_unit(api, property_b["id"], unit_label="B-101")
        fx.activate_property(api, property_b["id"])
        resident_b = fx.create_resident(
            api, full_name="Ben Ortiz", email="ben.ortiz@example.com", household_size=3
        )
        subscription_b = fx.create_subscription(api, resident_b["id"], unit_b["id"])
        fx.activate_subscription(api, subscription_b["id"])
        return env, property_b, resident_b, subscription_b

    def test_neither_a_peer_resident_nor_a_peer_manager_can_reach_across(self, api):
        """
        Ada's identity resolves through the subscription's resident_id and Cedar
        Ridge's manager identity through its property_id, so each is refused on
        Birch Court's records and served on its own — and a peer's write attempt
        leaves the target subscription untouched.

        PRD §2.10: "Ownership scope for the two entity-backed roles, as described in §2.1 — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to every endpoint whose authorised roles include `PropertyManager` or `Resident`."

        Design: Corner/rbac/resident_cannot_reach_another_residents_subscription
        """
        env, property_b, _resident_b, subscription_b = self._two_households(api)
        ada = make_resident_headers(env.resident_id)
        cedar_ridge_manager = make_property_manager_headers(env.property_id)

        validate_error(
            api.get_subscription(subscription_b["id"], ada), ERR_NOT_RESOURCE_OWNER, 403
        )
        own = validate_success(api.get_subscription(env.subscription_id, ada))
        assert own["resident_id"] == env.resident_id

        validate_error(
            api.list_benefit_entitlements(subscription_b["id"], cedar_ridge_manager),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        rows, meta = validate_paginated(
            api.list_benefit_entitlements(env.subscription_id, cedar_ridge_manager)
        )
        assert meta["total_count"] == 4
        assert len(rows) == 4

        validate_error(
            api.cancel_subscription(
                subscription_b["id"],
                f.cancel_payload("2026-08-05", "Peer tampering attempt"),
                ada,
            ),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        untouched = validate_success(
            api.get_subscription(subscription_b["id"], make_property_manager_headers(property_b["id"]))
        )
        assert untouched["status"] == "ACTIVE"
        assert untouched["version"] == 2


class TestSegregationOfDuties:
    """The bar is on the person, and it survives the revision loop."""

    def test_the_triaging_adjuster_can_never_decide_even_after_a_round_trip(self, api):
        """
        adj-001 is refused on both an approval and a denial while adj-002 succeeds
        on the identical call, and the information round trip in between neither
        clears triaged_by_user_id nor lifts the bar.

        PRD §3.7: "Segregation of duties bars the individual who triaged the claim from deciding it: an acting `X-User-ID` equal to the claim's `triaged_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` — the role is authorised, the person is not."

        Design: Corner/rbac/same_adjuster_triage_then_decide_rejected
        """
        env = fx.build_base_env(api)
        claim = fx.file_claim(api, env.subscription_id)
        fx.triage_claim(api, claim["id"], ADJUSTER_A)

        validate_error(
            api.decide_claim(
                claim["id"], f.decide_payload("APPROVE", "Self-approving"), ADJUSTER_A
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )
        blocked = validate_success(api.get_claim(claim["id"], OPERATOR))
        assert blocked["status"] == "UNDER_REVIEW"
        assert blocked["decided_by_user_id"] is None

        asked = validate_success(
            api.request_claim_info(
                claim["id"], f.request_info_payload("Please attach the vendor invoice"), ADJUSTER_A
            )
        )
        assert asked["status"] == "INFO_REQUESTED"
        assert asked["info_request_round"] == 1
        resubmitted = validate_success(
            api.resubmit_claim(claim["id"], OPERATOR, f.resubmit_payload("Vendor invoice attached"))
        )
        assert resubmitted["status"] == "UNDER_REVIEW"

        validate_error(
            api.decide_claim(
                claim["id"], f.decide_payload("DENY", "Still self-deciding"), ADJUSTER_A
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )

        decided = validate_success(
            api.decide_claim(
                claim["id"], f.decide_payload("APPROVE", "Second adjuster approves"), ADJUSTER_B
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "adj-002"
        assert decided["triaged_by_user_id"] == "adj-001"
        assert decided["info_request_round"] == 1
        a.assert_cents(decided["approved_amount_cents"], 30000, "approved_amount_cents")


class TestResidentWriteSurface:
    """The resident's own records are readable and surveyable, nothing more."""

    def test_the_resident_is_refused_every_operator_only_write_on_her_own_records(self, api):
        """
        Catalog registration, shipment dispatch, evidence scoring and the logical
        clock are all closed to the resident even when the target record is her
        own — the shipment keeps its SCHEDULED status and null tracking code and
        the clock keeps its instant — while her renewal survey and her entitlement
        read both succeed.

        PRD §2.1: "Residents may answer renewal surveys, file, resubmit and withdraw their own claims, cancel their own subscription, and read their own records; they may not score evidence, confirm a case, adjudicate, or move money."

        Design: Corner/rbac/resident_cannot_perform_operator_only_catalog_and_fulfilment_writes
        """
        env = fx.build_base_env(api)
        ada = make_resident_headers(env.resident_id)
        shipment = fx.first_shipment(api, env.subscription_id)

        validate_error(
            api.create_filter_sku(
                f.filter_sku_payload(sku_code="SKU-ROGUE", unit_cost_cents=1, ship_weight_oz=1),
                ada,
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.ship_shipment(shipment["id"], f.ship_payload("1Z-SELF-SHIP"), ada),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RENEWAL_SURVEY", "2026-08-05"),
                ada,
            ),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api.set_clock(f.clock_payload("2026-08-06T00:00:00Z"), ada),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

        held = validate_success(api.get_shipment(shipment["id"], OPERATOR))
        assert held["status"] == "SCHEDULED"
        assert held["tracking_code"] is None

        survey = validate_success(
            api.create_renewal_survey(
                env.subscription_id, f.renewal_survey_payload(True, 1, "2026-08-05"), ada
            ),
            201,
        )
        a.assert_instant_equals(survey["submitted_at"], "2026-08-05T00:00:00Z")

        _rows, meta = validate_paginated(
            api.list_benefit_entitlements(env.subscription_id, ada)
        )
        assert meta["total_count"] == 4
