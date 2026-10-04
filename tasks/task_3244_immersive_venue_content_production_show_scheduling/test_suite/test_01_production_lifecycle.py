"""Production lifecycle: creation defaults, activation exclusivity, gain recompute,
terminal lockdown, and deactivation precondition/cascade.

Every test starts against a freshly restarted server (empty database, logical
clock at 2026-09-01T00:00:00Z) and builds its own entities from scratch.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_booking_payload,
    create_production,
    create_show,
    get_success_data,
    setup_active_production_with_approved_asset,
    setup_confirmed_show,
    setup_show_in_rehearsal,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
CP = TEST_USERS["content_producer_headers"]
VS = TEST_USERS["venue_scheduler_headers"]
GU = TEST_USERS["guest_headers"]


class TestProductionCreate:

    def test_create_persists_draft_status_gain_zero_and_version_one(self, api):
        """PRD: "On creation the production lands in `DRAFT` status, with
        `gain_cents` initialized to 0 because a draft production contributes
        nothing to the venue-wide gain."
        PRD: "`version` (integer): a system-managed integer that increments by
        exactly 1 on every mutation to the resource, including mutations
        triggered by cascading side effects from a parent or sibling resource."

        Design: Corner/entities/production_create_persists_input_fields_and_defaults
        """
        data = validate_success(
            api.create_production(
                {
                    "title": "T1",
                    "production_type": "ORIGINAL",
                    "base_price_cents": 5000,
                    "is_haptic_capable": False,
                },
                PD,
            ),
            expected_status=201,
        )
        assert data["status"] == "DRAFT"
        assert data["gain_cents"] == 0
        assert data["version"] == 1

    def test_get_missing_production_returns_not_found(self, api):
        """PRD: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource;
        subsequent path segments and payload checks are not evaluated."

        Design: Corner/entities/get_missing_production_returns_not_found
        """
        resp = api.get_production(NON_EXISTENT_UUID, PD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProductionListing:

    def test_list_productions_paginates_with_envelope_fields(self, api):
        """PRD: "If `limit` is omitted, it defaults to 10; the minimum accepted
        value is 1 and the maximum is 100."
        PRD: "The `meta` object on every list response contains four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_productions_paginates_with_envelope_fields
        """
        create_production(title="L1", production_type="ORIGINAL", base_price_cents=5000)
        create_production(title="L2", production_type="RESIDENCY", base_price_cents=6000)
        resp = api.list_productions(PD, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"expected 1 item on the page, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestProductionActivation:

    def test_second_production_activation_rejected(self, api):
        """PRD: "Activation is exclusive: at most one production may be `ACTIVE`
        at any moment, so attempting to activate while another production is
        already `ACTIVE` is rejected with `ERR_PRODUCTION_ALREADY_ACTIVE`
        (HTTP 409)."

        Design: Corner/state_machines/second_production_activation_rejected
        """
        a = create_production(title="A", production_type="ORIGINAL", base_price_cents=5000)
        validate_success(api.activate_production(a["id"], PD))
        b = create_production(title="B", production_type="RESIDENCY", base_price_cents=6000)
        resp = api.activate_production(b["id"], PD)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_ALREADY_ACTIVE)
        after = validate_success(api.get_production(b["id"], PD))
        assert after["status"] == "DRAFT", "production B must remain DRAFT after rejected activation"

    def test_gain_cents_recomputed_on_activation(self, api):
        """PRD: "Whenever a production transitions into `ACTIVE`, the platform
        recomputes the venue-wide `gain_cents` as the sum of `base_price_cents`
        across all productions currently in `ACTIVE` status, including the
        production that just activated; productions in any other status are
        excluded from this sum."

        Design: Corner/entities/production_create_persists_input_fields_and_defaults
        """
        prod = create_production(title="G", production_type="ORIGINAL", base_price_cents=12000)
        data = validate_success(api.activate_production(prod["id"], PD))
        assert data["status"] == "ACTIVE"
        assert data["gain_cents"] == 12000, (
            "gain_cents must equal the sum of base_price_cents over ACTIVE productions"
        )


class TestProductionRetireTerminal:

    def test_activate_after_retire_rejected(self, api):
        """PRD: "Retirement (`DRAFT → RETIRED` or `DARK → RETIRED`) carries no
        preconditions and no cascades — a retired production simply leaves the
        slate."
        PRD §5: "| `ERR_INVALID_STATE` | 409 |"

        Design: Corner/state_machines/production_retire_is_terminal
        """
        prod = create_production(title="RT", production_type="ORIGINAL", base_price_cents=5000)
        validate_success(api.retire_production(prod["id"], PD))
        resp = api.activate_production(prod["id"], PD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_retire_after_retire_rejected(self, api):
        """PRD: "Retirement (`DRAFT → RETIRED` or `DARK → RETIRED`) carries no
        preconditions and no cascades — a retired production simply leaves the
        slate."
        PRD §5: "| `ERR_INVALID_STATE` | 409 |"

        Design: Corner/state_machines/production_retire_is_terminal
        """
        prod = create_production(title="RT2", production_type="ORIGINAL", base_price_cents=5000)
        validate_success(api.retire_production(prod["id"], PD))
        resp = api.retire_production(prod["id"], PD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestProductionDeactivation:

    def test_deactivate_rejected_with_confirmed_show(self, api):
        """PRD: "A production may only move `ACTIVE → DARK` when none of its
        shows is in `CONFIRMED` status."
        PRD §5: "| `ERR_INVALID_STATE` | 409 |"

        Design: Corner/state_machines/deactivate_rejected_with_confirmed_show
        """
        prod, asset, show = setup_confirmed_show(
            show_overrides={"start_time": "2026-09-03T19:00:00Z", "length_minutes": 90}
        )
        assert show["status"] == "CONFIRMED"
        resp = api.deactivate_production(prod["id"], PD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_production(prod["id"], PD))
        assert after["status"] == "ACTIVE", "production must remain ACTIVE after rejected deactivation"

    def test_deactivate_allowed_after_confirm_reverted_by_cancel(self, api):
        """PRD: "A production may only move `ACTIVE → DARK` when none of its
        shows is in `CONFIRMED` status."
        PRD: "Cancellation (`TENTATIVE`, `REHEARSAL`, or `CONFIRMED → CANCELLED`)
        compensates bookings: `HELD` bookings are cancelled with `refund_cents`
        equal to 0, and `CONFIRMED` bookings are cancelled with `refund_cents`
        equal to their `line_total_cents`."

        Design: Corner/state_machines/deactivate_rejected_with_confirmed_show
        """
        prod, asset, show = setup_confirmed_show(
            show_overrides={"start_time": "2026-09-03T19:00:00Z", "length_minutes": 90}
        )
        validate_success(api.cancel_show(show["id"], VS))
        data = validate_success(api.deactivate_production(prod["id"], PD))
        assert data["status"] == "DARK", (
            "with no CONFIRMED show remaining, deactivation must succeed"
        )


class TestProductionDeactivationCascade:

    def test_deactivate_cascades_show_then_booking(self, api):
        """PRD: "When the deactivation succeeds, every show of that production
        still in `TENTATIVE` or `REHEARSAL` is cancelled outright."
        PRD: "Each `CONFIRMED` booking on a cancelled show is cancelled with
        `refund_cents` set equal to that booking's `line_total_cents`, refunding
        the full amount."

        Design: Difficulty/transitive_cascade/production_deactivate_cascades_show_then_booking
        """
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        # Show S1: walked to terminal COMPLETED so deactivation stays legal.
        s1 = create_show(prod["id"], show_format="CORPORATE", start_time="2026-09-01T10:00:00Z", length_minutes=60)
        validate_success(api.schedule_rehearsal(s1["id"], VS))
        p_now = validate_success(api.get_production(prod["id"], PD))
        validate_success(api.confirm_show(s1["id"], {"expected_production_version": p_now["version"]}, VS))
        # Advancing the clock past the show's completion instant lets the §3.8
        # sweep complete the CONFIRMED show (settlement + impressions fire there).
        validate_success(api.set_clock("2026-09-01T12:00:00Z", PD))
        s1_completed = validate_success(api.get_show(s1["id"], VS))
        assert s1_completed["status"] == "COMPLETED", (
            "the clock sweep must complete a CONFIRMED show once its completion "
            "instant has been reached (PRD §3.8)"
        )
        # Show S2: REHEARSAL with one CONFIRMED booking.
        s2 = create_show(prod["id"], show_format="FILM", start_time="2026-09-10T19:00:00Z", length_minutes=90)
        validate_success(api.schedule_rehearsal(s2["id"], VS))
        bk = validate_success(api.create_booking(s2["id"], create_booking_payload(zone="MAIN", seats=2), GU), expected_status=201)
        validate_success(api.confirm_booking(bk["id"], GU))

        data = validate_success(api.deactivate_production(prod["id"], PD))
        assert data["status"] == "DARK"

        s2_after = validate_success(api.get_show(s2["id"], VS))
        assert s2_after["status"] == "CANCELLED", "show must be cancelled by the production cascade"
        bk_after = validate_success(api.get_booking(bk["id"], GU))
        assert bk_after["status"] == "CANCELLED", "booking must be cancelled via its show's cancellation"
        assert bk_after["refund_cents"] == pytest.approx(bk_after["line_total_cents"], abs=0.005), (
            "a CONFIRMED booking on a cascaded show refunds its full line total"
        )
        s1_after = validate_success(api.get_show(s1["id"], VS))
        assert s1_after["status"] == "COMPLETED", "terminal shows must be untouched by the cascade"

    def test_deactivate_cancels_held_booking_with_zero_refund(self, api):
        """PRD: "Each `HELD` booking on a cancelled show is itself cancelled
        with `refund_cents` set to 0 — the guest had not yet paid."
        PRD: "When the deactivation succeeds, every show of that production
        still in `TENTATIVE` or `REHEARSAL` is cancelled outright."

        Design: Difficulty/transitive_cascade/production_deactivate_cascades_show_then_booking
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        bk = validate_success(api.create_booking(show["id"], create_booking_payload(zone="MAIN", seats=1), GU), expected_status=201)
        assert bk["status"] == "HELD"

        validate_success(api.deactivate_production(prod["id"], PD))

        bk_after = validate_success(api.get_booking(bk["id"], GU))
        assert bk_after["status"] == "CANCELLED"
        assert bk_after["refund_cents"] == 0, "a HELD booking cancelled by the cascade refunds 0"
        show_after = validate_success(api.get_show(show["id"], VS))
        assert show_after["status"] == "CANCELLED"
