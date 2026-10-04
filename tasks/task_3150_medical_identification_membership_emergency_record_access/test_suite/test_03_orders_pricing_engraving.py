"""Product orders: lifecycle, pricing, engraving sync, OCC on confirm and
supersede, and compensating ledger invariants."""
from test_helpers import (
    ApiErrorId,
    add_product,
    add_record_item,
    add_verified_item,
    approve_item,
    confirm_order,
    create_product_payload,
    enroll_member,
    get_member,
    list_item_tickets,
    make_member_headers,
    open_ticket_for_item,
    place_and_confirm_order,
    place_order,
    set_clock,
    validate_error,
    validate_success,
)


def _sync_order_setup(api, member_overrides=None, product_overrides=None):
    """ACTIVE member + product + one PENDING SYNC_WITH_RECORD order after one
    VERIFIED item. Returns (member, product, order)."""
    set_clock(api=api)
    product = add_product(api=api, **(product_overrides or {}))
    member = enroll_member(api=api, **(member_overrides or {}))
    return member, product


class TestOrderHappyPath:
    def test_order_full_happy_path_pending_to_shipped(self, api, fulfillment_headers):
        """PRD §3.4: "After confirm, fulfillment is linear: a `FulfillmentAgent`
        engraves the order, moving `CONFIRMED` → `ENGRAVED` with an `AuditEvent`
        of action `ORDER_ENGRAVE`; then ships it, moving `ENGRAVED` → `SHIPPED`,
        which settles the ledger — the member's `balance_cents` is credited back by
        `price_cents` because the order is settled on shipment — the member's
        `version` increments by 1, and an `AuditEvent` with action `ORDER_SHIP` is
        appended."

        Design: Corner/state_machines/order_full_happy_path_pending_to_shipped
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="NK-1", product_name="Necklace",
                              base_price_cents=2000, max_engrave_chars=30)
        member = enroll_member(full_name="Sara Ship", email="sara@x.com", dob="1992-02-02", api=api)
        order = place_and_confirm_order(
            member["id"], product["id"], api=api, engraving_text="Sara N", engrave_mode="MANUAL"
        )
        assert validate_success(api.get_member(member["id"], make_member_headers(member["id"])))["balance_cents"] == 6000

        engraved = validate_success(api.engrave_order(member["id"], order["id"], fulfillment_headers))
        assert engraved["status"] == "ENGRAVED"
        shipped = validate_success(api.ship_order(member["id"], order["id"], fulfillment_headers))
        assert shipped["status"] == "SHIPPED"
        member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert member_after["balance_cents"] == 4000, (
            f"order settled on shipment; only the enrollment fee remains, got {member_after['balance_cents']}"
        )

    def test_confirm_then_engrave_state_progression_visible(self, api, fulfillment_headers):
        """PRD §3.4: "After confirm, fulfillment is linear: a `FulfillmentAgent`
        engraves the order, moving `CONFIRMED` → `ENGRAVED` with an `AuditEvent`
        of action `ORDER_ENGRAVE`; then ships it, moving `ENGRAVED` → `SHIPPED`,
        which settles the ledger — the member's `balance_cents` is credited back by
        `price_cents` because the order is settled on shipment — the member's
        `version` increments by 1, and an `AuditEvent` with action `ORDER_SHIP` is
        appended."

        Design: Corner/state_machines/order_full_happy_path_pending_to_shipped
        """
        set_clock(api=api)
        product = add_product(api=api, base_price_cents=2000)
        member = enroll_member(api=api)
        order = place_order(member["id"], product["id"], api=api, engraving_text="Sara N")
        assert order["status"] == "PENDING"
        confirmed = confirm_order(member["id"], order["id"], api=api)
        assert confirmed["status"] == "CONFIRMED"
        engraved = validate_success(api.engrave_order(member["id"], order["id"], fulfillment_headers))
        assert engraved["status"] == "ENGRAVED"


class TestEngraveInvalidState:
    def test_engrave_from_pending_returns_invalid_state(self, api, fulfillment_headers):
        """PRD §2.5: "State-machine from-state checks — `ERR_INVALID_STATE` when
        the target entity is not in the state the transition requires (for example,
        confirming an order that is not `PENDING`, engraving one that is not
        `CONFIRMED`, resolving a ticket that is not `OPEN`, or resolving a dispute
        that is not `UNDER_REVIEW`)."

        Design: Corner/state_machines/engrave_from_pending_returns_invalid_state
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="NK-2", product_name="Necklace2",
                              base_price_cents=2000, max_engrave_chars=30)
        member = enroll_member(full_name="Skip State", email="skip@x.com", dob="1992-02-02", api=api)
        order = place_order(member["id"], product["id"], api=api, engraving_text="Skip")
        resp = api.engrave_order(member["id"], order["id"], fulfillment_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_order(order["id"], fulfillment_headers))
        assert after["status"] == "PENDING"

    def test_engrave_from_pending_twice_still_pending(self, api, fulfillment_headers):
        """PRD §2.5: "State-machine from-state checks — `ERR_INVALID_STATE` when
        the target entity is not in the state the transition requires (for example,
        confirming an order that is not `PENDING`, engraving one that is not
        `CONFIRMED`, resolving a ticket that is not `OPEN`, or resolving a dispute
        that is not `UNDER_REVIEW`)."

        Design: Corner/state_machines/engrave_from_pending_returns_invalid_state
        """
        set_clock(api=api)
        product = add_product(api=api)
        member = enroll_member(api=api)
        order = place_order(member["id"], product["id"], api=api, engraving_text="Skip")
        validate_error(api.engrave_order(member["id"], order["id"], fulfillment_headers),
                       ApiErrorId.ERR_INVALID_STATE.value)
        validate_error(api.ship_order(member["id"], order["id"], fulfillment_headers),
                       ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_order(order["id"], fulfillment_headers))
        assert after["status"] == "PENDING"


class TestPremiumOrderDiscount:
    def test_premium_order_discount_applied_at_creation(self, api):
        """PRD §3.4: "`PREMIUM` members receive a fifteen percent discount on the
        base, rounded half-up to whole cents."

        Design: Corner/calculations/premium_order_discount_applied_at_creation
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="PM-1", product_name="Prem Band",
                              base_price_cents=10000, max_engrave_chars=30)
        member = enroll_member(full_name="Pam Premium", email="pam@x.com",
                               dob="1986-06-06", tier="PREMIUM", api=api)
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="Pam", engrave_mode="MANUAL")
        assert order["price_cents"] == 8500, (
            f"10000 * (1 - 0.15) = 8500 whole cents, got {order['price_cents']}"
        )

    def test_premium_discount_rounds_half_up(self, api):
        """PRD §3.4: "`PREMIUM` members receive a fifteen percent discount on the
        base, rounded half-up to whole cents."
        PRD §2.7: "Where a calculation multiplies a base by a fractional factor —
        the dependent discount on membership fees, or a percentage discount on an
        order — the product is rounded half-up to whole cents at the step the
        scaffold of each calculation pins (see §3.1 and §3.4)."

        Design: Corner/calculations/premium_order_discount_applied_at_creation
        """
        set_clock(api=api)
        # 1005 * 0.85 = 854.25 -> 854 (rounds down); 1015 * 0.85 = 862.75 -> 863 (rounds up).
        product_down = add_product(api=api, base_price_cents=1005)
        product_up = add_product(api=api, base_price_cents=1015)
        member = enroll_member(tier="PREMIUM", api=api)
        order_down = place_order(member["id"], product_down["id"], api=api, engraving_text="a")
        order_up = place_order(member["id"], product_up["id"], api=api, engraving_text="b")
        assert order_down["price_cents"] == 854
        assert order_up["price_cents"] == 863


class TestEngravingOverflow:
    def test_manual_engraving_overflow_rejected_at_create(self, api):
        """PRD §3.4: "For `MANUAL` orders the engraving text is taken as given,
        subject to capacity: if the text's length exceeds the product's
        `max_engrave_chars`, creation is rejected with `ERR_ENGRAVING_OVERFLOW`
        (HTTP 422) — the server never silently truncates."

        Design: Corner/validations/manual_engraving_overflow_rejected_at_create
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="SM-5", product_name="Tiny",
                              base_price_cents=1500, max_engrave_chars=5)
        member = enroll_member(full_name="Edgar Engrave", email="edgar@x.com", dob="1991-01-01", api=api)
        resp = api.create_order(
            member["id"],
            {"product_id": product["id"], "engraving_text": "123456", "engrave_mode": "MANUAL"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENGRAVING_OVERFLOW.value)
        ok = validate_success(
            api.create_order(
                member["id"],
                {"product_id": product["id"], "engraving_text": "12345", "engrave_mode": "MANUAL"},
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        assert ok["engraving_text"] == "12345"

    def test_manual_engraving_exactly_at_limit_succeeds(self, api):
        """PRD §3.4: "For `MANUAL` orders the engraving text is taken as given,
        subject to capacity: if the text's length exceeds the product's
        `max_engrave_chars`, creation is rejected with `ERR_ENGRAVING_OVERFLOW`
        (HTTP 422) — the server never silently truncates."

        Design: Corner/validations/manual_engraving_overflow_rejected_at_create
        """
        set_clock(api=api)
        product = add_product(api=api, max_engrave_chars=5)
        member = enroll_member(api=api)
        at_limit = place_order(member["id"], product["id"], api=api, engraving_text="12345")
        assert at_limit["status"] == "PENDING"
        assert at_limit["engraving_text"] == "12345"


class TestLifetimeFreeFirstSyncOrder:
    def _two_pending_sync_orders(self, api):
        """LIFETIME member with one VERIFIED CRITICAL item and two PENDING
        SYNC_WITH_RECORD orders on a 12000-cent product."""
        set_clock(api=api)
        product = add_product(api=api, product_sku="BR-STL", product_name="Stainless Bracelet",
                              base_price_cents=12000, max_engrave_chars=40)
        member = enroll_member(full_name="Lou Lifetime", email="lou@x.com",
                               dob="1980-01-01", tier="LIFETIME", api=api)
        add_verified_item(
            member["id"], api=api, item_kind="CONDITION", label="Diabetes",
            detail="Type 1", severity="CRITICAL", provider_document_ref="doc-1",
        )
        o1 = place_order(member["id"], product["id"], api=api,
                         engraving_text="ignored", engrave_mode="SYNC_WITH_RECORD")
        o2 = place_order(member["id"], product["id"], api=api,
                         engraving_text="ignored", engrave_mode="SYNC_WITH_RECORD")
        return member, o1, o2

    def test_lifetime_free_first_sync_order_provisional_free_final_paid_when_second_confirms(self, api):
        """PRD §3.4: "`LIFETIME` members receive a twenty-five percent discount on
        the base — except for their first-ever `SYNC_WITH_RECORD` order, which is
        free: its price is 0. The free-first-order entitlement is gated by the
        member's `first_lifetime_sync_order_consumed` flag, which is false until a
        `LIFETIME` member confirms an order in `SYNC_WITH_RECORD` mode; the flag is
        set at confirm time, not at creation."
        PRD §3.4: "In particular, two `PENDING` synchronized orders on a `LIFETIME`
        member both see the free provisional price; whichever confirms second
        re-prices to the discounted, non-free final price."

        Design: Difficulty/dual_variant_calc/lifetime_free_first_sync_order_provisional_free_final_paid_when_second_confirms
        """
        member, o1, o2 = self._two_pending_sync_orders(api)
        assert o1["price_cents"] == 0, "free provisional price (first SYNC order, LIFETIME)"
        assert o2["price_cents"] == 0, "both PENDING SYNC orders see the free provisional price"

        confirmed1 = confirm_order(member["id"], o1["id"], api=api)
        assert confirmed1["price_cents"] == 0
        assert confirmed1["status"] == "CONFIRMED"

        confirmed2 = confirm_order(member["id"], o2["id"], api=api)
        assert confirmed2["price_cents"] == 9000, (
            f"final = 12000 - 25% = 9000; the provisional 0 is NOT carried into confirm, "
            f"got {confirmed2['price_cents']}"
        )

        member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert member_after["first_lifetime_sync_order_consumed"] is True
        assert member_after["balance_cents"] == 50000 + 0 + 9000, (
            f"LIFETIME enrollment fee + both confirmed orders, got {member_after['balance_cents']}"
        )

    def test_lifetime_first_sync_confirm_stays_free_when_flag_unset(self, api):
        """PRD §3.4: "The provisional price therefore uses the tier and the flag as
        observed at creation, while the final price re-prices with the tier and the
        flag as observed at confirm — so when the tier or the flag changed between
        the two moments, the final price deliberately differs from the provisional
        one for identical product input."

        Design: Difficulty/dual_variant_calc/lifetime_free_first_sync_order_provisional_free_final_paid_when_second_confirms
        """
        set_clock(api=api)
        product = add_product(api=api, base_price_cents=12000, max_engrave_chars=40)
        member = enroll_member(tier="LIFETIME", dob="1980-01-01", api=api)
        add_verified_item(member["id"], api=api, item_kind="CONDITION", label="Diabetes",
                          detail="Type 1", severity="CRITICAL", provider_document_ref="doc-1")
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="ignored", engrave_mode="SYNC_WITH_RECORD")
        assert order["price_cents"] == 0
        confirmed = confirm_order(member["id"], order["id"], api=api)
        assert confirmed["price_cents"] == 0, (
            "flag still unset at this confirm: final price stays free"
        )
        after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert after["first_lifetime_sync_order_consumed"] is True


class TestOrderConfirmOcc:
    def test_occ_stale_expected_member_version_returns_412(self, api):
        """PRD §3.4: "Confirming an order is the point of commitment, and it is one
        of the two OCC-protected writes of §2.8: the request must carry
        `expected_member_version` matching the member's current `version`, and a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/state_machines/occ_stale_expected_member_version_returns_412
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="OC-1", product_name="Occ Band",
                              base_price_cents=1000, max_engrave_chars=30)
        member = enroll_member(full_name="Olga Occ", email="olga@x.com", dob="1990-09-09", api=api)
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="Olga", engrave_mode="MANUAL")
        stale_version = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )["version"]
        # Interleave a member mutation to bump the version: verifying a record
        # item increments Member.version by 1 (PRD §3.3) and leaves the MANUAL
        # order untouched (PRD §3.5 regeneration covers SYNC_WITH_RECORD only).
        add_verified_item(member["id"], api=api, item_kind="ALLERGY", label="Bump",
                          detail="bump", severity="LOW", provider_document_ref="doc-bump")

        resp = api.confirm_order(
            member["id"], order["id"],
            {"expected_member_version": stale_version},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        order_after = validate_success(api.get_order(order["id"], make_member_headers(member["id"])))
        assert order_after["status"] == "PENDING", "no state change after the 412"

        fresh_version = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )["version"]
        retry = validate_success(
            api.confirm_order(
                member["id"], order["id"],
                {"expected_member_version": fresh_version},
                make_member_headers(member["id"]),
            )
        )
        assert retry["status"] == "CONFIRMED"

    def test_occ_stale_version_returns_412_on_supersede_too(self, api):
        """PRD §2.8: "Superseding a verified record item likewise requires
        `expected_member_version`, the client's last observed `version` of the
        owning `Member`. If the supplied value does not equal the member's current
        `version` — because some other write has advanced the member since the
        client last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/state_machines/occ_stale_expected_member_version_returns_412
        """
        set_clock(api=api)
        member = enroll_member(api=api)
        item = add_verified_item(member["id"], api=api, label="OldLabel", severity="HIGH")
        stale_version = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )["version"]
        # Bump Member.version via a PRD-sanctioned mutation: approving another
        # record item increments Member.version by 1 (PRD §3.3).
        add_verified_item(member["id"], api=api, item_kind="ALLERGY", label="Bump",
                          detail="bump", severity="LOW", provider_document_ref="doc-bump2")
        resp = api.supersede_record_item(
            member["id"], item["id"],
            {
                "replacement_label": "NewLabel",
                "replacement_detail": "corrected",
                "provider_document_ref": "doc-new",
                "expected_member_version": stale_version,
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        item_after = validate_success(
            api.get_record_item(member["id"], item["id"], make_member_headers(member["id"]))
        )
        assert item_after["status"] == "VERIFIED", "the stale supersede made no state change"


class TestStatePriorityOverOcc:
    def test_state_transition_wrong_state_trumps_fiscal_occ_on_order_confirm(self, api):
        """PRD §2.5: "When several checks could reject the same request, the server
        evaluates them in a fixed priority order so the surfaced error is
        deterministic."
        PRD §2.5: "State-machine from-state checks — `ERR_INVALID_STATE` when the
        target entity is not in the state the transition requires (for example,
        confirming an order that is not `PENDING`, engraving one that is not
        `CONFIRMED`, resolving a ticket that is not `OPEN`, or resolving a dispute
        that is not `UNDER_REVIEW`)."

        Design: Difficulty/priority_pair_validation_conflict/state_transition_wrong_state_trumps_fiscal_occ_on_order_confirm
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="BR-M", product_name="Mid Band",
                              base_price_cents=5000, max_engrave_chars=40)
        member = enroll_member(full_name="Sue State", email="sue@x.com", dob="1995-11-11", api=api)
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="Sue band", engrave_mode="MANUAL")
        old_version = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )["version"]
        confirm_order(member["id"], order["id"], api=api)
        balance_after_confirm = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )["balance_cents"]

        # Re-confirm: already CONFIRMED (state failure) AND stale version (OCC failure).
        resp = api.confirm_order(
            member["id"], order["id"],
            {"expected_member_version": old_version},
            make_member_headers(member["id"]),
        )
        body = resp.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_STALE_VERSION.value, (
            "OCC is not surfaced; state check wins"
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        order_after = validate_success(api.get_order(order["id"], make_member_headers(member["id"])))
        assert order_after["status"] == "CONFIRMED"
        member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert member_after["balance_cents"] == balance_after_confirm, (
            "the rejected call changed nothing"
        )

    def test_second_confirm_with_fresh_version_still_invalid_state(self, api):
        """PRD §2.5: "State-machine from-state checks — `ERR_INVALID_STATE` when
        the target entity is not in the state the transition requires (for example,
        confirming an order that is not `PENDING`, engraving one that is not
        `CONFIRMED`, resolving a ticket that is not `OPEN`, or resolving a dispute
        that is not `UNDER_REVIEW`)."

        Design: Difficulty/priority_pair_validation_conflict/state_transition_wrong_state_trumps_fiscal_occ_on_order_confirm
        """
        set_clock(api=api)
        product = add_product(api=api, base_price_cents=5000, max_engrave_chars=40)
        member = enroll_member(api=api)
        order = place_and_confirm_order(member["id"], product["id"], api=api, engraving_text="Sue band")
        fresh_version = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )["version"]
        resp = api.confirm_order(
            member["id"], order["id"],
            {"expected_member_version": fresh_version},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestCompensatingLedger:
    def test_order_confirm_then_cancel_conserves_member_balance_and_wallet(self, api):
        """PRD §3.4: "Cancelling a `CONFIRMED` order reverses the confirm's ledger
        effect exactly: `balance_cents` is credited back by `price_cents` and the
        same amount lands in `wallet_credit_cents` as a refund, so balance and
        wallet return exactly to their pre-confirm values, with an `AuditEvent` of
        action `ORDER_CANCEL`."

        Design: Difficulty/compensating_invariant/order_confirm_then_cancel_conserves_member_balance_and_wallet
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="PD-X", product_name="Pendant X",
                              base_price_cents=5000, max_engrave_chars=40)
        member = enroll_member(full_name="Ivy Invariant", email="ivy@x.com", dob="1987-08-08", api=api)
        assert member["balance_cents"] == 4000
        assert member["wallet_credit_cents"] == 0

        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="Ivy pendant", engrave_mode="MANUAL")
        confirm_order(member["id"], order["id"], api=api)
        after_confirm = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert after_confirm["balance_cents"] == 9000, (
            f"order debited: 4000 + 5000, got {after_confirm['balance_cents']}"
        )

        cancelled = validate_success(api.cancel_order(member["id"], order["id"], make_member_headers(member["id"])))
        assert cancelled["status"] == "CANCELLED"
        after_cancel = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert after_cancel["balance_cents"] == 4000, (
            f"exactly the pre-confirm value — no drift, got {after_cancel['balance_cents']}"
        )
        assert after_cancel["wallet_credit_cents"] == 5000, "refund landed in wallet"

    def test_cancel_pending_order_has_no_financial_side_effects(self, api):
        """PRD §3.4: "Cancelling a `PENDING` order moves it to `CANCELLED` with no
        financial side effects beyond an `AuditEvent` of action `ORDER_CANCEL`."

        Design: Difficulty/compensating_invariant/order_confirm_then_cancel_conserves_member_balance_and_wallet
        """
        set_clock(api=api)
        product = add_product(api=api, base_price_cents=5000)
        member = enroll_member(api=api)
        order = place_order(member["id"], product["id"], api=api, engraving_text="Ivy pendant")
        cancelled = validate_success(api.cancel_order(member["id"], order["id"], make_member_headers(member["id"])))
        assert cancelled["status"] == "CANCELLED"
        after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert after["balance_cents"] == 4000, "no ledger effect for a PENDING cancel"
        assert after["wallet_credit_cents"] == 0


class TestEngravingSync:
    def test_engraving_sync_tail_truncation_severity_then_created_at(self, api):
        """PRD §3.5: "The engraving text is assembled from the member's items whose
        `status` is `VERIFIED`, ordered by severity rank — `CRITICAL` first, then
        `HIGH`, then `MEDIUM`, then `LOW` — with ties broken by `created_at`
        ascending, never by id. Each selected item contributes its `label`, and the
        lines are joined with the separator " | ". If the joined text exceeds the
        ordered product's `max_engrave_chars`, the lowest-severity lines are
        dropped from the tail of the ordering until the text fits; a member with
        zero verified items yields the empty string."

        Design: Difficulty/combinatorial_formula/engraving_sync_rounding_tail_truncation_severity_then_created_at
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="TAG-S", product_name="Small Tag",
                              base_price_cents=3000, max_engrave_chars=18)
        member = enroll_member(full_name="Sam Sync", email="sam@x.com", dob="1988-12-01", api=api)
        add_verified_item(member["id"], api=api, item_kind="ALLERGY", label="LowA",
                          detail="mild", severity="LOW", provider_document_ref="d1")
        add_verified_item(member["id"], api=api, item_kind="CONDITION", label="HighB",
                          detail="serious", severity="HIGH", provider_document_ref="d2")
        add_verified_item(member["id"], api=api, item_kind="MEDICATION", label="CritC",
                          detail="critical med", severity="CRITICAL", provider_document_ref="d3")

        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="client text ignored", engrave_mode="SYNC_WITH_RECORD")
        assert order["engraving_text"] == "CritC | HighB", (
            f"severity rank first regardless of creation order; LOW line tail-truncated "
            f"to fit 18 chars, got {order['engraving_text']!r}"
        )
        assert "LowA" not in order["engraving_text"], (
            "truncation drops the lowest-severity line, not the latest-created"
        )
        member_now = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert order["synced_revision"] == member_now["record_revision"]

    def test_sync_order_empty_when_no_verified_items(self, api):
        """PRD §3.5: "If the joined text exceeds the ordered product's
        `max_engrave_chars`, the lowest-severity lines are dropped from the tail of
        the ordering until the text fits; a member with zero verified items yields
        the empty string."

        Design: Difficulty/combinatorial_formula/engraving_sync_rounding_tail_truncation_severity_then_created_at
        """
        set_clock(api=api)
        product = add_product(api=api, base_price_cents=3000, max_engrave_chars=18)
        member = enroll_member(api=api)
        # One item still PENDING_VERIFICATION: nothing is VERIFIED yet.
        add_record_item(member["id"], api=api, item_kind="CONDITION", label="OnlyPending",
                        severity="CRITICAL", provider_document_ref="d1")
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="ignored", engrave_mode="SYNC_WITH_RECORD")
        assert order["engraving_text"] == "", "a member with zero verified items yields the empty string"

    def test_sync_order_resyncs_when_record_changes_while_pending(self, api, verifier_headers):
        """PRD §3.5: "The regeneration rule runs whenever a `MedicalRecordItem`
        transitions into `VERIFIED` or `SUPERSEDED` while any of the member's
        orders is `PENDING` with `engrave_mode` `SYNC_WITH_RECORD`, and it runs
        again at confirm time per §3.4."
        PRD §3.5: "The engraving text is assembled from the member's items whose
        `status` is `VERIFIED`, ordered by severity rank — `CRITICAL` first, then
        `HIGH`, then `MEDIUM`, then `LOW` — with ties broken by `created_at`
        ascending, never by id."

        Design: Corner/cross_cutting_layers/sync_order_resyncs_when_record_changes_while_pending
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="SY-1", product_name="Sync Band",
                              base_price_cents=3000, max_engrave_chars=40)
        member = enroll_member(full_name="Sybil Sync", email="sybil@x.com", dob="1990-01-01", api=api)
        add_verified_item(member["id"], api=api, item_kind="CONDITION", label="Aaa",
                          detail="a", severity="HIGH", provider_document_ref="d-a")
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="x", engrave_mode="SYNC_WITH_RECORD")
        assert order["engraving_text"] == "Aaa"
        rev0 = order["synced_revision"]

        item_b = add_record_item(member["id"], api=api, item_kind="ALLERGY", label="Bbb",
                                 detail="b", severity="CRITICAL", provider_document_ref="d-b")
        approve_item(member["id"], item_b["id"], api=api)

        order_after = validate_success(api.get_order(order["id"], make_member_headers(member["id"])))
        assert order_after["engraving_text"] == "Bbb | Aaa", (
            f"CRITICAL ranks ahead of HIGH, regenerated without any order mutation call; "
            f"got {order_after['engraving_text']!r}"
        )
        member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        assert order_after["synced_revision"] > rev0
        assert order_after["synced_revision"] == member_after["record_revision"]

    def test_verify_of_non_record_change_does_not_touch_manual_order(self, api, verifier_headers):
        """PRD §3.5: "The regeneration rule runs whenever a `MedicalRecordItem`
        transitions into `VERIFIED` or `SUPERSEDED` while any of the member's
        orders is `PENDING` with `engrave_mode` `SYNC_WITH_RECORD`, and it runs
        again at confirm time per §3.4."

        Design: Corner/cross_cutting_layers/sync_order_resyncs_when_record_changes_while_pending
        """
        set_clock(api=api)
        product = add_product(api=api, base_price_cents=3000, max_engrave_chars=40)
        member = enroll_member(api=api)
        manual = place_order(member["id"], product["id"], api=api,
                             engraving_text="Keep me", engrave_mode="MANUAL")
        item = add_record_item(member["id"], api=api, label="NewItem", severity="HIGH")
        approve_item(member["id"], item["id"], api=api)
        manual_after = validate_success(api.get_order(manual["id"], make_member_headers(member["id"])))
        assert manual_after["engraving_text"] == "Keep me", (
            "the regeneration rule applies only to SYNC_WITH_RECORD orders"
        )


class TestRecordParityInvariant:
    def test_record_verify_then_supersede_conserves_verified_count_and_revision_parity(self, api):
        """PRD §3.3: "The old item moves `VERIFIED` → `SUPERSEDED`; a brand-new
        item is created in `PENDING_VERIFICATION` carrying the replacement label
        and detail, with `item_kind` and `severity` copied from the superseded
        item and `condition_kind` reset to the `GENERAL` default — supersede
        payloads never carry a `condition_kind`; a fresh ticket opens for the
        replacement."
        PRD §3.5: "An order whose `synced_revision` trails the member's
        `record_revision` is considered stale; confirm refuses to proceed on a
        stale engraving by re-syncing first, so what ships always matches the
        record at confirm time."
        PRD §3.3: "On the member, `record_revision` increments, `version`
        increments by 1, and `has_cognitive_condition` is recomputed — it can flip
        false if the superseded item was the member's last verified `COGNITIVE`
        condition."

        Design: Difficulty/compensating_invariant/record_verify_then_supersede_conserves_verified_item_count_and_revision_parity
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="BR-Y", product_name="Band Y",
                              base_price_cents=4000, max_engrave_chars=40)
        member = enroll_member(full_name="Rey Record", email="rey@x.com", dob="1976-12-12", api=api)
        item_a = add_verified_item(member["id"], api=api, item_kind="CONDITION", label="OldLabel",
                                   detail="original", severity="HIGH", provider_document_ref="doc-old")
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="x", engrave_mode="SYNC_WITH_RECORD")
        assert order["engraving_text"] == "OldLabel"

        before = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        version_before = before["version"]

        replacement = validate_success(
            api.supersede_record_item(
                member["id"], item_a["id"],
                {
                    "replacement_label": "NewLabel",
                    "replacement_detail": "corrected",
                    "provider_document_ref": "doc-new",
                    "expected_member_version": version_before,
                },
                make_member_headers(member["id"]),
            )
        )
        assert replacement["status"] == "PENDING_VERIFICATION"
        old = validate_success(api.get_record_item(member["id"], item_a["id"], make_member_headers(member["id"])))
        assert old["status"] == "SUPERSEDED"

        # Verified count: 1 before -> 0 after (replacement pending); no instant with both VERIFIED.
        items_resp = api.list_record_items(member["id"], make_member_headers(member["id"]))
        from test_helpers import validate_paginated
        items, _ = validate_paginated(items_resp)
        verified = [i for i in items if i["status"] == "VERIFIED"]
        assert verified == [], "the superseded item left VERIFIED exactly when the replacement entered PENDING_VERIFICATION"

        after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        order_after = validate_success(api.get_order(order["id"], make_member_headers(member["id"])))
        assert order_after["engraving_text"] == "", "re-synced: no VERIFIED items"
        assert order_after["synced_revision"] == after["record_revision"], "parity restored"
        assert after["version"] == version_before + 1, (
            "Member.version incremented exactly once by the supersede (OCC discipline)"
        )

    def test_replacement_verify_restores_single_verified_item(self, api, verifier_headers):
        """PRD §3.3: "The old item moves `VERIFIED` → `SUPERSEDED`; a brand-new
        item is created in `PENDING_VERIFICATION` carrying the replacement label
        and detail, with `item_kind` and `severity` copied from the superseded
        item and `condition_kind` reset to the `GENERAL` default — supersede
        payloads never carry a `condition_kind`; a fresh ticket opens for the
        replacement."
        PRD §3.3: "Approval — decision `APPROVE` — requires the ticket to be `OPEN`
        and moves the underlying item from `PENDING_VERIFICATION` to `VERIFIED`
        while the ticket becomes `APPROVED`; the member's `has_cognitive_condition`
        is recomputed (and can flip true when the approved item is a `COGNITIVE`
        condition), `record_revision` increments, the member's `version` increments
        by 1, and an `AuditEvent` with action `RECORD_VERIFY` is appended."

        Design: Difficulty/compensating_invariant/record_verify_then_supersede_conserves_verified_item_count_and_revision_parity
        """
        from test_helpers import validate_paginated

        set_clock(api=api)
        member = enroll_member(api=api)
        item_a = add_verified_item(member["id"], api=api, label="OldLabel", severity="HIGH")
        fresh = validate_success(api.get_member(member["id"], make_member_headers(member["id"])))
        replacement = validate_success(
            api.supersede_record_item(
                member["id"], item_a["id"],
                {
                    "replacement_label": "NewLabel",
                    "replacement_detail": "corrected",
                    "provider_document_ref": "doc-new",
                    "expected_member_version": fresh["version"],
                },
                make_member_headers(member["id"]),
            )
        )
        approve_item(member["id"], replacement["id"], api=api)
        items, _ = validate_paginated(api.list_record_items(member["id"], make_member_headers(member["id"])))
        verified = [i for i in items if i["status"] == "VERIFIED"]
        assert len(verified) == 1 and verified[0]["id"] == replacement["id"], (
            "VERIFIED count conserved at 1 -> 0 -> 1 across verify/supersede/re-verify"
        )


class TestImmediateConsistency:
    def test_confirm_effects_visible_immediately_in_same_response(self, api):
        """PRD §3.4: "For a `SYNC_WITH_RECORD` order, confirm first re-syncs: the
        engraving text is regenerated from the member's verified items,
        `synced_revision` is set to the member's current `record_revision`, and
        only then is the order priced — a stale engraving is never confirmed."

        Design: Corner/consistency_model/confirm_effects_visible_immediately_in_same_response
        """
        set_clock(api=api)
        product = add_product(api=api, product_sku="IC-1", product_name="Ic Band",
                              base_price_cents=2000, max_engrave_chars=30)
        member = enroll_member(full_name="Iris Immediate", email="iris@x.com", dob="1989-09-09", api=api)
        add_verified_item(member["id"], api=api, item_kind="CONDITION", label="Epilepsy",
                          detail="seizures", severity="CRITICAL", provider_document_ref="d-ep")
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="x", engrave_mode="SYNC_WITH_RECORD")
        confirmed = confirm_order(member["id"], order["id"], api=api)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["price_cents"] == 2000, "STANDARD member: no discount"
        assert confirmed["engraving_text"] == "Epilepsy"

        reread = validate_success(api.get_order(order["id"], make_member_headers(member["id"])))
        assert reread["status"] == confirmed["status"]
        assert reread["price_cents"] == confirmed["price_cents"]
        assert reread["engraving_text"] == confirmed["engraving_text"], (
            "no eventual-consistency drift between the confirm response and the re-read"
        )

    def test_confirm_response_and_reread_agree_for_manual_order(self, api):
        """PRD §3.4: "Then the final price is computed, the member's
        `balance_cents` is debited by that `price_cents`, and — when the order is
        synchronized and the member is `LIFETIME` — the member's
        `first_lifetime_sync_order_consumed` becomes true."

        Design: Corner/consistency_model/confirm_effects_visible_immediately_in_same_response
        """
        set_clock(api=api)
        product = add_product(api=api, base_price_cents=2000)
        member = enroll_member(api=api)
        order = place_order(member["id"], product["id"], api=api,
                            engraving_text="Iris M", engrave_mode="MANUAL")
        confirmed = confirm_order(member["id"], order["id"], api=api)
        reread = validate_success(api.get_order(order["id"], make_member_headers(member["id"])))
        for field in ("status", "price_cents", "engraving_text", "engrave_mode"):
            assert reread[field] == confirmed[field], f"field {field} drifted between response and re-read"
