"""Compensating transactions that must conserve one quantity exactly.

The first pair conserves MONEY: allowing and then withdrawing a reclaim has to
return every derived figure to the cent it started at, with the compensation
auditable in the ledger rather than silent. The second group conserves TIME: an
amended interchange instant shifts custody hours between adjoining segments
without creating or destroying any, even though the cents deliberately move.
"""

from datetime import datetime

from test_helpers import (
    ApiClient,
    assert_hours,
    assert_instant_equals,
    assert_money,
    bad_order_band_world,
    canonical_instant,
    computed_cycle,
    confirmed_correction,
    exposure,
    file_reclaim,
    ledger_entries,
    open_movement_of,
    read_cycle,
    read_movement,
    timestamp_amend_world,
    validate_success,
)
import test_helpers.factories as f

BAND_FROM = "2026-08-25T00:00:00Z"
BAND_TO = "2026-08-26T00:00:00Z"
WITHDRAW_REASON = "BN withdraws; the defect was pre-existing at receipt"


def _filed_claim_on_a_computed_cycle(api):
    """The 11464 segment inside a COMPUTED cycle, with a 24.00-hour claim filed."""
    world, movement = bad_order_band_world(api, report_at=BAND_FROM, release_at=BAND_TO)
    cycle, computed = computed_cycle(api, world)
    movement = read_movement(api, world, movement["id"])
    claim = file_reclaim(api, world, movement, "BAD_ORDER", BAND_FROM, BAND_TO)
    return world, movement, cycle, computed, claim


class TestReclaimWithdrawalRestoresTheMoneyExactly:
    """Allow then withdraw must land back on 11464 and 57, not one cent away."""

    def test_the_credit_is_granted_and_then_unwound_to_the_baseline_cent(self, api: ApiClient):
        """The cycle moves 11464/57 to 8621/43 and back to exactly 11464/57.

        PRD: "Withdrawing an allowed claim is a compensating transaction that must restore every derived figure **exactly**: `credit_cents` returns to 0, the segment's waterfall is re-run from the beginning so that `reclaim_credit_cents` and `net_hire_cents` return precisely to their previous values with no drift, the segment's `version` is incremented, and where a credit had already reached a cycle a `RECLAIM_REVERSAL` entry for exactly the amount removed is minted and the cycle recomputed, restoring `pre_fee_net_cents` and `clearinghouse_fee_cents` to their pre-allowance values."

        Design: Difficulty/compensating_invariant/reclaim_withdraw_restores_cycle_money_exactly_and_ledger_sums_to_pre_fee_net
        """
        world, movement, cycle, computed, claim = _filed_claim_on_a_computed_cycle(api)

        assert_money(movement["reclaim_credit_cents"], 0, "baseline reclaim_credit_cents")
        assert_money(movement["net_hire_cents"], 11464, "baseline net_hire_cents")
        assert computed["status"] == "COMPUTED"
        assert_money(computed["gross_hire_cents"], 11464, "baseline gross_hire_cents")
        assert_money(computed["reclaim_credit_cents"], 0, "baseline reclaim_credit_cents")
        assert_money(computed["pre_fee_net_cents"], 11464, "baseline pre_fee_net_cents")
        assert_money(computed["clearinghouse_fee_cents"], 57, "baseline fee")
        assert_money(computed["net_settlement_cents"], 11407, "baseline net_settlement_cents")
        assert computed["reopen_count"] == 0

        allowed = validate_success(api.allow_reclaim_claim(
            claim["id"], {"decision_note": "Bad order substantiated"},
            world.accountant(world.cx)))
        assert allowed["status"] == "ALLOWED"
        assert_hours(allowed["allowed_hours"], 24.00, "allowed_hours")
        assert_money(allowed["credit_cents"], 2843, "credit_cents")

        during = read_movement(api, world, movement["id"])
        assert_money(during["reclaim_credit_cents"], 2843, "reclaim_credit_cents")
        assert_money(during["net_hire_cents"], 8621, "net_hire_cents")
        mid_cycle = read_cycle(api, world, cycle["id"])
        assert mid_cycle["status"] == "COMPUTED"
        assert_money(mid_cycle["reclaim_credit_cents"], 2843, "reclaim_credit_cents")
        assert_money(mid_cycle["pre_fee_net_cents"], 8621, "pre_fee_net_cents")
        assert_money(mid_cycle["clearinghouse_fee_cents"], 43, "fee")
        assert_money(mid_cycle["net_settlement_cents"], 8578, "net_settlement_cents")

        withdrawn = validate_success(api.withdraw_reclaim_claim(
            claim["id"], {"withdraw_reason": WITHDRAW_REASON},
            world.accountant(world.bn)))
        assert withdrawn["status"] == "WITHDRAWN"
        assert_money(withdrawn["credit_cents"], 0, "credit_cents")
        assert withdrawn["withdraw_reason"] == WITHDRAW_REASON

        after = read_movement(api, world, movement["id"])
        assert_money(after["reclaim_credit_cents"], 0, "restored reclaim_credit_cents")
        assert_money(after["net_hire_cents"], 11464, "restored net_hire_cents")
        assert after["net_hire_cents"] not in (11463, 11465)

        restored = read_cycle(api, world, cycle["id"])
        assert restored["status"] == "COMPUTED"
        assert_money(restored["reclaim_credit_cents"], 0, "restored reclaim_credit_cents")
        assert_money(restored["pre_fee_net_cents"], 11464, "restored pre_fee_net_cents")
        assert_money(restored["clearinghouse_fee_cents"], 57, "restored fee")
        assert restored["clearinghouse_fee_cents"] not in (56, 58)
        assert_money(restored["net_settlement_cents"], 11407, "restored net_settlement_cents")
        assert restored["reopen_count"] == 0

    def test_the_ledger_keeps_both_legs_and_sums_back_to_the_pre_fee_net(self, api: ApiClient):
        """A -2843 credit and a +2843 reversal both survive, summing to 11464.

        PRD: "Ledger entries are never updated and never deleted, and every reversal is a new entry with the opposite sign; there is no endpoint that creates one, because rows are minted only by the settlement, reclaim, dispute and correction cascades described above."

        Design: Difficulty/compensating_invariant/reclaim_withdraw_restores_cycle_money_exactly_and_ledger_sums_to_pre_fee_net
        """
        world, movement, cycle, computed, claim = _filed_claim_on_a_computed_cycle(api)
        validate_success(api.allow_reclaim_claim(claim["id"], {},
                                                world.accountant(world.cx)))
        validate_success(api.withdraw_reclaim_claim(
            claim["id"], {"withdraw_reason": WITHDRAW_REASON},
            world.accountant(world.bn)))

        rows = ledger_entries(api, settlement_cycle_id=cycle["id"])
        by_type = {}
        for row in rows:
            by_type.setdefault(row["entry_type"], []).append(row["amount_cents"])

        assert by_type.get("HIRE_CHARGE") == [11464]
        assert by_type.get("RECLAIM_CREDIT") == [-2843]
        assert by_type.get("RECLAIM_REVERSAL") == [2843]
        assert "SETTLEMENT_PAYMENT" not in by_type

        credit = next(r for r in rows if r["entry_type"] == "RECLAIM_CREDIT")
        reversal = next(r for r in rows if r["entry_type"] == "RECLAIM_REVERSAL")
        assert credit["reclaim_claim_id"] == claim["id"]
        assert reversal["reclaim_claim_id"] == claim["id"]
        assert credit["id"] != reversal["id"]
        assert credit["amount_cents"] + reversal["amount_cents"] == 0

        conserved = sum(r["amount_cents"] for r in rows
                        if r["entry_type"] != "SETTLEMENT_PAYMENT")
        restored = read_cycle(api, world, cycle["id"])
        assert_money(conserved, 11464, "ledger sum")
        assert conserved == restored["pre_fee_net_cents"]
        assert restored["settled_at"] is None


FINAL_CLOCK = "2026-08-31T00:00:00Z"
ORIGINAL_HANDOFF = "2026-08-26T06:00:00Z"
AMENDED_HANDOFF = "2026-08-26T00:00:00Z"
CAR_REGISTERED_AT = "2026-08-20T00:00:00Z"
RETURN_HANDOFF = "2026-08-29T10:00:00Z"


def _hours(start: str, end: str) -> float:
    """Elapsed hours between two ISO-8601 instants, sub-second widths aside."""
    begin = datetime.fromisoformat(canonical_instant(start).replace("Z", "+00:00"))
    finish = datetime.fromisoformat(canonical_instant(end).replace("Z", "+00:00"))
    return (finish - begin).total_seconds() / 3600.0


def _amend_the_handoff(api, world, out_event):
    """BN amends the outbound handoff to 00:00, CX confirms, BN applies."""
    payload = f.timestamp_amend_payload(
        world.car, world.jct, world.cx, out_event["id"], AMENDED_HANDOFF,
        filing_note="The yard clock was six hours fast",
    )
    filed, confirmed = confirmed_correction(api, world, payload, world.bn, world.cx)
    applied = validate_success(
        api.apply_correction_request(filed["id"], {}, world.clerk(world.bn))
    )
    return filed, applied


class TestTimestampAmendConservesCustodyHours:
    """Six hours move from CX's segment to BN's; none are created or destroyed."""

    def test_the_target_event_is_superseded_by_a_minted_replacement(self, api: ApiClient):
        """The original 06:00 row survives as SUPERSEDED beside a CORRECTION_APPLY row.

        PRD: "A `MISSED_EVENT_INSERT` mints a new interchange event whose `source` is `CORRECTION_APPLY`; a `TIMESTAMP_AMEND` takes the target event `RECORDED → SUPERSEDED` and mints a replacement; an `ERRONEOUS_EVENT_VOID` takes the target event `RECORDED → VOID`."

        Design: Difficulty/compensating_invariant/timestamp_amend_conserves_total_custody_hours_across_three_segments
        """
        world, out_event, home, away = timestamp_amend_world(api)
        filed, applied = _amend_the_handoff(api, world, out_event)

        assert applied["status"] == "APPLIED"
        assert applied["resulting_event_id"] is not None
        assert applied["resulting_event_id"] != out_event["id"]

        replacement = validate_success(api.get_interchange_event(
            applied["resulting_event_id"], world.clerk(world.bn)))
        assert replacement["status"] == "RECORDED"
        assert replacement["source"] == "CORRECTION_APPLY"
        assert_instant_equals(replacement["interchange_at"], AMENDED_HANDOFF,
                              "interchange_at")

        superseded = validate_success(api.get_interchange_event(
            out_event["id"], world.clerk(world.bn)))
        assert superseded["status"] == "SUPERSEDED"
        assert_instant_equals(superseded["interchange_at"], ORIGINAL_HANDOFF,
                              "superseded interchange_at")

        recorded = validate_success(api.list_interchange_events(
            world.clerk(world.bn), params={"car_id": world.car, "status": "RECORDED"}))
        recorded = recorded if isinstance(recorded, list) else recorded["items"]
        assert len(recorded) == 2
        assert out_event["id"] not in [row["id"] for row in recorded]

    def test_the_boundary_moves_and_the_total_custody_hours_stay_at_264(self, api: ApiClient):
        """150 + 76 + 38 becomes 144 + 82 + 38: the same 264.00 hours of custody.

        PRD: "Layer two rewrites segment boundaries: `start_at` and `end_at` are re-derived from the surviving `RECORDED` events in `interchange_at` ascending order with ties broken by `created_at` ascending, a still-open segment left with zero length — one whose `start_at` equals the reconstructed `proposed_interchange_at` — transitions `OPEN → VOID`, a closed segment whose opening event has been erased transitions `CLOSED → VOID` provided it belongs to no `ARCHIVED` cycle, with any `HIRE_CHARGE` entry already minted for it reversed by a `CORRECTION_ADJUSTMENT` entry of the opposite amount, and voiding an `INTERCHANGE_REJECTION` clears the `bad_order_from` and `bad_order_to` stamps it had placed on the segment."

        Design: Difficulty/compensating_invariant/timestamp_amend_conserves_total_custody_hours_across_three_segments
        """
        world, out_event, home, away = timestamp_amend_world(api)
        still_open = open_movement_of(api, world.car, world.cx,
                                     world.accountant(world.cx))

        assert_hours(_hours(home["start_at"], home["end_at"]), 150.00, "M0 elapsed")
        assert_hours(_hours(away["start_at"], away["end_at"]), 76.00, "M1 elapsed")
        assert_hours(_hours(still_open["start_at"], FINAL_CLOCK), 38.00, "M2 elapsed")
        before = (_hours(home["start_at"], home["end_at"])
                  + _hours(away["start_at"], away["end_at"])
                  + _hours(still_open["start_at"], FINAL_CLOCK))
        assert_hours(before, 264.00, "total custody hours before")

        _amend_the_handoff(api, world, out_event)

        moved_home = read_movement(api, world, home["id"], road_id=world.cx)
        moved_away = read_movement(api, world, away["id"], road_id=world.bn)
        untouched = open_movement_of(api, world.car, world.cx,
                                    world.accountant(world.cx))

        assert_instant_equals(moved_home["start_at"], CAR_REGISTERED_AT, "M0 start_at")
        assert_instant_equals(moved_home["end_at"], AMENDED_HANDOFF, "M0 end_at")
        assert_instant_equals(moved_away["start_at"], AMENDED_HANDOFF, "M1 start_at")
        assert_instant_equals(moved_away["end_at"], RETURN_HANDOFF, "M1 end_at")
        assert untouched["id"] == still_open["id"]
        assert untouched["status"] == "OPEN"
        assert_instant_equals(untouched["start_at"], RETURN_HANDOFF, "M2 start_at")

        assert_hours(_hours(moved_home["start_at"], moved_home["end_at"]), 144.00,
                     "M0 elapsed")
        assert_hours(_hours(moved_away["start_at"], moved_away["end_at"]), 82.00,
                     "M1 elapsed")
        assert_hours(_hours(untouched["start_at"], FINAL_CLOCK), 38.00, "M2 elapsed")
        after = (_hours(moved_home["start_at"], moved_home["end_at"])
                 + _hours(moved_away["start_at"], moved_away["end_at"])
                 + _hours(untouched["start_at"], FINAL_CLOCK))
        assert_hours(after, 264.00, "total custody hours after")
        assert after == before

    def test_the_cents_do_not_conserve_because_days_ceiling_per_segment(self, api: ApiClient):
        """BN's segment rises from 72.00 hours and 7800 cents to 78.00 and 10900.

        PRD: "Layer three recomputes money on every affected segment — `chargeable_hours`, `time_component_cents`, `mileage_component_cents`, `gross_hire_cents` and `net_hire_cents` — and increments each `version`."

        Design: Difficulty/compensating_invariant/timestamp_amend_conserves_total_custody_hours_across_three_segments
        """
        world, out_event, home, away = timestamp_amend_world(api)
        assert_hours(away["chargeable_hours"], 72.00, "chargeable_hours")
        assert away["chargeable_days"] == 3
        assert_money(away["time_component_cents"], 7800, "time_component_cents")
        assert_money(away["gross_hire_cents"], 8775, "gross_hire_cents")
        assert away["recompute_count"] == 0

        _amend_the_handoff(api, world, out_event)

        repriced = read_movement(api, world, away["id"], road_id=world.bn)
        assert_hours(repriced["chargeable_hours"], 78.00, "chargeable_hours")
        assert repriced["chargeable_days"] == 4
        assert_money(repriced["time_component_cents"], 10900, "time_component_cents")
        assert_money(repriced["mileage_component_cents"], 975, "mileage_component_cents")
        assert_money(repriced["gross_hire_cents"], 11875, "gross_hire_cents")
        assert_money(repriced["net_hire_cents"], 11875, "net_hire_cents")
        assert repriced["recompute_count"] == 1
        assert repriced["version"] > away["version"]

        assert repriced["chargeable_hours"] != away["chargeable_hours"]
        assert repriced["time_component_cents"] - away["time_component_cents"] == 3100

        bn = exposure(api, world, world.bn)
        assert_money(bn["exposure_cents"], 11875, "exposure_cents")
        assert bn["open_movement_count"] == 0
