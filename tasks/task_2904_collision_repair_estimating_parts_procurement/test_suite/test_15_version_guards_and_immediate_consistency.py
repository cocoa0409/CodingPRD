"""The version guard on the two guarded writes, and money that settles at once.

Two halves, both about what a caller is allowed to believe about the repair
order it last read.

The first half is the estimator's and the owner's stale read. Raising a
supplement and recording a consent decision are the only two writes that carry
the client's last observed order version, and each of them advances that version
when it succeeds -- so the caller's own accepted write is what turns its captured
figure stale. Neither guard is a once-only rule: a shop may raise several
supplements against one car and an owner may change their mind, and both do so
successfully here, once they re-read.

The second half is the absence of any settling delay. Freezing a supplier's
price and answering a supplement both rewrite the order's money picture inside
the same request, so the very next read of the order already agrees with the
response body that was just handed back -- no sweep, no clock move, no second
read to let the figures catch up.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import canonical_instant
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ESTIMATOR_HEADERS,
    PARTS_MANAGER_HEADERS,
    make_customer_headers,
    make_insurer_adjuster_headers,
)

# The worked estimate the requirements use for a single body operation: 4.5
# guide hours at an effective 6,000 cents an hour is 27,000 of labor, four
# percent of that is 1,080 of supplies, and with no parts the pre-tax total is
# 28,080. Against a 25,000 deductible the owner's share is exactly the
# deductible, which leaves the order comfortably below the consent threshold.
_DEDUCTIBLE_CENTS = 25000


def _instants_canonicalised(row: Dict[str, Any]) -> Dict[str, Any]:
    """A row whose instant fields are reduced to their canonical form.

    Two reads of the same untouched row must agree field for field, but the
    fractional part of a timestamp is a formatting detail rather than a value,
    so it is normalised before the two bodies are compared.
    """
    normalised: Dict[str, Any] = {}
    for key, value in row.items():
        if key.endswith("_at") and isinstance(value, str):
            normalised[key] = canonical_instant(value)
        else:
            normalised[key] = value
    return normalised


class TestTheVersionGuardOnTheTwoGuardedWrites:
    """A caller working from a superseded read is told to re-read."""

    def test_a_second_supplement_priced_off_a_superseded_read_is_refused(self, api):
        """A second supplement replaying the estimator's first read is refused 412.

        Uniqueness is not what guards this write: the order may legitimately
        carry several supplements, and the second one is accepted the moment the
        estimator re-reads the version its own first supplement advanced.

        PRD: "If it does not equal the order's current `version`, the request is rejected with `ERR_STALE_REPAIR_ORDER_VERSION` and HTTP 412."
        PRD: "A shop may legitimately raise several supplements against one order, so a second supplement is not blocked by the existence of the first; what is blocked is a supplement whose `requested_amount_cents` was computed from a superseded money picture."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Corner/cross_cutting_complexity_layers/a_second_supplement_priced_off_a_superseded_read_is_refused
        """
        world = fx.locked_world(
            api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
        )
        order_id = world["order_id"]

        # What the estimator saw before asking for anything.
        version_the_estimator_read = fx.order_version(api, order_id)

        first = fx.raise_supplement(
            api,
            order_id,
            expected_repair_order_version=version_the_estimator_read,
            reason_code="HIDDEN_DAMAGE",
            requested_amount_cents=50000,
        )
        assert first["status"] == "SUBMITTED", (
            f"a freshly raised supplement is SUBMITTED, got {first['status']}"
        )
        A.assert_count(first["round_count"], 1, "round_count")

        # Raising the first supplement is itself a write on the order, so the
        # estimator's captured figure is already superseded.
        after_first = fx.read_order(api, order_id)
        assert after_first["version"] > version_the_estimator_read, (
            "raising a supplement must advance the order's version past the "
            f"estimator's read of {version_the_estimator_read}, "
            f"got {after_first['version']}"
        )
        A.assert_posture(after_first, C.POSTURE_SUPPLEMENT_PENDING)

        refused = api.create_supplement(
            order_id,
            f.supplement_payload(
                version_the_estimator_read,
                reason_code="PROCEDURE_REQUIREMENT",
                requested_amount_cents=30000,
            ),
            ESTIMATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.STALE_REPAIR_ORDER_VERSION.value, 412)

        # The refusal wrote nothing at all: no second supplement, no version bump.
        rows, meta = fx.page(api.list_supplements(order_id, ESTIMATOR_HEADERS))
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [first["id"]])

        unchanged = fx.read_order(api, order_id)
        A.assert_version(unchanged, after_first["version"], "repair order")

        # Re-read, ask again with the same amounts: the guard was the version,
        # never the existence of the first supplement.
        fresh_version = unchanged["version"]
        second = get_success_data(
            api.create_supplement(
                order_id,
                f.supplement_payload(
                    fresh_version,
                    reason_code="PROCEDURE_REQUIREMENT",
                    requested_amount_cents=30000,
                ),
                ESTIMATOR_HEADERS,
            )
        )
        assert second["id"] != first["id"], "the retry must create a new supplement"
        assert second["status"] == "SUBMITTED", (
            f"the second supplement is SUBMITTED, got {second['status']}"
        )
        A.assert_count(second["round_count"], 1, "round_count")
        A.assert_cents(second["requested_amount_cents"], 30000, "requested_amount_cents")

        # Every accepted write on the order advances the version by exactly one,
        # so the version behind the second supplement is now stale in its turn.
        after_second = fx.read_order(api, order_id)
        A.assert_version(after_second, fresh_version + 1, "repair order")

        replayed = api.create_supplement(
            order_id,
            f.supplement_payload(
                fresh_version,
                reason_code="PARTS_PRICE_VARIANCE",
                requested_amount_cents=20000,
            ),
            ESTIMATOR_HEADERS,
        )
        validate_error(replayed, ApiErrorId.STALE_REPAIR_ORDER_VERSION.value, 412)

        rows, meta = fx.page(api.list_supplements(order_id, ESTIMATOR_HEADERS))
        A.assert_page(meta, total_count=2)
        A.assert_version(
            fx.read_order(api, order_id), after_second["version"], "repair order"
        )

    def test_a_consent_decision_carrying_a_superseded_version_is_refused(self, api):
        """An owner replaying the version behind their own consent is refused 412.

        The owner is free to change their mind -- a later decision supersedes an
        earlier one -- but only against the figure the order actually holds now.

        PRD: "Recording a consent decision requires the same field, `expected_repair_order_version`, again non-optional, and again rejected on mismatch with `ERR_STALE_REPAIR_ORDER_VERSION` and HTTP 412."
        PRD: "A vehicle owner may record consent repeatedly and a later decision legitimately supersedes an earlier one, so an existing consent does not block a new one."
        PRD: "A `CONSENT` decision sets `consent_state` to `CONSENTED`, freezes `consent_basis_cents` at the order's *current* `customer_pay_cents` — the figure the owner was actually shown — and sets `consent_alternate_parts` from the supplied `alternate_parts_ok`."
        PRD: "A `DECLINE` decision sets `consent_state` to `DECLINED`."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Corner/cross_cutting_complexity_layers/a_consent_decision_carrying_a_superseded_version_is_refused
        """
        world = fx.locked_world(
            api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
        )
        order_id = world["order_id"]
        customer_id = world["customer_id"]
        owner_headers = make_customer_headers(customer_id)

        # The figure the owner was actually shown, and the version behind it.
        as_shown = fx.read_order(api, order_id, owner_headers)
        A.assert_cents(as_shown["customer_pay_cents"], 25000, "customer_pay_cents")
        version_the_owner_saw = as_shown["version"]

        fx.record_consent(
            api,
            order_id,
            customer_id,
            "CONSENT",
            False,
            expected_repair_order_version=version_the_owner_saw,
        )

        after_consent = fx.read_order(api, order_id)
        assert after_consent["consent_state"] == "CONSENTED", (
            f"consent_state: expected CONSENTED, got {after_consent['consent_state']}"
        )
        A.assert_cents(after_consent["consent_basis_cents"], 25000, "consent_basis_cents")
        assert after_consent["consent_alternate_parts"] is False, (
            "consent_alternate_parts follows the supplied alternate_parts_ok, "
            f"got {after_consent['consent_alternate_parts']}"
        )
        assert after_consent["version"] > version_the_owner_saw, (
            "recording consent must advance the order's version past the owner's "
            f"read of {version_the_owner_saw}, got {after_consent['version']}"
        )

        refused = api.create_consent_decision(
            order_id,
            f.consent_decision_payload("DECLINE", False, version_the_owner_saw),
            owner_headers,
        )
        validate_error(refused, ApiErrorId.STALE_REPAIR_ORDER_VERSION.value, 412)

        # The refusal changed nothing: the standing consent and its basis survive
        # untouched, and the order's version did not move.
        untouched = fx.read_order(api, order_id)
        assert untouched["consent_state"] == "CONSENTED", (
            "a refused decision must leave consent_state at CONSENTED, "
            f"got {untouched['consent_state']}"
        )
        A.assert_cents(untouched["consent_basis_cents"], 25000, "consent_basis_cents")
        A.assert_version(untouched, after_consent["version"], "repair order")

        # Re-read and decline: the endpoint is not once-only, the version was the
        # only reason the replay failed.
        fresh_version = untouched["version"]
        fx.record_consent(
            api,
            order_id,
            customer_id,
            "DECLINE",
            False,
            expected_repair_order_version=fresh_version,
        )

        after_decline = fx.read_order(api, order_id)
        assert after_decline["consent_state"] == "DECLINED", (
            "a later decision supersedes the earlier one: expected DECLINED, "
            f"got {after_decline['consent_state']}"
        )
        A.assert_cents(after_decline["consent_basis_cents"], 25000, "consent_basis_cents")
        A.assert_version(after_decline, fresh_version + 1, "repair order")

        # The accepted decline advanced the version once more, so the version the
        # owner read before it is stale in its turn.
        replayed = api.create_consent_decision(
            order_id,
            f.consent_decision_payload("CONSENT", True, fresh_version),
            owner_headers,
        )
        validate_error(replayed, ApiErrorId.STALE_REPAIR_ORDER_VERSION.value, 412)

        final = fx.read_order(api, order_id)
        assert final["consent_state"] == "DECLINED", (
            "the refused third decision must not overwrite the standing decline, "
            f"got {final['consent_state']}"
        )
        A.assert_version(final, after_decline["version"], "repair order")


class TestTheMoneyPictureSettlesInsideTheSameRequest:
    """Nothing in this shop settles later: the next read already agrees."""

    def test_an_accepted_price_is_visible_in_the_totals_within_the_same_request(self, api):
        """Freezing a supplier's price rewrites the order's totals immediately.

        The accept-price response already carries the priced line, and the very
        next read of the order already carries the parts gross that line feeds --
        with no sweep, no clock move and no second read in between.

        PRD: "Accepting the price also pulls the line into the money picture: the eight-step totals rerun on the order because the line has now entered the parts-gross input set, and the posture derivation runs after them."
        PRD: "`extended_price_cents` is then `unit_extended_cents` multiplied by `qty` less `returned_qty`."
        PRD: "Both the parts line's `version` and the order's `version` increment."
        Design: Corner/consistency_model/an_accepted_price_is_visible_in_the_totals_within_the_same_request
        """
        world = fx.locked_world(
            api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
        )
        order_id = world["order_id"]
        labor_line_id = world["line_ids"][0]

        vendor = fx.create_vendor(
            api,
            name="Harbour Honda",
            vendor_type="OEM_DEALER",
            part_types_offered=["OEM"],
            discount_pct=0,
            max_qty_per_line=5,
        )
        part = fx.add_parts_line(
            api,
            labor_line_id,
            part_number="OEM-9071",
            part_description="Door shell",
            part_type="OEM",
            list_price_cents=30000,
            qty=2,
            vendor_id=vendor["id"],
        )
        fx.quote_part(api, part["id"], vendor["id"], 20000)

        before = fx.read_order(api, order_id)
        A.assert_cents(before["parts_gross_cents"], 0, "parts_gross_cents")

        # The write, and then nothing at all until the read.
        response = api.accept_parts_price(part["id"], None, PARTS_MANAGER_HEADERS)
        locked = validate_success(response, 200)
        A.assert_parts_line_state(
            locked,
            procurement_status="PRICE_LOCKED",
            authorization_status=C.AUTH_INSURER_ALLOWED,
        )
        A.assert_cents(locked["unit_price_cents"], 20000, "unit_price_cents")
        A.assert_extension(locked, 20000, 40000)

        after = fx.read_order(api, order_id)
        A.assert_totals(
            after,
            parts_gross_cents=40000,
            parts_discount_cents=0,
            parts_subtotal_cents=40000,
            pre_tax_total_cents=68080,
            insurer_authorized_cents=43080,
            customer_pay_cents=25000,
        )
        A.assert_customer_pay_split(after)

        # The line write and the roll-up were one atomic change on the order.
        A.assert_version(after, before["version"] + 1, "repair order")

        stored = fx.read_parts_line(api, part["id"])
        assert _instants_canonicalised(stored) == _instants_canonicalised(locked), (
            "the stored parts line must agree field for field with the "
            "accept-price response body"
        )

    def test_a_supplement_and_its_decision_are_readable_the_moment_they_land(self, api):
        """A raised supplement lists at once, and its partial answer lands at once.

        The partial approval is the interesting side, because the money figure
        comes from the adjuster's answer rather than from the estimator's
        request -- and it is already on the order when the response returns.

        PRD: "On success `approved_amount_cents` takes the adjuster's figure and `decided_at` is stamped."
        PRD: "The authorization ceiling is the order's `initial_authorized_cents` plus the sum of `approved_amount_cents` over the order's supplements whose `status` is `APPROVED` or `PARTIAL`."
        PRD: "It is created with `status` `SUBMITTED`, `round_count` 1, and `submitted_at` stamped from the logical clock — which simultaneously opens a cycle-time exclusion interval."
        Design: Corner/consistency_model/a_supplement_and_its_decision_are_readable_the_moment_they_land
        """
        world = fx.locked_world(
            api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
        )
        order_id = world["order_id"]
        insurer_id = world["insurer_id"]

        version_the_estimator_read = fx.order_version(api, order_id)
        supplement = fx.raise_supplement(
            api,
            order_id,
            expected_repair_order_version=version_the_estimator_read,
            reason_code="HIDDEN_DAMAGE",
            requested_amount_cents=50000,
        )

        # In the next breath, the request is already in the order's list.
        rows, meta = fx.page(api.list_supplements(order_id, ESTIMATOR_HEADERS))
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [supplement["id"]])
        assert rows[0]["status"] == "SUBMITTED", (
            f"the listed supplement is SUBMITTED, got {rows[0]['status']}"
        )
        A.assert_count(rows[0]["round_count"], 1, "round_count")

        before = fx.read_order(api, order_id)
        A.assert_posture(before, C.POSTURE_SUPPLEMENT_PENDING)

        response = api.decide_supplement(
            supplement["id"],
            f.supplement_decision_payload("PARTIAL", approved_amount_cents=30000),
            make_insurer_adjuster_headers(insurer_id),
        )
        decided = validate_success(response, 200)
        assert decided["status"] == "PARTIAL", (
            f"status: expected PARTIAL, got {decided['status']}"
        )
        A.assert_cents(decided["approved_amount_cents"], 30000, "approved_amount_cents")
        A.assert_cents(decided["requested_amount_cents"], 50000, "requested_amount_cents")
        A.assert_instant_format(decided["decided_at"], "decided_at")
        A.assert_instant(decided["decided_at"], C.CLOCK_DEFAULT, "decided_at")

        # The adjuster's 30,000 is the figure the order now works from; the
        # estimator's 50,000 never enters the money picture.
        after = fx.read_order(api, order_id)
        A.assert_totals(
            after,
            pre_tax_total_cents=28080,
            insurer_authorized_cents=3080,
            customer_pay_cents=25000,
        )
        A.assert_version(after, before["version"] + 1, "repair order")
        A.assert_posture(after, C.POSTURE_OPEN)

        stored = fx.read_supplement(api, supplement["id"])
        assert _instants_canonicalised(stored) == _instants_canonicalised(decided), (
            "the stored supplement must agree field for field with the decision "
            "response body"
        )
