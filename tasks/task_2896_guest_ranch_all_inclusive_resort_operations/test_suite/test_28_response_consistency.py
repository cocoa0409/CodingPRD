"""Response consistency: a write's own response already carries every field the
write derived, and the rows it cascaded into are settled by the time it answers."""

from prd_bench_local_runner.testing import validate_success
from test_helpers import assertions
from test_helpers.factories import create_booking_payload, party_member, payment_payload
from test_helpers.fixtures import (
    build_cabin,
    build_guest,
    build_open_season,
    set_clock_to,
    sign_guest_waiver,
)
from test_helpers.test_users import RANCH_MANAGER, RESERVATIONS_AGENT


class TestSameResponseVisibility:
    """No effect described for an operation is deferred past its own response."""

    def test_every_derived_field_is_visible_in_the_same_response(self, client):
        """Booking, deposit and confirmation each answer with their own derived money and counters, and the season rollup is already settled.

        PRD: "A cascade is not an eventual, background reconciliation: every effect described in §3 for a given operation lands inside the same request, before the response is written, and the response reflects the fully settled state."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        cabin = build_cabin(client)
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        sign_guest_waiver(client, ann["id"])
        assert season["bed_nights_sold"] == 0
        season_version_before = season["version"]

        created = validate_success(
            client.create_booking(
                create_booking_payload(
                    season["id"], cabin["id"], ann["id"], [party_member(ann["id"])]
                ),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        assertions.assert_booking(created)
        assert created["booking_status"] == "HELD"
        assert created["payment_status"] == "AWAITING_DEPOSIT"
        assert created["nights"] == 7
        assert created["party_size"] == 1
        assert created["adult_count"] == 1
        assert created["child_count"] == 0
        assert created["provisional_package_total_cents"] == 479500
        assert created["deposit_required_cents"] == 143850
        assert created["deposit_paid_cents"] == 0
        assert created["payments_applied_cents"] == 0
        assertions.assert_folio_balance_consistent(created)

        paid = validate_success(
            client.post_payment(
                created["id"], payment_payload(143850, "DEPOSIT"), RESERVATIONS_AGENT
            )
        )
        assert paid["payment_status"] == "DEPOSIT_PAID"
        assert paid["deposit_paid_cents"] == 143850
        assert paid["payments_applied_cents"] == 0
        assert paid["booking_status"] == "HELD"

        confirmed = validate_success(
            client.confirm_booking(created["id"], RESERVATIONS_AGENT)
        )
        assert confirmed["booking_status"] == "CONFIRMED"
        assert confirmed["deposit_paid_cents"] == 143850
        assert confirmed["version"] == paid["version"] + 1

        # The season rollup the confirmation touched is already settled.
        season_after = validate_success(client.get_season(season["id"], RANCH_MANAGER))
        assertions.assert_season(season_after)
        assert season_after["bed_nights_sold"] == 7
        assert season_after["version"] == season_version_before + 1
