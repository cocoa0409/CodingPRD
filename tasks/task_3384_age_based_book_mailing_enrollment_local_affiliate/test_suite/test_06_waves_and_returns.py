"""Mailing waves: scheduling, manifest, reconcile, undeliverable returns
(PRD §3.7, §3.4, §2.9)."""
import pytest

from test_helpers import (
    AGE_BANDS,
    ApiErrorId,
    DEFAULT_CHILD_SPECS,
    EnrollmentStatus,
    ItemStatus,
    TEST_USERS,
    UnenrollReason,
    WaveStatus,
    api_client,
    assert_affiliate_invoice,
    assert_mailing_item,
    confirm_print_order,
    create_print_order,
    create_wave,
    create_wave_payload,
    get_affiliate,
    get_child,
    get_child_wave_item,
    get_wave_invoices,
    list_wave_items,
    manifest_wave,
    mark_item_returned,
    reconcile_wave,
    set_logical_clock,
    setup_approved_selection,
    setup_five_titles,
    setup_manifested_wave,
    setup_month_supply,
    setup_reconciled_wave,
    setup_wave_ready,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_MAIL_OPS = TEST_USERS["mail_ops_headers"]


class TestWaveScheduling:
    def test_wave_for_past_month_rejected(self, api):
        """PRD §3.7: "Scheduling a wave takes only a `mailing_month`, which
        must be unique across waves (else `ERR_WAVE_MONTH_DUPLICATE`) and must
        not be earlier than the current logical month (else
        `ERR_WAVE_MONTH_PAST`)."

        Design: Corner/validations/wave_for_past_month_rejected
        """
        set_logical_clock()
        resp = api.create_wave(create_wave_payload("2026-08"), _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_WAVE_MONTH_PAST)


class TestManifestGates:
    def test_manifest_with_insufficient_stock_rejected(self, api):
        """PRD §3.7: "for every band, the selected title's `stock_on_hand`
        must be at least that band's demand — the count of eligible children
        falling into the band — else `ERR_INVENTORY_SHORTFALL`."
        PRD §2.9: "it is recomputed on every print-order confirmation and
        every wave manifest, and the manifest's pre-checks guarantee it never
        goes negative."

        Design: Corner/validations/manifest_with_insufficient_stock_rejected
        """
        ctx = setup_wave_ready(
            quantities={"INFANT": 1}, child_specs=DEFAULT_CHILD_SPECS[:2]
        )
        resp = api.manifest_wave(ctx["wave"]["id"], _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_INVENTORY_SHORTFALL)
        assert list_wave_items(ctx["wave"]["id"]) == [], (
            "a failed manifest creates no items at all"
        )
        title = validate_success(api.get_title(ctx["titles"]["INFANT"]["id"], _ADMIN))
        assert title["stock_on_hand"] == 1, "no partial debit against the title"

    def test_manifest_blocked_until_all_band_selections_locked(self, api):
        """PRD §3.7: "all five age bands must have a `LOCKED` selection for
        the wave's month (else `ERR_MANIFEST_SELECTIONS_INCOMPLETE`)".

        Design: Difficulty/cross_entity_state_dependency/manifest_blocked_until_all_band_selections_locked
        """
        set_logical_clock()
        titles = setup_five_titles()
        selections = {}
        for band in AGE_BANDS:
            selections[band] = setup_approved_selection(
                "2026-10", band, title_id=titles[band]["id"]
            )["selection"]
        for band in ("INFANT", "TODDLER", "TWO", "THREE"):
            confirm_print_order(create_print_order(selections[band]["id"])["id"])
        four_order = create_print_order(selections["FOUR"]["id"])
        wave = create_wave("2026-10")
        resp = api.manifest_wave(wave["id"], _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_SELECTIONS_INCOMPLETE)
        assert list_wave_items(wave["id"]) == []
        assert four_order["status"] == "SUBMITTED", (
            "the FOUR-band order was never confirmed, so its selection is "
            "merely APPROVED, not LOCKED"
        )

    def test_manifest_succeeds_once_final_selection_locked(self, api):
        """PRD §3.7: "all five age bands must have a `LOCKED` selection for
        the wave's month (else `ERR_MANIFEST_SELECTIONS_INCOMPLETE`)".
        PRD §3.5: "confirmation locks the selection into the terminal `LOCKED`
        state".

        Design: Difficulty/cross_entity_state_dependency/manifest_blocked_until_all_band_selections_locked
        """
        set_logical_clock()
        titles = setup_five_titles()
        selections = {}
        for band in AGE_BANDS:
            selections[band] = setup_approved_selection(
                "2026-10", band, title_id=titles[band]["id"]
            )["selection"]
        for band in ("INFANT", "TODDLER", "TWO", "THREE"):
            confirm_print_order(create_print_order(selections[band]["id"])["id"])
        four_order = create_print_order(selections["FOUR"]["id"])
        wave = create_wave("2026-10")
        resp = api.manifest_wave(wave["id"], _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_SELECTIONS_INCOMPLETE)
        confirm_print_order(four_order["id"])
        locked = validate_success(api.get_selection(selections["FOUR"]["id"], _ADMIN))
        assert locked["status"] == "LOCKED"
        manifested = manifest_wave(wave["id"])
        assert manifested["status"] == WaveStatus.MANIFESTED.value
        assert manifested["manifested_item_count"] == 0, (
            "no children are registered, so the manifest creates zero items"
        )


class TestManifestEffects:
    def test_manifest_response_reflects_items_and_stock_debit(self, api):
        """PRD §3.7: "Manifesting debits each selected title's `stock_on_hand`
        by its band's manifested count, sets the wave's
        `manifested_item_count` to the total pieces created, and moves the
        wave to `MANIFESTED`."
        PRD §3.7: "For each eligible child the manifest creates one mailing
        item in `MAILED` status" and "An item's `billable` flag is true while
        the item is `MAILED` or `DELIVERED`".

        Design: Corner/endpoints/manifest_response_reflects_items_and_stock_debit
        """
        ctx = setup_wave_ready()
        wave = manifest_wave(ctx["wave"]["id"])
        assert wave["status"] == WaveStatus.MANIFESTED.value
        assert wave["manifested_item_count"] == 3
        infant = validate_success(api.get_title(ctx["titles"]["INFANT"]["id"], _ADMIN))
        assert infant["stock_on_hand"] == 6000 - 3, (
            "the INFANT title is debited by its band's manifested count"
        )
        toddler = validate_success(api.get_title(ctx["titles"]["TODDLER"]["id"], _ADMIN))
        assert toddler["stock_on_hand"] == 6000, "no TODDLER demand, no debit"
        items = list_wave_items(ctx["wave"]["id"])
        assert len(items) == 3
        for item in items:
            assert_mailing_item(item)
            assert item["status"] == ItemStatus.MAILED.value
            assert item["billable"] is True
            assert item["affiliate_id"] == ctx["affiliate"]["id"]

    def test_wave_manifest_twice_rejected(self, api):
        """PRD §3.7: "the wave must be `SCHEDULED` (else
        `ERR_INVALID_STATE`)".
        PRD §3.7: "the pair of child and month is unique across items and
        duplicates are prevented outright."

        Design: Corner/state_machines/wave_manifest_twice_rejected
        """
        ctx = setup_manifested_wave()
        resp = api.manifest_wave(ctx["wave"]["id"], _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        items = list_wave_items(ctx["wave"]["id"])
        assert len(items) == 3, "no duplicate items are created by the retry"

    def test_manifest_with_zero_eligible_children(self, api):
        """PRD §3.7: "A child is eligible for a wave month only when all five
        of the following hold: ..." — with no registered children the
        eligibility set is empty, and "Manifesting ... sets the wave's
        `manifested_item_count` to the total pieces created, and moves the
        wave to `MANIFESTED`."
        PRD §2.9: "A title's `stock_on_hand` is the sum of quantities over
        confirmed print orders whose selection names that title, minus the
        count of mailing items manifested from those selections".

        Design: Difficulty/boundary_precision_check/manifest_with_zero_eligible_children
        """
        ctx = setup_wave_ready(child_specs=[])
        wave = manifest_wave(ctx["wave"]["id"])
        assert wave["status"] == WaveStatus.MANIFESTED.value
        assert wave["manifested_item_count"] == 0
        infant = validate_success(api.get_title(ctx["titles"]["INFANT"]["id"], _ADMIN))
        assert infant["stock_on_hand"] == 6000, "zero demand debits nothing"

    def test_reconcile_with_zero_items_creates_no_invoices(self, api):
        """PRD §3.7: "Then the billing run of §3.8 creates one draft invoice
        per affiliate with at least one billable item — an affiliate whose
        items all came back undeliverable receives no invoice at all — and the
        wave settles into its terminal `RECONCILED` state."

        Design: Difficulty/boundary_precision_check/manifest_with_zero_eligible_children
        """
        ctx = setup_wave_ready(child_specs=[])
        manifest_wave(ctx["wave"]["id"])
        wave = reconcile_wave(ctx["wave"]["id"])
        assert wave["status"] == WaveStatus.RECONCILED.value
        rows, meta = validate_paginated(
            api.list_invoices(_ADMIN, params={"wave_id": ctx["wave"]["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestReconcileEffects:
    def test_reconcile_delivers_items_and_creates_draft_invoice(self, api):
        """PRD §3.7: "every item still `MAILED` transitions to `DELIVERED`"
        and "creates one draft invoice per affiliate with at least one
        billable item".
        PRD §3.7: "An item's `billable` flag is true while the item is
        `MAILED` or `DELIVERED` and false once it comes back
        `RETURNED_UNDELIVERABLE`."
        PRD §3.8: "Then `gross_cents` is the sum of per-item costs over the
        invoice's billable items."

        Design: Corner/endpoints/reconcile_delivers_items_and_creates_draft_invoice
        """
        ctx = setup_manifested_wave()
        child_returned, child_b, child_c = ctx["children"]
        item_returned = get_child_wave_item(ctx["wave"]["id"], child_returned["id"])
        mark_item_returned(item_returned["id"])
        wave = reconcile_wave(ctx["wave"]["id"])
        assert wave["status"] == WaveStatus.RECONCILED.value
        returned_after = validate_success(api.get_item(item_returned["id"], _ADMIN))
        assert returned_after["status"] == ItemStatus.RETURNED_UNDELIVERABLE.value
        assert returned_after["billable"] is False
        for sibling in (child_b, child_c):
            item = get_child_wave_item(ctx["wave"]["id"], sibling["id"])
            assert item["status"] == ItemStatus.DELIVERED.value
            assert item["billable"] is True
        invoices = get_wave_invoices(ctx["wave"]["id"])
        assert len(invoices) == 1, "exactly one affiliate has billable items"
        invoice = invoices[0]
        assert_affiliate_invoice(invoice)
        assert invoice["status"] == "DRAFT"
        assert invoice["item_count"] == 2, "the returned item is not billable"
        # 2 x (floor((6000*185 + 25000) / 6000) + 35) = 2 x 224
        assert invoice["gross_cents"] == 448
        assert invoice["affiliate_id"] == ctx["affiliate"]["id"]


class TestMarkReturned:
    def test_mark_returned_after_reconcile_rejected(self, api):
        """PRD §3.4: "`MailOps` records a return against a mailed item,
        allowed only while the item is `MAILED` and its wave is still
        `MANIFESTED` rather than `RECONCILED` (else `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/mark_returned_after_reconcile_rejected
        """
        ctx = setup_reconciled_wave()
        child = ctx["children"][0]
        item = get_child_wave_item(ctx["wave"]["id"], child["id"])
        assert item["status"] == ItemStatus.DELIVERED.value
        resp = api.mark_item_returned(item["id"], _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_item(item["id"], _ADMIN))
        assert after["status"] == ItemStatus.DELIVERED.value
        assert after["billable"] is True
        assert get_child(child["id"])["consecutive_returns"] == 0, (
            "the rejected return records nothing against the child"
        )


class TestAgeBandAssignment:
    def test_age_band_boundaries_11_vs_12_months(self, api):
        """PRD §2.4: "A child's age at any reference month is measured in
        whole months: take the reference month's year times twelve plus its
        month number, subtract the birth date's year times twelve plus its
        month number, and ignore the day of the month entirely."
        PRD §3.5: "The five bands partition the program's age range: `INFANT`
        for 0–11 months, `TODDLER` for 12–23, `TWO` for 24–35, `THREE` for
        36–47, and `FOUR` for 48–59."
        PRD §3.7: the manifest creates items carrying "the computed
        `age_band`".

        Design: Corner/calculations/age_band_boundaries_11_vs_12_months
        """
        ctx = setup_manifested_wave(
            clock="2026-08-01T00:00:00Z",
            mailing_month="2026-09",
            child_specs=[
                {
                    "full_name": "Kid Eleven",
                    "family_name": "Eleven",
                    "birth_date": "2025-10-15T00:00:00Z",
                    "mailing_address": {
                        "line1": "11 A St", "city": "Nashville", "region": "TN",
                        "postal_code": "37201", "country": "US",
                    },
                },
                {
                    "full_name": "Kid Twelve",
                    "family_name": "Twelve",
                    "birth_date": "2025-09-15T00:00:00Z",
                    "mailing_address": {
                        "line1": "12 B St", "city": "Nashville", "region": "TN",
                        "postal_code": "37203", "country": "US",
                    },
                },
            ],
        )
        wave = ctx["wave"]
        assert wave["manifested_item_count"] == 2
        kid11, kid12 = ctx["children"]
        item11 = get_child_wave_item(wave["id"], kid11["id"])
        item12 = get_child_wave_item(wave["id"], kid12["id"])
        # At 2026-09 the 2025-10 birth is 11 months old (INFANT); the 2025-09
        # birth is 12 months old (TODDLER, lower bound inclusive).
        assert item11["age_band"] == "INFANT"
        assert item11["selection_id"] == ctx["selections"]["INFANT"]["id"]
        assert item12["age_band"] == "TODDLER"
        assert item12["selection_id"] == ctx["selections"]["TODDLER"]["id"]


class TestReturnThresholdCascade:
    def _run_two_month_return_sequence(self, api):
        """Bootstrap through a second consecutive return on the first child.

        October wave manifested with three children; the first child's
        October item is returned (hold, counter 1); the clock advances to
        November; November supply is locked and manifested (the held child is
        still manifest-eligible); the first child's November item is
        returned (counter 2).
        """
        ctx = setup_manifested_wave()
        affiliate, child = ctx["affiliate"], ctx["children"][0]
        item_oct = get_child_wave_item(ctx["wave"]["id"], child["id"])
        mark_item_returned(item_oct["id"])
        set_logical_clock("2026-11-01T00:00:00Z")
        setup_month_supply("2026-11", titles=ctx["titles"])
        wave_nov = create_wave("2026-11")
        manifest_wave(wave_nov["id"])
        item_nov = get_child_wave_item(wave_nov["id"], child["id"])
        returned = mark_item_returned(item_nov["id"])
        return ctx, affiliate, child, returned

    def test_return_threshold_cascades_unenroll_and_recount(self, api):
        """PRD §3.4: "The item becomes `RETURNED_UNDELIVERABLE`, the wave's
        `returned_item_count` increases by one, and the child's
        `consecutive_returns` increases by one." and "When the counter reaches
        two — the program's auto-unenrollment threshold — the same return that
        raised it fires hold-then-unenroll atomically, netting out at
        `UNENROLLED` with `unenroll_reason` set to `UNDELIVERABLE` and the
        affiliate's `enrolled_count` recomputed".

        Design: Difficulty/transitive_cascade/return_threshold_cascades_unenroll_and_recount
        """
        ctx, affiliate, child, returned = self._run_two_month_return_sequence(api)
        assert returned["status"] == ItemStatus.RETURNED_UNDELIVERABLE.value
        after = get_child(child["id"])
        assert after["enrollment_status"] == EnrollmentStatus.UNENROLLED.value
        assert after["unenroll_reason"] == UnenrollReason.UNDELIVERABLE.value
        assert after["consecutive_returns"] == 2
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 2, (
            "the auto-unenrollment recomputes the count from 3 to 2"
        )

    def test_return_threshold_holds_at_one_and_spares_siblings(self, api):
        """PRD §3.4: "The first consecutive return slides the child from
        `ACTIVE` into `UNDELIVERABLE_HOLD` — and a held child **remains
        manifest-eligible**, so books keep mailing while the family sorts out
        its address."
        PRD §2.9: "An affiliate's `enrolled_count` is the count of its
        children whose `enrollment_status` is `ACTIVE` or
        `UNDELIVERABLE_HOLD`".

        Design: Difficulty/transitive_cascade/return_threshold_cascades_unenroll_and_recount
        """
        ctx = setup_manifested_wave()
        affiliate = ctx["affiliate"]
        child, sibling_b, sibling_c = ctx["children"]
        item_oct = get_child_wave_item(ctx["wave"]["id"], child["id"])
        mark_item_returned(item_oct["id"])
        held = get_child(child["id"])
        assert held["enrollment_status"] == EnrollmentStatus.UNDELIVERABLE_HOLD.value
        assert held["consecutive_returns"] == 1
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 3, (
            "a held child still counts"
        )
        set_logical_clock("2026-11-01T00:00:00Z")
        setup_month_supply("2026-11", titles=ctx["titles"])
        wave_nov = create_wave("2026-11")
        manifest_wave(wave_nov["id"])
        # The held child was mailed again in November — hold does not defer.
        item_nov = get_child_wave_item(wave_nov["id"], child["id"])
        mark_item_returned(item_nov["id"])
        for sibling in (sibling_b, sibling_c):
            assert get_child(sibling["id"])["enrollment_status"] == (
                EnrollmentStatus.ACTIVE.value
            ), "the cascade never fans out to siblings"
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 2
