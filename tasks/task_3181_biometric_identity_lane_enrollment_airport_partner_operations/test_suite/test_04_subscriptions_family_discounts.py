"""Subscriptions, family groups, discounts, and billing: deferred upgrade vs
immediate downgrade, per-line invoice rounding, OCC on plan change, version
increments, redemption invariant, family slot invariant, and subscription
cancel gating."""
from test_helpers import (
    ApiErrorId,
    add_family_member,
    attach_discount,
    cancel_subscription,
    change_plan,
    create_active_member,
    create_discount,
    create_enrollment_center,
    create_subscription,
    detach_discount,
    get_family_group_for_subscription,
    make_member_headers,
    register_member,
    run_invoice_cycle,
    set_clock,
    setup_airport_with_active_agreement,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS, PM


class TestPlanChangeAsymmetry:
    def _setup_two_members(self):
        airport, _ = setup_airport_with_active_agreement("AUS")
        center = create_enrollment_center(airport["id"], name="AUS Center")
        member_a = create_active_member(
            center, email="a@x.com", full_name="Member A", date_of_birth="1990-01-01",
            document_number="PA1111111",
        )
        sub_a = create_subscription(member_a, plan="INDIVIDUAL", billing_cycle_day=1)
        member_b = create_active_member(
            center, email="b@x.com", full_name="Member B", date_of_birth="1991-01-01",
            document_number="PB2222222",
        )
        sub_b = create_subscription(member_b, plan="FAMILY", billing_cycle_day=1)
        return member_a, sub_a, member_b, sub_b

    def test_individual_to_family_is_deferred(self, api):
        """PRD §3.4: "Switching from `INDIVIDUAL` to `FAMILY` is always deferred: the request
        records `pending_plan`, and the change is applied at the next renewal" and
        "No pro-rata mid-cycle invoice is ever issued for the upgrade direction."

        Design: Difficulty/dual_variant_calc/plan_upgrade_deferred_vs_downgrade_immediate_diverge
        """
        member_a, sub_a, _, _ = self._setup_two_members()
        changed = change_plan(sub_a, "FAMILY", sub_a["version"], member_a)
        assert changed["plan"] == "INDIVIDUAL", "upgrade is deferred: plan unchanged"
        assert changed["pending_plan"] == "FAMILY"
        assert changed["price_cents"] == 18900, "price unchanged mid-cycle"
        assert changed["version"] == sub_a["version"] + 1

    def test_family_to_individual_applies_immediately(self, api):
        """PRD §3.4: "Switching from `FAMILY` to `INDIVIDUAL` applies immediately with no
        refund of the current period: `price_cents` is recomputed and the family group
        is dissolved."

        Design: Difficulty/dual_variant_calc/plan_upgrade_deferred_vs_downgrade_immediate_diverge
        """
        _, _, member_b, sub_b = self._setup_two_members()
        changed = change_plan(sub_b, "INDIVIDUAL", sub_b["version"], member_b)
        assert changed["plan"] == "INDIVIDUAL", "downgrade applies immediately"
        assert changed.get("pending_plan") is None
        assert changed["version"] == sub_b["version"] + 1


class TestInvoicePerLineRounding:
    def _setup_family_with_two_dependants(self):
        airport, _ = setup_airport_with_active_agreement("SEA")
        center = create_enrollment_center(airport["id"], name="SEA Center")
        primary = create_active_member(
            center, email="primary@x.com", full_name="Pri Mary",
            date_of_birth="1990-01-01", document_number="P1234567",
        )
        sub = create_subscription(primary, plan="FAMILY", billing_cycle_day=1)
        create_discount(
            airport["id"], code="SEA15", percent_off=15, max_redemptions=10,
            expires_at="2027-01-01T00:00:00Z",
        )
        attach_discount(sub, "SEA15", primary)
        group = get_family_group_for_subscription(sub, primary)
        for i, (email, name, dob, doc) in enumerate([
            ("dep1@x.com", "Dep One", "1992-02-02", "P7654321"),
            ("dep2@x.com", "Dep Two", "1994-03-03", "P7654322"),
        ]):
            dep = create_active_member(
                center, email=email, full_name=name, date_of_birth=dob,
                document_number=doc,
            )
            group = add_family_member(group, dep, primary)
        return primary, sub, group

    def test_family_invoice_amount_is_sum_of_rounded_lines(self, api):
        """PRD §3.4: "The base is 18900 cents for either plan. When a discount is attached,
        the discount factor is one minus `percent_off` hundredths; otherwise the
        factor is one. The discounted base rounds half up to whole cents. For a
        family plan, each dependant — that is, `slots_used` minus one members —
        contributes a line of 9900 cents times the discount factor, each line
        independently rounded half up to whole cents. The invoice `amount_cents` is
        the discounted base plus the sum of the rounded lines."

        15% off: base round(18900*0.85) = 16065; each dependant line
        round(9900*0.85) = 8415; total 16065 + 2*8415 = 32895.

        Design: Difficulty/combinatorial_formula/invoice_per_line_round_then_sum_order_pinned
        """
        _, sub, group = self._setup_family_with_two_dependants()
        assert group["slots_used"] == 3
        invoice = run_invoice_cycle(sub)
        assert invoice["amount_cents"] == 32895, (
            f"16065 + 2*8415 = 32895, got {invoice['amount_cents']}"
        )

    def test_family_price_cents_is_discounted_base_only(self, api):
        """PRD §3.4: "The subscription's own `price_cents` equals the discounted base for
        both plans; the dependant lines appear on the invoice, not on `price_cents`."

        15% off a 18900 base -> price_cents 16065 even with two dependants attached.

        Design: Difficulty/combinatorial_formula/invoice_per_line_round_then_sum_order_pinned
        """
        _, sub, _ = self._setup_family_with_two_dependants()
        sub_after = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_after["price_cents"] == 16065


class TestChangePlanOcc:
    def _setup_member_with_subscription(self):
        airport, _ = setup_airport_with_active_agreement("SYR")
        center = create_enrollment_center(airport["id"], name="SYR Center")
        member = create_active_member(
            center, email="occ@x.com", full_name="Occ Member",
            date_of_birth="1990-01-01", document_number="PO000900",
        )
        sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
        return member, sub

    def test_stale_subscription_version_rejected_412(self, api):
        """PRD §2.6: "Second, changing a subscription's plan requires the non-optional input
        `expected_subscription_version`, carrying the subscription `version` the
        client last observed. If the version has advanced since — for instance because
        a renewal invoice applied a deferred plan change — the request is rejected
        with `ERR_STALE_VERSION` so the client re-reads `price_cents` before deciding."

        Design: Corner/cross_cutting_layers/change_plan_occ_stale_version_412
        """
        member, sub = self._setup_member_with_subscription()
        resp = api.change_plan(
            sub["id"], "FAMILY", sub["version"] - 1, make_member_headers(member["id"])
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_current_subscription_version_succeeds_and_bumps_once(self, api):
        """PRD §2.6: "changing a subscription's plan requires the non-optional input
        `expected_subscription_version`, carrying the subscription `version` the
        client last observed." and PRD §3.4: "Every plan change carries the OCC guard
        of §2.6 and increments the subscription's `version` by one regardless of
        direction."

        Design: Corner/cross_cutting_layers/change_plan_occ_stale_version_412
        """
        member, sub = self._setup_member_with_subscription()
        changed = change_plan(sub, "FAMILY", sub["version"], member)
        assert changed["pending_plan"] == "FAMILY"
        assert changed["version"] == sub["version"] + 1


class TestVersionIncrementsOnMutation:
    def test_attach_then_detach_increments_version_by_one_each(self, api):
        """PRD §2.4: "All entities except `BiometricRetentionLog` additionally carry
        `updated_at` and an integer `version` that starts at 1 and increments by
        exactly one on every mutation of that entity."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        airport, _ = setup_airport_with_active_agreement("PWM")
        center = create_enrollment_center(airport["id"], name="PWM Center")
        create_discount(
            airport["id"], code="PWM10", percent_off=10, max_redemptions=5,
            expires_at="2027-01-01T00:00:00Z",
        )
        member = create_active_member(
            center, email="ver@x.com", full_name="Ver Member",
            date_of_birth="1990-01-01", document_number="PV000910",
        )
        sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
        assert sub["version"] == 1
        attached = attach_discount(sub, "PWM10", member)
        assert attached["version"] == 2, "attach-discount increments exactly 1"
        detached = detach_discount(sub, member)
        assert detached["version"] == 3, "detach-discount increments exactly 1"


class TestDiscountRedemptionInvariant:
    def _setup_three_members_with_subscriptions(self):
        airport, _ = setup_airport_with_active_agreement("STL")
        center = create_enrollment_center(airport["id"], name="STL Center")
        discount = create_discount(
            airport["id"], code="STL50", percent_off=50, max_redemptions=2,
            expires_at="2027-01-01T00:00:00Z",
        )
        members = []
        for i, letter in enumerate("abc"):
            member = create_active_member(
                center, email=f"s{letter}@x.com", full_name=f"Sub {letter.upper()}",
                date_of_birth=f"199{ i }-01-01", document_number=f"PS00000{i + 1}",
            )
            sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
            members.append((member, sub))
        return discount, members

    def test_attach_detach_never_decrements_and_third_attach_exhausted(self, api):
        """PRD §3.4: "A successful attach increments `redemptions_used` (which is never
        decremented, even on detach or cancel), flips the discount to `EXHAUSTED` the
        moment the counter reaches the cap" and "a discount whose `redemptions_used`
        has reached `max_redemptions` has already flipped to `EXHAUSTED` and attaching
        to it fails with `ERR_DISCOUNT_EXHAUSTED`."

        Design: Difficulty/compensating_invariant/discount_redemption_invariant_attach_detach_never_decrements
        """
        discount, members = self._setup_three_members_with_subscriptions()
        member_a, sub_a = members[0]
        member_b, sub_b = members[1]
        member_c, sub_c = members[2]
        attached_a = attach_discount(sub_a, "STL50", member_a)
        assert attached_a["price_cents"] == 9450, "50% off 18900"
        attach_discount(sub_b, "STL50", member_b)
        detached_b = detach_discount(sub_b, member_b)
        assert detached_b["price_cents"] == 18900, "detach restores full price"
        resp = api.attach_discount(sub_c["id"], "STL50", make_member_headers(member_c["id"]))
        validate_error(resp, ApiErrorId.ERR_DISCOUNT_EXHAUSTED)
        discount_after = validate_success(api.get_discount(discount["id"], PM))
        assert discount_after["redemptions_used"] == 2, (
            "the detach did NOT decrement the conserved counter"
        )
        assert discount_after["status"] == "EXHAUSTED"

    def test_detach_recomputes_full_price_and_counter_conserved(self, api):
        """PRD §3.4: "Detaching clears `partner_discount_id` and recomputes `price_cents` at
        full price." and "A successful attach increments `redemptions_used` (which is
        never decremented, even on detach or cancel)"

        Design: Difficulty/compensating_invariant/discount_redemption_invariant_attach_detach_never_decrements
        """
        discount, members = self._setup_three_members_with_subscriptions()
        member_a, sub_a = members[0]
        attach_discount(sub_a, "STL50", member_a)
        detached = detach_discount(sub_a, member_a)
        assert detached.get("partner_discount_id") is None
        assert detached["price_cents"] == 18900
        discount_after = validate_success(api.get_discount(discount["id"], PM))
        assert discount_after["redemptions_used"] == 1


class TestDiscountExpiry:
    def test_attach_at_expires_at_rejected(self, api):
        """PRD §3.4: "The attach requires the discount to be `ACTIVE`, the logical clock to
        be strictly before `expires_at` (`ERR_DISCOUNT_EXPIRED` at or past it)"

        Design: Corner/errors/discount_expired_attach_rejected
        """
        airport, _ = setup_airport_with_active_agreement("GPT")
        center = create_enrollment_center(airport["id"], name="GPT Center")
        create_discount(
            airport["id"], code="GPT10", percent_off=10, max_redemptions=5,
            expires_at="2026-09-10T00:00:00Z",
        )
        member = create_active_member(
            center, email="gpt@x.com", full_name="Gpt User",
            date_of_birth="1990-01-01", document_number="PG000600",
        )
        sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
        set_clock("2026-09-10T00:00:00Z")
        resp = api.attach_discount(sub["id"], "GPT10", make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_DISCOUNT_EXPIRED)


class TestFamilyGroupFullBoundary:
    def _setup_family_with_three_candidates(self):
        airport, _ = setup_airport_with_active_agreement("MIA")
        center = create_enrollment_center(airport["id"], name="MIA Center")
        primary = create_active_member(
            center, email="fam0@x.com", full_name="Fam Zero",
            date_of_birth="1980-01-01", document_number="PF000001",
        )
        sub = create_subscription(primary, plan="FAMILY", billing_cycle_day=1)
        group = get_family_group_for_subscription(sub, primary)
        dependants = []
        for i in (1, 2, 3):
            dep = create_active_member(
                center, email=f"fam{i}@x.com", full_name=f"Fam {i}",
                date_of_birth=f"198{2 * i}-01-01", document_number=f"PF00000{i + 1}",
            )
            dependants.append(dep)
        return primary, sub, group, dependants

    def test_boundary_add_to_full_succeeds_then_next_rejected(self, api):
        """PRD §3.4: "Family groups carry `primary_subscription_id`, a `slots_total` of two
        or three (the total counting the primary), and a `slots_used` counter that
        must never exceed `slots_total`; the boundary where `slots_used` equals
        `slots_total` is full." and "attaching into a full group fails with
        `ERR_FAMILY_FULL`."

        Design: Difficulty/boundary_precision_check/family_group_full_boundary_at_slots_total
        """
        primary, sub, group, dependants = self._setup_family_with_three_candidates()
        group = add_family_member(group, dependants[0], primary)
        assert group["slots_used"] == 2
        group = add_family_member(group, dependants[1], primary)
        assert group["slots_used"] == 3, "the add reaching slots_total succeeds"
        resp = api.add_family_member(
            group["id"], dependants[2]["id"], make_member_headers(primary["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FAMILY_FULL)
        rejected_member = validate_success(api.get_member(dependants[2]["id"], OPS))
        assert rejected_member.get("family_group_id") is None, (
            "rejected attach has no side effect"
        )

    def test_family_group_starts_with_primary_attached(self, api):
        """PRD §3.4: "choosing `FAMILY` also creates an empty `FamilyGroup` for the
        subscription with the primary member already attached, so `slots_used` starts
        at one."

        Design: Difficulty/boundary_precision_check/family_group_full_boundary_at_slots_total
        """
        airport, _ = setup_airport_with_active_agreement("MIA")
        center = create_enrollment_center(airport["id"], name="MIA Center")
        primary = create_active_member(
            center, email="fam0@x.com", full_name="Fam Zero",
            date_of_birth="1980-01-01", document_number="PF000001",
        )
        sub = create_subscription(primary, plan="FAMILY", billing_cycle_day=1)
        group = get_family_group_for_subscription(sub, primary)
        assert group["slots_used"] == 1
        assert group["slots_total"] == 3


class TestFamilySlotInvariant:
    def _setup_family(self):
        airport, _ = setup_airport_with_active_agreement("MSP")
        center = create_enrollment_center(airport["id"], name="MSP Center")
        primary = create_active_member(
            center, email="p@x.com", full_name="Pri P",
            date_of_birth="1980-01-01", document_number="PM000001",
        )
        sub = create_subscription(primary, plan="FAMILY", billing_cycle_day=1)
        group = get_family_group_for_subscription(sub, primary)
        deps = []
        for i, (email, name, dob, doc) in enumerate([
            ("d1@x.com", "Dep One", "1982-01-01", "PM000002"),
            ("d2@x.com", "Dep Two", "1984-01-01", "PM000003"),
        ]):
            dep = create_active_member(
                center, email=email, full_name=name, date_of_birth=dob,
                document_number=doc,
            )
            deps.append(dep)
        return primary, sub, group, deps

    def test_add_remove_pairs_keep_slots_used_exact(self, api):
        """PRD §3.4: "The primary member attaches a dependant by `member_id`; the added
        member must be `ACTIVE` and not already attached to another group" and
        "Detaching a member (never the primary) — addressed by the group's `id` and
        the `memberId` of the dependant in the path — decrements `slots_used` and
        clears that member's `family_group_id`."

        Design: Difficulty/compensating_invariant/family_slots_used_invariant_add_remove_cancel
        """
        primary, sub, group, deps = self._setup_family()
        assert group["slots_used"] == 1
        group = add_family_member(group, deps[0], primary)
        assert group["slots_used"] == 2
        group = add_family_member(group, deps[1], primary)
        assert group["slots_used"] == 3
        resp = api.remove_family_member(
            group["id"], deps[0]["id"], make_member_headers(primary["id"])
        )
        after = validate_success(resp)
        assert after["slots_used"] == 2, "compensating removal leaves the count exact"
        dep0 = validate_success(api.get_member(deps[0]["id"], OPS))
        assert dep0.get("family_group_id") is None

    def test_subscription_cancel_dissolves_group_and_detaches_members(self, api):
        """PRD §3.4: "Cancellation moves the family group to its terminal `DISSOLVED` status
        (detaching all dependants and clearing each `family_group_id`)"

        Design: Difficulty/compensating_invariant/family_slots_used_invariant_add_remove_cancel
        """
        primary, sub, group, deps = self._setup_family()
        group = add_family_member(group, deps[0], primary)
        group = add_family_member(group, deps[1], primary)
        cancel_subscription(sub, primary)
        group_after = validate_success(api.get_family_group(group["id"], OPS))
        assert group_after["status"] == "DISSOLVED"
        assert group_after["slots_used"] == 0
        dep1 = validate_success(api.get_member(deps[1]["id"], OPS))
        assert dep1.get("family_group_id") is None


class TestSubscriptionCancelGate:
    def test_suspended_member_cannot_self_cancel(self, api):
        """PRD §3.4: "Voluntary cancellation is a member action on a subscription in `ACTIVE`
        or `PAST_DUE`, but only while the member itself is `ACTIVE` — a suspended
        member cannot self-cancel (`ERR_MEMBER_NOT_ACTIVE`) because their cancellation
        rides the dispute cascade instead."

        Design: Corner/validations/subscription_self_cancel_blocked_while_suspended
        """
        airport, _ = setup_airport_with_active_agreement("DSM")
        center = create_enrollment_center(airport["id"], name="DSM Center")
        member = create_active_member(
            center, email="sus@x.com", full_name="Sus Member",
            date_of_birth="1990-01-01", document_number="PS000100",
        )
        sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
        validate_success(api.admin_suspend_member(member["id"], OPS))
        resp = api.cancel_subscription(sub["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        sub_after = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_after["status"] == "ACTIVE", "subscription unchanged"
