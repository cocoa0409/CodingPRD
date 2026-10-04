"""Cohort formation, the seat ledger, placement offers and their gates
(PRD §3.4, §3.5)."""
from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    accept_offer,
    activate_agreement,
    api_client,
    assert_cohort,
    assert_offer,
    create_cohort,
    create_mentor,
    create_offer,
    create_offer_payload,
    create_selected_nominee,
    decide,
    decline_offer,
    draft_agreement,
    get_cohort,
    get_nominee,
    get_offer,
    get_scholar_for_nominee,
    make_nominee_headers,
    nominate,
    scholar_lifecycle,
    setup_city_with_partner,
    setup_cohort_foundation,
    setup_college,
    setup_locked_cohort,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OFFICER = TEST_USERS["selection_officer_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _forming_cohort_with_three_offers_one_accepted():
    """Cohort size 3 FORMING with seats_committed 1 and offers_outstanding 2
    (seats_remaining == 0). Returns (ctx, nominees, offers)."""
    ctx = setup_cohort_foundation(cohort_size=3)
    nominees = [
        create_selected_nominee(ctx["program"], ctx["partner"], f"Nom {i}")
        for i in (1, 2, 3)
    ]
    offers = [create_offer(n["id"], ctx["cohort"]["id"]) for n in nominees]
    accept_offer(offers[0])
    return ctx, nominees, offers


class TestInitialStates:
    def test_entities_boot_into_declared_initial_states(self, api):
        """PRD §3.3: "A freshly drafted agreement starts in `DRAFT` status."
        PRD §3.1: "The new nominee starts in `NOMINATED` status with
        `current_round` at 0 and all three round scores null".
        PRD §3.4: "The cohort starts in `FORMING` status with
        `seats_committed` at 0, `offers_outstanding` at 0,
        `invoice_total_cents` null, and `meetings_held_count` at 0."
        PRD §3.5: "A created offer starts in `OFFERED` status with its
        `expires_at` set fourteen days out".

        Design: Corner/state_machines/entities_boot_into_declared_initial_states
        """
        program, partner = setup_city_with_partner(quota=5)
        college = setup_college()
        agreement = draft_agreement(college, cohort_size=3)
        assert agreement["status"] == "DRAFT"
        activate_agreement(agreement["id"])
        mentor = create_mentor(college["id"])
        cohort = create_cohort(agreement, program, mentor)
        assert cohort["status"] == "FORMING"
        assert cohort["seats_committed"] == 0
        assert cohort["offers_outstanding"] == 0
        assert cohort["invoice_total_cents"] is None
        assert cohort["meetings_held_count"] == 0

        nominee = nominate(program, partner, "Nom One", by_nominator=True)
        assert nominee["status"] == "NOMINATED"
        assert nominee["current_round"] == 0
        assert nominee["round_1_score"] is None

        selected = create_selected_nominee(program, partner, "Nom Two")
        offer = create_offer(selected["id"], cohort["id"])
        assert_offer(offer)
        assert offer["status"] == "OFFERED"
        assert _parse(offer["expires_at"]) - _parse(offer["created_at"]) == timedelta(
            days=14
        ), "expires_at is exactly created_at + 14 days"


class TestTerminalLockdown:
    def test_accepted_offer_and_placed_nominee_are_terminal_locked(self, api):
        """PRD §3.5: "Acceptance requires the offer to still be `OFFERED`".
        PRD §3.2: "A `DROP` decision is available from `NOMINATED`, `ROUND_1`,
        `ROUND_2`, `ROUND_3`, `WAITLISTED`, and `SELECTED`, and moves the
        nominee to `DROPPED`."
        PRD §3.2: "The nominee's terminal states are `PLACED`, `DROPPED`, and
        `WITHDRAWN`."

        Design: Corner/state_machines/accepted_offer_and_placed_nominee_are_terminal_locked
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        nominee = create_selected_nominee(ctx["program"], ctx["partner"], "Nom One")
        offer = create_offer(nominee["id"], ctx["cohort"]["id"])
        accept_offer(offer)

        second = api.accept_offer(offer["id"], make_nominee_headers(nominee["id"]))
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

        drop = api.decide_nominee(nominee["id"], {"decision": "DROP"}, _OFFICER)
        validate_error(drop, ApiErrorId.ERR_INVALID_STATE)

        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 1, "the failed repeats touched nothing"
        assert get_nominee(nominee["id"])["status"] == "PLACED"


class TestNotFound:
    def test_cohort_get_unknown_id_returns_not_found(self, api):
        """PRD §2.7: "Path parameters resolve left to right: every identifier
        segment in the URL must name an existing resource, otherwise
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/cohort_get_unknown_id_returns_not_found
        """
        resp = api.get_cohort(MISSING_UUID, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_offer_create_with_unknown_nominee_returns_not_found(self, api):
        """PRD §2.7: "Identifiers referenced in the request body —
        `city_program_id`, `nominator_id`, `nominee_id`,
        `partner_college_id`, `agreement_id`, `mentor_id`, `cohort_id`,
        `scholar_id` ... — must each name an existing resource, otherwise
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/offer_create_with_unknown_nominee_returns_not_found
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        resp = api.create_offer(
            create_offer_payload(MISSING_UUID, ctx["cohort"]["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["offers_outstanding"] == 0


class TestOfferCreationConsistencyGates:
    def test_offer_create_city_mismatch_rejected(self, api):
        """PRD §3.5: "and the nominee's `city_program_id` must equal the
        cohort's `city_program_id`, otherwise `ERR_CITY_MISMATCH`."

        Design: Corner/validations/offer_create_city_mismatch_rejected
        """
        ctx = setup_cohort_foundation(cohort_size=3)  # cohort feeds from ATL
        boston_program, boston_partner = setup_city_with_partner(
            quota=5,
            program_overrides={"code": "BOS", "name": "Boston"},
        )
        boston_nominee = create_selected_nominee(
            boston_program, boston_partner, "Boston Nom"
        )
        resp = api.create_offer(
            create_offer_payload(boston_nominee["id"], ctx["cohort"]["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_CITY_MISMATCH)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["offers_outstanding"] == 0

    def test_second_live_offer_for_same_nominee_rejected(self, api):
        """PRD §3.5: "the nominee must not already hold an offer in `OFFERED`
        or `ACCEPTED` status anywhere, across all cohorts, otherwise
        `ERR_ACTIVE_OFFER_EXISTS`".

        Design: Corner/validations/second_live_offer_for_same_nominee_rejected
        """
        program, partner = setup_city_with_partner(quota=5)
        college = setup_college()
        agr1 = draft_agreement(college, cycle="2027", cohort_size=3)
        activate_agreement(agr1["id"])
        agr2 = draft_agreement(college, cycle="2028", cohort_size=3)
        activate_agreement(agr2["id"])
        mentor = create_mentor(college["id"])
        cohort1 = create_cohort(agr1, program, mentor)
        cohort2 = create_cohort(agr2, program, mentor)

        nominee = create_selected_nominee(program, partner, "Nom One")
        offer1 = create_offer(nominee["id"], cohort1["id"])

        resp = api.create_offer(
            create_offer_payload(nominee["id"], cohort2["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_OFFER_EXISTS)
        assert get_cohort(cohort2["id"])["offers_outstanding"] == 0
        assert get_offer(offer1["id"])["status"] == "OFFERED", (
            "the first offer is untouched by the rejected second attempt"
        )


class TestOfferCapacityGate:
    def test_offer_create_full_forming_cohort_rejected(self, api):
        """PRD §3.5: "Finally the capacity tier requires `seats_remaining`
        above zero; a cohort may still be `FORMING` with every seat spoken
        for, and that attempt is rejected with `ERR_COHORT_FULL`."

        Design: Corner/validations/offer_create_full_forming_cohort_rejected
        """
        ctx, _nominees, _offers = _forming_cohort_with_three_offers_one_accepted()
        fourth = create_selected_nominee(ctx["program"], ctx["partner"], "Nom Four")
        resp = api.create_offer(
            create_offer_payload(fourth["id"], ctx["cohort"]["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_COHORT_FULL)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "FORMING"
        assert cohort["seats_committed"] == 1
        assert cohort["offers_outstanding"] == 2, "the rejected offer moved nothing"


class TestFillProjectionVariants:
    def test_provisional_projection_weights_pending_offers(self, api):
        """PRD §3.4: "The `projected_fill_provisional` is the planning view:
        pending offers are weighted at 75% likely to convert, so it equals
        `seats_committed` plus the `offers_outstanding` count multiplied by
        7500 and divided by 10000, that product rounded half-up to a whole
        seat."

        Design: Difficulty/dual_variant_calc/cohort_fill_projection_provisional_vs_final
        """
        ctx, _nominees, _offers = _forming_cohort_with_three_offers_one_accepted()
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 1
        assert cohort["offers_outstanding"] == 2
        assert cohort["status"] == "FORMING"
        assert cohort["projected_fill_provisional"] == 3, (
            "1 committed + round_half_up(2 * 7500 / 10000) = 1 + 2"
        )

    def test_final_projection_counts_only_committed(self, api):
        """PRD §3.4: "The `projected_fill_final` is the committed view: pending
        offers count as zero, so it always equals `seats_committed`."

        Design: Difficulty/dual_variant_calc/cohort_fill_projection_provisional_vs_final
        """
        ctx, _nominees, _offers = _forming_cohort_with_three_offers_one_accepted()
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["projected_fill_final"] == 1
        assert cohort["projected_fill_provisional"] != cohort["projected_fill_final"], (
            "the two variants disagree (3 vs 1) on one identical ledger state"
        )
        assert_cohort(cohort)


class TestAutoLockBoundary:
    def _cohort_with_three_pending_offers(self):
        ctx = setup_cohort_foundation(cohort_size=3)
        nominees = [
            create_selected_nominee(ctx["program"], ctx["partner"], f"Nom {i}")
            for i in (1, 2, 3)
        ]
        offers = [create_offer(n["id"], ctx["cohort"]["id"]) for n in nominees]
        return ctx, nominees, offers

    def test_cohort_still_forming_below_cohort_size(self, api):
        """PRD §3.5: "And if committed seats have now reached the
        `cohort_size` — the boundary is inclusive, so equality locks — the
        cohort automatically moves from `FORMING` to `LOCKED`, after which no
        further offers can be created for it."

        Design: Difficulty/boundary_precision_check/cohort_locks_at_exactly_cohort_size
        """
        ctx, _nominees, offers = self._cohort_with_three_pending_offers()
        accept_offer(offers[0])
        accept_offer(offers[1])
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 2
        assert cohort["status"] == "FORMING", (
            "at seats_committed == 2 of 3 the cohort has not reached the boundary"
        )

    def test_cohort_locks_at_exactly_cohort_size(self, api):
        """PRD §3.5: "And if committed seats have now reached the
        `cohort_size` — the boundary is inclusive, so equality locks — the
        cohort automatically moves from `FORMING` to `LOCKED`, after which no
        further offers can be created for it."

        Design: Difficulty/boundary_precision_check/cohort_locks_at_exactly_cohort_size
        """
        ctx, _nominees, offers = self._cohort_with_three_pending_offers()
        for offer in offers:
            accept_offer(offer)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 3
        assert cohort["status"] == "LOCKED", (
            "at seats_committed == cohort_size == 3 the inclusive boundary locks"
        )
        assert cohort["offers_outstanding"] == 0


class TestStateErrorBeatsCapacityError:
    def _setup(self):
        ctx, _nominees, _offers = _forming_cohort_with_three_offers_one_accepted()
        nx = nominate(ctx["program"], ctx["partner"], "Nom X")
        decide(nx["id"], "DROP")  # DROPPED straight from NOMINATED
        return ctx, nx

    def test_state_error_wins_over_capacity_error(self, api):
        """PRD §2.7: "Every incoming request passes through twelve validation
        tiers in a strict priority order: the lower-numbered tier wins whenever
        one request violates several rules".
        PRD §3.5: "Within the state tier, the nominee's state is checked before
        the cohort's state: the nominee must be `SELECTED` — any other nominee
        status is rejected with `ERR_INVALID_STATE`".

        Design: Difficulty/priority_pair_validation_conflict/offer_create_state_error_beats_capacity_error
        """
        ctx, nx = self._setup()
        resp = api.create_offer(
            create_offer_payload(nx["id"], ctx["cohort"]["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            "the state tier (8) beats the capacity tier (11): 409, not 422"
        )

    def test_rejected_dual_violation_leaves_no_trace(self, api):
        """PRD §2.7: "the lower-numbered tier wins whenever one request
        violates several rules, so the error the caller receives is always the
        earliest applicable one."

        Design: Difficulty/priority_pair_validation_conflict/offer_create_state_error_beats_capacity_error
        """
        ctx, nx = self._setup()
        resp = api.create_offer(
            create_offer_payload(nx["id"], ctx["cohort"]["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 1
        assert cohort["offers_outstanding"] == 2, "no partial creation"
        offers, meta = validate_paginated(
            api.list_offers(_ADMIN, params={"nominee_id": nx["id"]})
        )
        assert meta["total_count"] == 0 and offers == []


class TestOfferBlockedWhenCohortLocked:
    def test_offer_create_on_locked_cohort_rejected(self, api):
        """PRD §3.5: "and the cohort must be `FORMING`, since an offer against
        a `LOCKED`, `MATRICULATED`, or `COMPLETED` cohort is rejected with
        `ERR_COHORT_NOT_FORMING`."

        Design: Difficulty/cross_entity_state_dependency/offer_create_blocked_when_cohort_locked
        """
        ctx = setup_locked_cohort()
        fourth = create_selected_nominee(ctx["program"], ctx["partner"], "Nom Four")
        resp = api.create_offer(
            create_offer_payload(fourth["id"], ctx["cohort"]["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_COHORT_NOT_FORMING)

    def test_locked_cohort_unchanged_by_rejected_offer(self, api):
        """PRD §3.5: "And if committed seats have now reached the
        `cohort_size` — the boundary is inclusive, so equality locks — the
        cohort automatically moves from `FORMING` to `LOCKED`, after which no
        further offers can be created for it."

        Design: Difficulty/cross_entity_state_dependency/offer_create_blocked_when_cohort_locked
        """
        ctx = setup_locked_cohort()
        fourth = create_selected_nominee(ctx["program"], ctx["partner"], "Nom Four")
        resp = api.create_offer(
            create_offer_payload(fourth["id"], ctx["cohort"]["id"]), _OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_COHORT_NOT_FORMING)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "LOCKED"
        assert cohort["seats_committed"] == 3
        offers, meta = validate_paginated(
            api.list_offers(_ADMIN, params={"nominee_id": fourth["id"]})
        )
        assert meta["total_count"] == 0, "no fourth offer exists"


class TestLockUnlockRevert:
    def test_withdrawal_reverts_locked_cohort_to_forming(self, api):
        """PRD §3.5: "if the cohort was `LOCKED` and committed seats have
        fallen below the `cohort_size` — the cohort reverts from `LOCKED` back
        to `FORMING` with the promotion sweep running immediately after the
        revert."

        Design: Difficulty/non_linear_state_machine/cohort_lock_unlock_revert
        """
        ctx = setup_locked_cohort()
        assert get_cohort(ctx["cohort"]["id"])["status"] == "LOCKED"
        scholar_lifecycle(ctx["scholars"][0]["id"], to_enrollment_status="WITHDRAWN")
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "FORMING", "the LOCKED -> FORMING revert fired"
        assert cohort["seats_committed"] == 2
        assert cohort["offers_outstanding"] == 0, (
            "the promotion sweep no-ops on an empty waitlist"
        )

    def test_withdrawal_revokes_the_accepted_offer(self, api):
        """PRD §3.7: "the scholar's accepted offer becomes `REVOKED`, the
        cohort's `seats_committed` falls by one, and the
        lock-revert-plus-promotion cascade of Section 3.5 runs when the cohort
        is still `LOCKED`".

        Design: Difficulty/non_linear_state_machine/cohort_lock_unlock_revert
        """
        ctx = setup_locked_cohort()
        offer, scholar = ctx["offers"][0], ctx["scholars"][0]
        assert get_offer(offer["id"])["status"] == "ACCEPTED"
        scholar_lifecycle(scholar["id"], to_enrollment_status="WITHDRAWN")
        assert get_offer(offer["id"])["status"] == "REVOKED"
        assert get_cohort(ctx["cohort"]["id"])["status"] == "FORMING"


class TestDeclineMovesSeatLedger:
    def test_offer_create_then_decline_moves_seat_ledger(self, api):
        """PRD §3.5: "Decline releases the seat: the offer moves from `OFFERED`
        to `DECLINED`, the cohort's `offers_outstanding` falls by one, and the
        waitlist promotion sweep runs for the cohort — though the sweep only
        fires while the cohort is `FORMING` with at least one seat remaining."

        Design: Corner/endpoints/offer_create_then_decline_moves_seat_ledger
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        nominee = create_selected_nominee(ctx["program"], ctx["partner"], "Nom One")
        offer = create_offer(nominee["id"], ctx["cohort"]["id"])

        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["offers_outstanding"] == 1
        assert cohort["seats_remaining"] == 2

        declined = decline_offer(offer)
        assert declined["status"] == "DECLINED"

        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["offers_outstanding"] == 0
        assert cohort["seats_remaining"] == 3
        assert cohort["seats_committed"] == 0, "decline never touches committed seats"
        assert get_nominee(nominee["id"])["status"] == "SELECTED", (
            "a decline does not drop the nominee"
        )
