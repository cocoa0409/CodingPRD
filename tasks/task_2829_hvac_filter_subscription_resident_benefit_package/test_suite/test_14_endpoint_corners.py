"""
Endpoint corners: the logical clock that mutates nothing yet changes every later
write, the read-only settlement preview, the amount predicate on the payout
action, and the nested unit list's parent scoping.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CLAIM_STATE_INVALID, ERR_PROPERTY_NOT_FOUND
from test_helpers.test_users import ADJUSTER_A, ADJUSTER_B, OPERATOR


class TestLogicalClock:
    """The startup default, and repointing it between two identical writes."""

    def test_the_startup_default_and_a_repointing_drive_two_identical_activations(
        self, api
    ):
        """
        Without ever calling the clock endpoint the first activation must read
        2026-08-01, billing the whole 31-day month at 3546; after the clock is
        repointed to 11 September the identical activation on a sibling unit bills
        20 of 30 days at 2364 — and the repointing itself mutated no record.

        PRD §2.4: "The clock's startup default is exactly `2026-08-01T00:00:00Z`, and before any operator advances it, every date computation, deadline, coverage window and staleness comparison reads that default value."

        Design: Corner/endpoints/logical_clock_default_and_repointing_drive_every_temporal_read
        """
        env = fx.build_base_env(
            api, activate=False, clock_at_enrollment=None, set_initial_clock=False
        )
        unit_b = fx.create_unit(api, env.property_id, unit_label="A-102")
        resident_b = fx.create_resident(
            api, full_name="Ben Ortiz", email="ben.ortiz@example.com", household_size=3
        )
        subscription_b = fx.create_subscription(api, resident_b["id"], unit_b["id"])

        activated_a = validate_success(api.activate_subscription(env.subscription_id, OPERATOR))
        a.assert_instant_equals(activated_a["activated_at"], "2026-08-01T00:00:00Z")
        rows_a, meta_a = validate_paginated(
            api.list_ledger_entries(
                env.subscription_id, OPERATOR, {"entry_type": "MONTHLY_FEE"}
            )
        )
        assert meta_a["total_count"] == 1
        a.assert_cents(rows_a[0]["amount_cents"], 3546, "first month at the default clock")
        shipment_a = fx.first_shipment(api, env.subscription_id)
        assert shipment_a["scheduled_ship_date"] == "2026-08-01"
        assert shipment_a["sequence_number"] == 1

        property_before = fx.read_property(api, env.property_id)
        clock = fx.set_clock(api, "2026-09-11T00:00:00Z")
        a.assert_instant_equals(clock["current_utc"], "2026-09-11T00:00:00Z")
        property_after = fx.read_property(api, env.property_id)
        assert property_after["version"] == property_before["version"]
        assert property_after["unit_count"] == property_before["unit_count"]
        _subscriptions, subscription_meta = validate_paginated(api.list_subscriptions(OPERATOR))
        assert subscription_meta["total_count"] == 2

        activated_b = validate_success(api.activate_subscription(subscription_b["id"], OPERATOR))
        a.assert_instant_equals(activated_b["activated_at"], "2026-09-11T00:00:00Z")
        rows_b, meta_b = validate_paginated(
            api.list_ledger_entries(
                subscription_b["id"], OPERATOR, {"entry_type": "MONTHLY_FEE"}
            )
        )
        assert meta_b["total_count"] == 1
        a.assert_cents(rows_b[0]["amount_cents"], 2364, "first month after the repointing")
        shipment_b = fx.first_shipment(api, subscription_b["id"])
        assert shipment_b["scheduled_ship_date"] == "2026-09-11"

        assert a.property_balance(api, env.property_id, OPERATOR) == 10910


class TestSettlementPreview:
    """The computed read, and its agreement with the write that follows it."""

    def test_the_preview_is_repeatable_side_effect_free_and_matches_the_cancel(self, api):
        """
        The preview exposes the whole waterfall for a hypothetical date, returns
        the same eight figures twice, leaves the subscription, the shipment, the
        ledger and the balance untouched — and the cancellation that follows
        freezes exactly those numbers.

        PRD §3.9: "The preview mutates nothing: no state changes, no ledger rows, no frozen fields, no version bumps."

        Design: Corner/endpoints/settlement_preview_is_repeatable_and_side_effect_free
        """
        env = fx.build_base_env(api)
        shipment = fx.deliver_first_shipment(
            api, env.subscription_id, "2026-08-06T00:00:00Z"
        )
        fx.set_clock(api, "2026-09-11T00:00:00Z")

        def read_preview():
            return validate_success(
                api.get_settlement(
                    env.subscription_id, OPERATOR, {"effective_date": "2026-09-11"}
                )
            )

        for preview in (read_preview(), read_preview()):
            assert preview["subscription_id"] == env.subscription_id
            assert preview["used_days"] == 10
            assert preview["unused_days"] == 20
            a.assert_cents(
                preview["gross_prorated_credit_cents"], 2364, "gross_prorated_credit_cents"
            )
            assert preview["exposed_shipment_count"] == 1
            a.assert_cents(
                preview["unreturned_fee_gross_cents"], 1360, "unreturned_fee_gross_cents"
            )
            a.assert_decimal_string(preview["waiver_credit_pct"], "0.25", "waiver_credit_pct")
            a.assert_cents(
                preview["unreturned_fee_net_cents"], 1020, "unreturned_fee_net_cents"
            )
            a.assert_cents(preview["net_settlement_cents"], 1344, "net_settlement_cents")

        untouched = fx.read_subscription(api, env.subscription_id)
        assert untouched["status"] == "ACTIVE"
        assert untouched["version"] == 2
        assert validate_success(api.get_shipment(shipment["id"], OPERATOR))["status"] == (
            "DELIVERED"
        )
        _rows, meta = validate_paginated(api.list_ledger_entries(env.subscription_id, OPERATOR))
        assert meta["total_count"] == 2
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

        cancelled = validate_success(
            api.cancel_subscription(
                env.subscription_id, f.cancel_payload("2026-09-11", "Move-out"), OPERATOR
            )
        )
        a.assert_cents(
            cancelled["gross_prorated_credit_cents"], 2364, "gross_prorated_credit_cents"
        )
        a.assert_decimal_string(cancelled["waiver_credit_pct"], "0.25", "waiver_credit_pct")
        a.assert_cents(
            cancelled["unreturned_fee_gross_cents"], 1360, "unreturned_fee_gross_cents"
        )
        a.assert_cents(cancelled["unreturned_fee_net_cents"], 1020, "unreturned_fee_net_cents")
        a.assert_cents(cancelled["net_settlement_cents"], 1344, "net_settlement_cents")
        assert a.property_balance(api, env.property_id, OPERATOR) == 4244


class TestPayoutPredicate:
    """APPROVED is necessary but not sufficient for a disbursement."""

    def test_an_approved_claim_worth_nothing_cannot_be_paid(self, api):
        """
        A damage-waiver claim requested at exactly the deductible approves at zero
        cents and is unpayable — no payout row, no paid_at — while a claim approved
        at 30000 on the same subscription disburses and drives the balance
        negative.

        PRD §3.7: "A `ProgramOperator` disburses an approved claim, which requires the claim to be `APPROVED` with an `approved_amount_cents` greater than zero."

        Design: Corner/endpoints/paying_an_approved_claim_worth_zero_cents_rejected
        """
        env = fx.build_base_env(api)
        zero_claim = fx.file_claim(
            api,
            env.subscription_id,
            requested_amount_cents=5000,
            description="Scuffed filter door, at the deductible",
        )
        fx.triage_claim(api, zero_claim["id"], ADJUSTER_A)
        approved_zero = validate_success(
            api.decide_claim(
                zero_claim["id"], f.decide_payload("APPROVE", "Covered at zero"), ADJUSTER_B
            )
        )
        assert approved_zero["status"] == "APPROVED"
        a.assert_cents(approved_zero["provisional_amount_cents"], 0, "provisional_amount_cents")
        a.assert_cents(approved_zero["approved_amount_cents"], 0, "approved_amount_cents")

        paying_claim = fx.file_claim(
            api,
            env.subscription_id,
            requested_amount_cents=40000,
            description="Return grille torn during filter change",
        )
        fx.triage_claim(api, paying_claim["id"], ADJUSTER_A)
        fx.approve_claim(api, paying_claim["id"], ADJUSTER_B)

        validate_error(
            api.pay_claim(zero_claim["id"], OPERATOR), ERR_CLAIM_STATE_INVALID, 409
        )
        unpaid = validate_success(api.get_claim(zero_claim["id"], OPERATOR))
        assert unpaid["status"] == "APPROVED"
        assert unpaid["paid_at"] is None
        rows = fx.read_ledger(api, env.subscription_id)
        assert a.find_ledger_rows(rows, "CLAIM_PAYOUT") == []

        paid = validate_success(api.pay_claim(paying_claim["id"], OPERATOR))
        assert paid["status"] == "PAID"
        a.assert_cents(paid["approved_amount_cents"], 30000, "approved_amount_cents")
        a.assert_instant_equals(paid["paid_at"], "2026-08-05T00:00:00Z")

        payouts = a.find_ledger_rows(fx.read_ledger(api, env.subscription_id), "CLAIM_PAYOUT")
        assert len(payouts) == 1
        a.assert_ledger_row(
            payouts[0], "CLAIM_PAYOUT", -30000, "PROPERTY_MANAGER", paying_claim["id"]
        )
        assert a.property_balance(api, env.property_id, OPERATOR) == -24412


class TestNestedUnitListing:
    """Reverse reachability: the list is scoped by its parent, and 404s without one."""

    def test_the_nested_unit_list_is_scoped_filtered_paginated_and_parent_checked(
        self, api
    ):
        """
        Each property's unit list returns only its own units and agrees with the
        property's own unit_count, composes the parent scope with a status filter
        and with pagination, and answers a well-formed but unknown parent with a
        404 rather than an empty page.

        PRD §2.5: "These nested paths exist purely as reverse lookups over a foreign key; they do not imply that the child is stored inside the parent."

        Design: Corner/endpoints/nested_unit_list_is_scoped_to_its_parent_property
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        property_a = fx.create_property(api)
        unit_ids = [
            fx.create_unit(api, property_a["id"], unit_label=label)["id"]
            for label in ("A-101", "A-102", "A-103")
        ]
        property_b = fx.create_property(api, name="Birch Court")
        unit_b_id = fx.create_unit(api, property_b["id"], unit_label="B-101")["id"]

        rows_a, meta_a = validate_paginated(
            api.list_property_units(property_a["id"], OPERATOR)
        )
        assert meta_a["total_count"] == 3
        assert {row["id"] for row in rows_a} == set(unit_ids)
        assert unit_b_id not in {row["id"] for row in rows_a}

        rows_b, meta_b = validate_paginated(
            api.list_property_units(property_b["id"], OPERATOR)
        )
        assert meta_b["total_count"] == 1
        assert rows_b[0]["id"] == unit_b_id

        assert fx.read_property(api, property_a["id"])["unit_count"] == 3
        assert fx.read_property(api, property_b["id"])["unit_count"] == 1

        filtered, filtered_meta = validate_paginated(
            api.list_property_units(property_a["id"], OPERATOR, {"status": "OUT_OF_SERVICE"})
        )
        assert filtered == []
        assert filtered_meta["total_count"] == 0

        paged, paged_meta = validate_paginated(
            api.list_property_units(property_a["id"], OPERATOR, {"limit": 2, "offset": 0})
        )
        assert len(paged) == 2
        a.assert_page_meta(paged_meta, limit=2, offset=0, total_count=3, has_more=True)

        validate_error(
            api.list_property_units(NON_EXISTENT_UUID, OPERATOR), ERR_PROPERTY_NOT_FOUND, 404
        )
