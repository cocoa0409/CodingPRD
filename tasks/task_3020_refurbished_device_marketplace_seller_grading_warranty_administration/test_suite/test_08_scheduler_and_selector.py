"""Scheduler-driven transitions and the deterministic reservation selector."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import next_imei


class TestReservationSelector:
    def test_the_latest_activated_reservation_services_the_listing(self, api):
        """PRD §3.5: "Candidates are ranked by `activated_on` descending, and ties on that instant are broken by `created_at` ascending. The first row under that ranking wins."
        PRD §3.5: "the row `id` may serve neither as the primary key nor as the tie-break, because it is a random identifier and would make an otherwise deterministic result non-deterministic"
        PRD §3.5: "When exactly one candidate exists the ranking is vacuous and that row is returned; when several exist, `activated_on` decides and `created_at` settles any tie."

        Design: Corner/cross_cutting_complexity_layers/selector_picks_deterministic_reservation_winner
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])

        # The approval-opened reservation carries the approval instant, so a
        # later clock is adopted before the two explicitly-opened rows so that
        # the later-activated one demonstrably outranks every other candidate.
        fx.set_clock("2026-12-05T00:00:00Z")
        older = fx.add_reservation(
            listing["id"], activated_on="2026-09-02T00:00:00Z", warranty_period_days=180
        )
        newer = fx.add_reservation(
            listing["id"], activated_on="2026-12-03T00:00:00Z", warranty_period_days=180
        )
        assert newer["activated_on"] > older["activated_on"]

        claim = fx.create_claim_under_review(seller["id"], listing["id"])
        assert claim["claim_state"] == "UNDER_REVIEW"

        reservations, _ = validate_paginated(
            api.get(f"/v1/listings/{listing['id']}/warranty-reservations", headers=fx.ADMIN)
        )
        assert {row["id"] for row in reservations} > {older["id"], newer["id"]}

        # PRD §3.5: "Candidates are ranked by `activated_on` descending, and
        # ties on that instant are broken by `created_at` ascending."  The
        # winner is the first row under that ranking, and it must agree with the
        # listing's `servicing_seller_id`.  The row `id` never participates.
        winner = fx.servicing_reservation(listing["id"])
        expected = max(
            reservations,
            key=lambda row: (row["activated_on"], tuple(-ord(c) for c in row["created_at"])),
        )
        assert winner["id"] == expected["id"]
        assert winner["activated_on"] == max(row["activated_on"] for row in reservations)
        assert winner["created_at"] == min(
            row["created_at"] for row in reservations
            if row["activated_on"] == winner["activated_on"]
        )
        assert winner["id"] == newer["id"], (
            "the latest-activated candidate must be the one that services the listing"
        )

    def test_remediation_of_a_replaced_reservation_returns_it_to_active(self, api):
        """PRD §3.5: "Remediation returns either state to `ACTIVE`: a `ClaimAdjudicator` remediating a `REPAIRING` reservation supplies `repair_estimate_cents` and may supply a `replacement_listing_id`, while remediating a `REPLACED` reservation supplies `replacement_listing_id`"
        PRD §3.5: "In both cases the listing's `active_reservation_days` resets to 0"

        Design: Corner/cross_cutting_complexity_layers/selector_picks_deterministic_reservation_winner
        """
        scenario = fx.setup_listed_device()
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        replacement = fx.create_listing(seller_id, imei=next_imei(), part_provenance="OEM_ONLY",
                                        provenance_doc_digest=None)
        fx.approve_listing(replacement["id"])

        fx.create_upheld_claim(
            seller_id, listing_id, resolution_type="REPLACE", obligation_cents=90000
        )
        reservations, _ = validate_paginated(
            api.get(f"/v1/listings/{listing_id}/warranty-reservations", headers=fx.ADMIN)
        )
        replaced = reservations[0]
        assert replaced["warranty_state"] == "REPLACED"

        remediated = validate_success(
            fx.remediate_reservation(replaced["id"], replacement_listing_id=replacement["id"])
        )
        assert remediated["warranty_state"] == "ACTIVE"

        listing = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert listing["active_reservation_days"] == 0, (
            "remediation resets the listing's active_reservation_days"
        )
        after = fx.get_exposure_floor(seller_id)
        assert after["cell_count"] == 0, "the released cell stops contributing to the repair term"


class TestSchedulerTransitions:
    def test_clock_advance_completes_an_expired_active_reservation(self, api):
        """PRD §3.9: "Moving the clock is not inert: the call evaluates every system transition whose guard depends on time, so warranty reservations whose `expired_on` has been passed while `ACTIVE` become `COMPLETED`"
        PRD §3.5: "`COMPLETED` is terminal, and a completed reservation contributes nothing to exposure."

        Design: Corner/cross_cutting_complexity_layers/reliance_on_clock_for_reservation_expiry
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        reservation = fx.add_reservation(
            listing["id"], activated_on="2026-12-01T00:00:00Z", warranty_period_days=20
        )
        assert reservation["warranty_state"] == "ACTIVE"

        fx.set_clock("2026-12-25T00:00:00Z")
        after = validate_success(
            api.get(f"/v1/warranty-reservations/{reservation['id']}", headers=fx.ADMIN)
        )
        assert after["warranty_state"] == "COMPLETED"

        exposure = fx.get_exposure_floor(seller["id"])
        assert exposure["cell_count"] == 0

    def test_remediated_repair_reservation_stops_contributing_before_expiry(self, api):
        """PRD §3.5: "a reservation that has returned to `ACTIVE` through remediation, or has reached `COMPLETED`, contributes zero, because its obligation has been discharged."
        PRD §3.5: "the remediated reservation stops contributing a cell, so the repair term falls by exactly that cell and the published floor falls by the same amount."

        Design: Corner/cross_cutting_complexity_layers/reliance_on_clock_for_reservation_expiry
        """
        fx.set_clock("2026-12-10T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-10T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        claim = fx.create_upheld_claim(seller["id"], listing["id"])
        validate_success(fx.route_claim_return(claim["id"]))

        before = fx.get_exposure_floor(seller["id"])
        assert before["cell_count"] == 1

        # The approval-opened reservation activates at the clock instant with
        # the default 180-day term, so the cell still carries its whole period.
        reservation = fx.servicing_reservation(listing["id"])
        assert reservation["warranty_state"] == "REPAIRING"
        assert before["published_exposure_floor_cents"] == 1800, (
            "180 days of 180 at 1800 cents per day is 1800 cents"
        )
        validate_success(fx.remediate_reservation(reservation["id"], repair_estimate_cents=18000))
        after = fx.get_exposure_floor(seller["id"])
        assert after["cell_count"] == 0
        assert after["published_exposure_floor_cents"] == 0
        assert before["published_exposure_floor_cents"] - after["published_exposure_floor_cents"] == 1800, (
            "the repair term falls by exactly the released cell"
        )


class TestCloseGuardOrdering:
    def test_section_age_guard_reports_the_too_young_code(self, api):
        """PRD §3.7: "A section may close only once it is at least 90 calendar days old, measured from `section_opened_on`"
        PRD §2.11: "priority 28 a too-young scoring section (`ERR_SECTION_TOO_YOUNG`, 409)"

        Design: Corner/state_machines/service_score_close_without_section_age
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        section = fx.open_section(seller["id"], "2026-11-15T00:00:00Z")

        version = fx.current_seller_version(seller["id"])
        response = fx.close_section(section["id"], version)
        validate_error(response, ApiErrorId.ERR_SECTION_TOO_YOUNG, 409)

    def test_a_section_blocked_by_an_approved_claim_reports_the_guard_error(self, api):
        """PRD §3.7: "the open-approved-claim guard fires *before* the section-age guard, so a section that is both too young and blocked by an open approved claim reports `ERR_SECTION_BLOCKED_BY_OPEN_CLAIM` (HTTP 409) rather than `ERR_SECTION_TOO_YOUNG` (409)."
        PRD §2.11: "priority 28 a too-young scoring section (`ERR_SECTION_TOO_YOUNG`, 409)"

        Design: Corner/state_machines/service_score_close_without_section_age
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        section = fx.open_section(seller["id"], "2026-11-15T00:00:00Z")
        fx.create_upheld_claim(seller["id"], listing["id"], resolution_type="REPAIR")

        version = fx.current_seller_version(seller["id"])
        response = fx.close_section(section["id"], version)
        validate_error(response, ApiErrorId.ERR_SECTION_BLOCKED_BY_OPEN_CLAIM, 409)

    def test_close_succeeds_once_the_section_is_old_enough(self, api):
        """PRD §3.7: "A section may close only once it is at least 90 calendar days old, measured from `section_opened_on`, and only when no claim routed to that seller is `APPROVED` and unresolved"
        PRD §3.7: "Closing a section is what fixes its numbers."

        Design: Corner/state_machines/service_score_close_without_section_age
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        section = fx.open_section(seller["id"], "2026-01-05T00:00:00Z")

        version = fx.current_seller_version(seller["id"])
        closed = validate_success(fx.close_section(section["id"], version))
        assert closed["section_state"] == "CLOSED"
        assert closed["section_closed_on"] is not None