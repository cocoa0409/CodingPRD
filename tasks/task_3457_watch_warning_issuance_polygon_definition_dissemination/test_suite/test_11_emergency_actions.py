"""Emergency actions: product-state gate and the evacuation re-entry buffer.

Ordering is gated on the linked product being ISSUED and covering the zone;
EVACUATION orders additionally respect a 60-minute closed-interval re-entry
buffer measured from the prior action's lifted_at (PRD §3.9).
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    cancel_product,
    create_action,
    create_watch_draft,
    get_action,
    lift_action,
    make_emergency_manager_headers,
    order_action,
    set_clock,
    setup_issued_warning,
    setup_office_with_zone,
    validate_error,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant regardless of fractional-digit rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# 120 minutes from the 08:30 issue instant: the inclusive SEVERE_THUNDERSTORM
# duration ceiling (PRD §3.5), so the warning issues and covers every action
# window used below.
_EXPIRES = "2026-09-01T10:30:00Z"


def _setup_issued_warning_over_high_zone(api):
    return setup_issued_warning(
        api,
        hazard_type="SEVERE_THUNDERSTORM",
        readings={"max_wind_mph": 60},
        issue_clock="2026-09-01T08:30:00Z",
        expires_at=_EXPIRES,
        zone_overrides={"population_tier": "HIGH"},
    )


class TestOrderRequiresIssuedProduct:
    def test_order_succeeds_while_product_issued(self, api):
        """PRD §3.9: "Ordering a recommendation — moving it from `RECOMMENDED`
        to `ORDERED` with `ordered_at` stamped — is gated three ways. The
        linked product must currently be `ISSUED`, else
        `ERR_INVALID_PRODUCT_STATE`."

        Design: Difficulty/cross_entity_state_dependency/emergency_order_requires_linked_product_issued
        """
        bundle = _setup_issued_warning_over_high_zone(api)
        action = create_action(
            api, bundle.zone["id"], bundle.product["id"], "EVACUATION",
            "2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z",
        )
        ordered = order_action(api, action["id"])
        assert ordered["status"] == "ORDERED"
        assert ordered["ordered_at"] is not None
        assert _instant(ordered["ordered_at"]) == _instant("2026-09-01T08:30:00Z")

    def test_order_rejected_after_product_cancelled(self, api):
        """PRD §3.9: "The linked product must currently be `ISSUED`, else
        `ERR_INVALID_PRODUCT_STATE`."
        PRD §3.7: "A forecaster may cancel an `ISSUED` product, moving it to
        the terminal `CANCELLED` status with `cancelled_at` stamped"

        Design: Difficulty/cross_entity_state_dependency/emergency_order_requires_linked_product_issued
        """
        bundle = _setup_issued_warning_over_high_zone(api)
        first = create_action(
            api, bundle.zone["id"], bundle.product["id"], "EVACUATION",
            "2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z",
        )
        assert order_action(api, first["id"])["status"] == "ORDERED", (
            "the same call succeeded minutes earlier while the product was ISSUED"
        )
        cancel_product(api, bundle.product["id"], bundle.headers)

        second = create_action(
            api, bundle.zone["id"], bundle.product["id"], "SHELTER_IN_PLACE",
            "2026-09-01T10:10:00Z", "2026-09-01T11:00:00Z",
        )
        resp = api.order_emergency_action(second["id"], make_emergency_manager_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_PRODUCT_STATE)
        assert get_action(api, second["id"])["status"] == "RECOMMENDED", (
            "the failed order mutates nothing"
        )


class TestEvacuationReentryBuffer:
    def test_evacuation_reentry_gap_45_minutes_rejected(self, api):
        """PRD §3.9: "an `EVACUATION` order must respect the re-entry buffer:
        against every other same-zone `EVACUATION` action in `ORDERED` or
        `LIFTED`, the new action's `effective_from` must be no earlier than
        sixty minutes after that prior action's end — where the prior end is
        its `lifted_at` when set, otherwise its `effective_until` — with a gap
        of exactly sixty minutes allowed. A violation is rejected with
        `ERR_EVACUATION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/evacuation_reentry_buffer_gap_45_rejected_gap_60_allowed
        """
        bundle = _setup_issued_warning_over_high_zone(api)
        ea1 = create_action(
            api, bundle.zone["id"], bundle.product["id"], "EVACUATION",
            "2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z",
        )
        set_clock(api, "2026-09-01T08:50:00Z")
        order_action(api, ea1["id"])
        set_clock(api, "2026-09-01T09:30:00Z")
        lifted = lift_action(api, ea1["id"])
        assert _instant(lifted["lifted_at"]) == _instant("2026-09-01T09:30:00Z")

        ea2 = create_action(
            api, bundle.zone["id"], bundle.product["id"], "EVACUATION",
            "2026-09-01T10:15:00Z", "2026-09-01T11:00:00Z",
        )
        resp = api.order_emergency_action(ea2["id"], make_emergency_manager_headers())
        validate_error(resp, ApiErrorId.ERR_EVACUATION_WINDOW_CONFLICT)
        assert get_action(api, ea2["id"])["status"] == "RECOMMENDED"

    def test_evacuation_reentry_gap_60_minutes_allowed(self, api):
        """PRD §3.9: "the new action's `effective_from` must be no earlier than
        sixty minutes after that prior action's end — where the prior end is
        its `lifted_at` when set, otherwise its `effective_until` — with a gap
        of exactly sixty minutes allowed."

        Design: Difficulty/resource_temporal_overlap/evacuation_reentry_buffer_gap_45_rejected_gap_60_allowed
        """
        bundle = _setup_issued_warning_over_high_zone(api)
        ea1 = create_action(
            api, bundle.zone["id"], bundle.product["id"], "EVACUATION",
            "2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z",
        )
        set_clock(api, "2026-09-01T08:50:00Z")
        order_action(api, ea1["id"])
        set_clock(api, "2026-09-01T09:30:00Z")
        lift_action(api, ea1["id"])

        ea3 = create_action(
            api, bundle.zone["id"], bundle.product["id"], "EVACUATION",
            "2026-09-01T10:30:00Z", "2026-09-01T11:30:00Z",
        )
        ordered = order_action(api, ea3["id"])
        assert ordered["status"] == "ORDERED", (
            "10:30 is exactly 60 minutes after lifted_at 09:30; the >= comparison "
            "admits the boundary, and the scheduled effective_until 10:00 is irrelevant"
        )


class TestLiftFromRecommended:
    def test_lift_from_recommended_withdraws_action(self, api):
        """PRD §3.9: "Lifting resolves an action: from `ORDERED` the lift moves
        it to `LIFTED` with `lifted_at` stamped, while the same lift applied to
        a still-`RECOMMENDED` action withdraws the recommendation into
        `WITHDRAWN`."
        PRD §3.9: "The action is born `RECOMMENDED` with `decided_by` recording
        the manager's `X-User-ID`"

        Design: Corner/state_machines/lift_from_recommended_withdraws_action
        """
        bundle = setup_office_with_zone(api)
        draft = create_watch_draft(
            api,
            bundle.office,
            bundle.headers,
            [bundle.zone["id"]],
            hazard_type="WINTER_STORM",
            effective_from="2026-09-02T00:00:00Z",
            expires_at="2026-09-02T12:00:00Z",
        )
        action = create_action(
            api, bundle.zone["id"], draft["id"], "SHELTER_OPEN",
            "2026-09-02T01:00:00Z", "2026-09-02T06:00:00Z", manager_id="em-7",
        )
        withdrawn = lift_action(api, action["id"], manager_id="em-7")
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["lifted_at"] is None, "lifted_at is stamped only on a LIFTED transition"
        assert withdrawn["decided_by"] == "em-7"
