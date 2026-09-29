"""
Operations refused because of another entity's state: a retired catalog SKU
blocking shipment scheduling, and a forfeited entitlement blocking a claim
approval.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_BENEFIT_NOT_ENTITLED, ERR_SKU_DISCONTINUED
from test_helpers.test_users import ADJUSTER_A, ADJUSTER_B, OPERATOR


def _two_sku_env(api):
    """
    Two subscriptions at one property: Ada on the MERV 8 SKU that is then
    retired, Ben on the MERV 11 SKU his allergy flag demands.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    sku_m8 = fx.create_sku(api)
    sku_m11 = fx.create_sku(
        api,
        sku_code="SKU-16251-M11",
        merv_rating=11,
        unit_cost_cents=1120,
        ship_weight_oz=15,
    )
    prop = fx.create_property(api)
    unit_a = fx.create_unit(api, prop["id"])
    fx.activate_property(api, prop["id"])
    unit_b = fx.create_unit(api, prop["id"], unit_label="A-102")
    resident_a = fx.create_resident(api)
    resident_b = fx.create_resident(
        api, full_name="Ben Ortiz", email="ben.ortiz@example.com", allergy_flag=True
    )
    fx.set_clock(api, "2026-08-05T00:00:00Z")

    sub_a = fx.create_subscription(api, resident_a["id"], unit_a["id"])
    fx.activate_subscription(api, sub_a["id"])
    sub_b = fx.create_subscription(api, resident_b["id"], unit_b["id"])
    fx.activate_subscription(api, sub_b["id"])

    validate_success(api.discontinue_filter_sku(sku_m8["id"], OPERATOR))
    return {
        "sku_m8_id": sku_m8["id"],
        "sku_m11_id": sku_m11["id"],
        "sub_a_id": sub_a["id"],
        "sub_b_id": sub_b["id"],
    }


class TestSchedulingAgainstCatalogState:
    """A live subscription cannot ship what the catalog has retired."""

    def test_a_retired_sku_blocks_scheduling_without_re_pointing_the_link(self, api):
        """
        Subscription A is ACTIVE and 2026-10-19 is cadence-legal for it, yet
        scheduling is refused with ERR_SKU_DISCONTINUED purely because its assigned
        catalog entry is retired — and that entry is still the one the subscription
        names, because retirement re-points nothing.

        PRD §3.1: "Retirement deliberately does **not** re-point the subscriptions already mapped to that SKU — their `assigned_sku_id` keeps naming the retired entry."

        Design: Difficulty/cross_entity_state_dependency/shipment_scheduling_blocked_by_discontinued_filtersku_state
        """
        env = _two_sku_env(api)

        subscription = fx.read_subscription(api, env["sub_a_id"])
        assert subscription["status"] == "ACTIVE"
        assert subscription["assigned_sku_id"] == env["sku_m8_id"]
        assert subscription["ship_cadence_days"] == 75
        assert validate_success(api.get_filter_sku(env["sku_m8_id"], OPERATOR))["status"] == (
            "DISCONTINUED"
        )

        validate_error(
            api.create_shipment(
                env["sub_a_id"], f.shipment_payload("2026-10-19", 2), OPERATOR
            ),
            ERR_SKU_DISCONTINUED,
            422,
        )

        shipments = validate_success(
            api.list_shipments(OPERATOR, {"subscription_id": env["sub_a_id"]})
        )
        assert len(shipments) == 1
        assert fx.read_subscription(api, env["sub_a_id"])["shipment_sequence_counter"] == 1

    def test_the_sibling_subscription_on_a_live_sku_still_schedules(self, api):
        """
        Subscription B, mapped by its resident's allergy flag onto the untouched
        MERV 11 entry and running a 60-day cadence, schedules normally: the new
        shipment is SCHEDULED at sequence_number 2 with the SKU snapshotted from the
        subscription.

        PRD §3.5: "The new shipment is `SCHEDULED` with `version` 1, a `sequence_number` one greater than the highest `sequence_number` already used on that subscription — equivalently, the subscription's `shipment_sequence_counter` is advanced by one and its new value is stamped onto the shipment — and a `sku_id` copied from the subscription's current `assigned_sku_id` — that copy is a snapshot and is never re-pointed afterwards even if the subscription is later remapped onto a different catalog entry."

        Design: Difficulty/cross_entity_state_dependency/shipment_scheduling_blocked_by_discontinued_filtersku_state
        """
        env = _two_sku_env(api)

        subscription = fx.read_subscription(api, env["sub_b_id"])
        assert subscription["assigned_sku_id"] == env["sku_m11_id"]
        assert subscription["ship_cadence_days"] == 60

        created = validate_success(
            api.create_shipment(
                env["sub_b_id"], f.shipment_payload("2026-10-19", 2), OPERATOR
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["sku_id"] == env["sku_m11_id"]
        assert created["quantity"] == 2
        assert created["sequence_number"] == 2
        assert created["version"] == 1
        assert fx.read_subscription(api, env["sub_b_id"])["shipment_sequence_counter"] == 2


def _forfeited_claim_env(api):
    """
    A DAMAGE_WAIVER claim triaged while entitled, then overtaken by cascade A so
    the backing entitlement is FORFEITED before the decision.
    """
    env = fx.build_base_env(api)
    claim = validate_success(
        api.create_claim(
            f.claim_payload(
                env.subscription_id,
                description="Return grille torn during filter change",
            ),
            env.pm_headers,
        ),
        201,
    )
    triaged = validate_success(api.triage_claim(claim["id"], ADJUSTER_A))
    a.assert_cents(triaged["provisional_amount_cents"], 30000, "provisional_amount_cents")

    fx.deliver_first_shipment(api, env.subscription_id, "2026-08-06T00:00:00Z")
    fx.add_runtime_reading(
        api, env.unit_id, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z",
        168, 100, "PRESSURE_SENSOR",
    )
    fx.add_runtime_reading(
        api, env.unit_id, "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z",
        168, 120, "PRESSURE_SENSOR",
    )
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    case = fx.open_case(api, env.subscription_id, "RUNTIME_ANALYTICS", "2026-08-09")
    validate_success(api.send_case_notice(case["id"], OPERATOR))
    fx.set_clock(api, "2026-09-11T00:00:00Z")
    validate_success(api.confirm_case(case["id"], OPERATOR))
    return env, claim


class TestApprovalAgainstEntitlementState:
    """The decision-time re-check reads the entitlement as it stands now."""

    def test_approval_is_refused_once_the_backing_entitlement_is_forfeited(self, api):
        """
        The claim was legally filed and triaged while the damage waiver was ACTIVE,
        but cascade A has since forfeited that row, so the approving path is refused
        with ERR_BENEFIT_NOT_ENTITLED and the claim is left exactly as it was.

        PRD §3.7: "Then, on the approving path only, entitlement is re-checked against the state at the decision instant: the entitlement row whose `benefit_code` equals the `claim_type` must still be `ACTIVE`, and a row that has since been forfeited or expired yields `ERR_BENEFIT_NOT_ENTITLED`."

        Design: Difficulty/cross_entity_state_dependency/claim_approval_blocked_by_forfeited_benefit_entitlement_state
        """
        env, claim = _forfeited_claim_env(api)
        rows = fx.read_entitlements(api, env.subscription_id)
        a.assert_entitlement(
            a.entitlement_by_code(rows, "DAMAGE_WAIVER"),
            "FORFEITED",
            forfeit_reason="NON_INSTALL_CONFIRMED",
        )

        validate_error(
            api.decide_claim(
                claim["id"],
                f.decide_payload("APPROVE", "Attempting approval after forfeiture"),
                ADJUSTER_B,
            ),
            ERR_BENEFIT_NOT_ENTITLED,
            422,
        )

        after = validate_success(api.get_claim(claim["id"], ADJUSTER_B))
        assert after["status"] == "UNDER_REVIEW"
        assert after["approved_amount_cents"] is None
        assert after["decided_by_user_id"] is None
        a.assert_cents(after["provisional_amount_cents"], 30000, "provisional_amount_cents")

    def test_denial_of_the_same_claim_is_unaffected_and_moves_no_money(self, api):
        """
        The denying path runs no entitlement re-check, so the same claim can be
        denied by the same adjuster: it lands in DENIED with approved_amount_cents 0,
        posts no payout row, and leaves the balance at the 4921 cascade A had
        already set.

        PRD §3.7: "A denial moves it `UNDER_REVIEW → DENIED`, sets `approved_amount_cents` to 0, and posts no ledger row; `DENIED` is terminal."

        Design: Difficulty/cross_entity_state_dependency/claim_approval_blocked_by_forfeited_benefit_entitlement_state
        """
        env, claim = _forfeited_claim_env(api)

        denied = validate_success(
            api.decide_claim(
                claim["id"],
                f.decide_payload(
                    "DENY", "Damage waiver forfeited by confirmed non-installation"
                ),
                ADJUSTER_B,
            )
        )
        assert denied["status"] == "DENIED"
        a.assert_cents(denied["approved_amount_cents"], 0, "approved_amount_cents")
        assert denied["decided_by_user_id"] == "adj-002"
        assert denied["triaged_by_user_id"] == "adj-001"

        rows = fx.read_ledger(api, env.subscription_id)
        assert a.find_ledger_rows(rows, "CLAIM_PAYOUT") == []
        assert a.property_balance(api, env.property_id, OPERATOR) == 4921
