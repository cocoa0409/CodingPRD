"""Calculation corners: input-set filtering, formula order, caps and floors.

Each test here pins one arithmetic claim the PRD makes about a derived figure -
which gifts enter a score, which variant drives a ranking, where a cap or a
floor bites, and which denominator an aggregate divides by.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_TRANSFER_AMOUNT_EXCEEDS_BALANCE
from test_helpers.assertions import (
    assert_cents,
    assert_donor_points,
    assert_instant,
    assert_page_meta,
    assert_points,
    assert_ratio,
    assert_seat_inventory,
    find_ledger_entries,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    ACTION_COMPLETE,
    ATHLETICS_ANNUAL,
    BASIS_DEATH,
    BASIS_DIVORCE,
    DECISION_UPHOLD,
    DISPUTE_UPHELD,
    DONOR_DECEASED,
    ENDOWMENT,
    ENTRY_ALUMNI_STATUS,
    ENTRY_CONSECUTIVE_YEARS,
    ENTRY_CUMULATIVE_GIVING,
    ENTRY_DISPUTE_ADJUSTMENT,
    ENTRY_NET_TRANSFER,
    ENTRY_SEASON_TICKET_TENURE,
    EVENT_POSTSEASON,
    EVENT_SLOTS_PUBLISHED,
    GIFT_PLEDGED,
    GIFT_REFUNDED,
    JOINT_HOUSEHOLD,
    NON_ALUMNUS,
    OCCUPANCY_ASSIGNED,
    PAYMENT_PAID,
    POSTURE_NORMAL,
    RECALC_COMPUTED,
    RENOVATION_COMPLETED,
    RENOVATION_REPRICED,
    RENOVATION_RESEATING,
    RENOVATION_SURVEYED,
    SEAT_AVAILABLE,
    SEAT_DECOMMISSIONED,
    SECTION_OPEN,
    SECTION_UNDER_RENOVATION,
    SLOT_CONSUMED,
    SLOT_SCHEDULED,
    TRANSFER_REQUESTED,
    VARIANT_CERTIFIED,
    VARIANT_PROVISIONAL,
)
from test_helpers.fixtures import (
    add_gift,
    add_received_gift,
    change_status,
    certified_cycle,
    communicate_cycle,
    confirm_assignment,
    create_event,
    create_section_with_seats,
    file_dispute,
    invoice_and_pay,
    link_partners,
    ledger_entries,
    open_cycle,
    pick_seat_ok,
    publish_and_open,
    publish_slots,
    read_donor,
    read_event,
    read_seat,
    read_slot,
    register_donor,
    renew_season,
    reprice_renovation,
    reprice_section,
    request_transfer,
    request_transfer_ok,
    retention,
    run_cycle,
    sensitivity,
    set_clock,
    slot_for_donor,
    start_reseating,
    survey_section,
    renovation_action,
)
from test_helpers.test_users import (
    ANALYST,
    CERTIFIER,
    OFFICER,
    POLICY,
    POLICY_USER_ID,
)


def _latest_component(client, donor_id, entry_type, variant, expected_points):
    """The newest ledger generation's row for one component of one variant."""
    rows = find_ledger_entries(
        ledger_entries(client, donor_id=donor_id),
        entry_type=entry_type,
        variant=variant,
        donor_id=donor_id,
    )
    assert rows, "no {0}/{1} ledger row for donor {2}".format(
        entry_type, variant, donor_id
    )
    assert_points(
        rows[-1]["points"],
        expected_points,
        "{0}/{1} points".format(entry_type, variant),
    )
    return rows[-1]


def _refunded_gift_after_an_approved_transfer(client):
    """A donor whose base collapses to zero while 10.00 points stay transferred."""
    set_clock(client, f.instant(2026, 4, 1))
    source = register_donor(client, alumni_status=NON_ALUMNUS)
    recipient = register_donor(client, alumni_status=NON_ALUMNUS)
    gift = add_received_gift(client, source["id"], 1000000, f.instant(2026, 3, 1))

    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])

    change_status(client, source, DONOR_DECEASED, f.instant(2026, 3, 25))
    transfer = request_transfer_ok(
        client, source["id"], recipient["id"], BASIS_DEATH, 10.00
    )
    validate_success(client.approve_point_transfer(transfer["id"], headers=CERTIFIER))
    validate_success(
        client.settle_gift(
            gift["id"], f.settle_gift_payload(GIFT_REFUNDED), headers=OFFICER
        )
    )
    communicate_cycle(client, cycle["id"])
    return source, recipient, cycle


class TestCertifiedPointsIsFlooredAfterNettingTransfers:
    """A refund that undercuts an approved transfer must surface 0.00, not -10.00."""

    def test_the_pre_trigger_state_shows_the_unfloored_arithmetic(self, client):
        """Before the re-run the pair reads 5.00 and 10.00, so nothing is clamped yet.

        PRD 3.6: "On success it adds `points_amount` to the recipient's
        `transferred_points_in` and the same amount to the source's
        `transferred_points_out`, recomputes `certified_points` for both donors,
        and stamps `approved_by_user_id` with the certifier's `X-User-ID`."

        Design: Corner/calculations/certified_points_floor_clamps_a_net_negative_ledger_to_zero
        """
        source, recipient, _cycle = _refunded_gift_after_an_approved_transfer(client)

        assert_donor_points(
            read_donor(client, source["id"]),
            certified_base_points="15.00",
            certified_points="5.00",
            transferred_points_out="10.00",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            transferred_points_in="10.00",
            certified_points="10.00",
            label="recipient",
        )

    def test_the_re_run_floors_the_net_negative_total_at_zero(self, client):
        """Base 0.00 against 10.00 transferred out reads 0.00, never -10.00.

        PRD 3.3: "Whenever `certified_base_points`, `transferred_points_in`,
        `transferred_points_out` or `dispute_adjustment_points` changes,
        `certified_points` is recomputed as `certified_base_points` plus
        `transferred_points_in` minus `transferred_points_out` plus
        `dispute_adjustment_points`, rounded half up to 2 decimal places and
        floored at `0.00`."

        Design: Corner/calculations/certified_points_floor_clamps_a_net_negative_ledger_to_zero
        """
        source, recipient, cycle = _refunded_gift_after_an_approved_transfer(client)

        rerun = run_cycle(client, cycle["id"])
        assert rerun["status"] == RECALC_COMPUTED

        assert_donor_points(
            read_donor(client, source["id"]),
            certified_base_points="0.00",
            transferred_points_out="10.00",
            certified_points="0.00",
            provisional_points="0.00",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            certified_base_points="0.00",
            certified_points="10.00",
            label="recipient",
        )

    def test_the_floor_applies_to_the_total_and_not_to_each_component(self, client):
        """The explanatory NET_TRANSFER row still carries -10.00.

        PRD 3.3: "Sixth, the **net transfer component**: the donor's
        `transferred_points_in` minus their `transferred_points_out`."

        Design: Corner/calculations/certified_points_floor_clamps_a_net_negative_ledger_to_zero
        """
        source, _recipient, cycle = _refunded_gift_after_an_approved_transfer(client)
        run_cycle(client, cycle["id"])

        _latest_component(
            client, source["id"], ENTRY_NET_TRANSFER, VARIANT_CERTIFIED, "-10.00"
        )
        _latest_component(
            client, source["id"], ENTRY_CUMULATIVE_GIVING, VARIANT_CERTIFIED, "0.00"
        )


class TestEndowmentGiftsNeverEnterTheScoringInputSet:
    """The designation filter is variant-independent and unconditional."""

    def test_a_large_endowment_gift_does_not_move_the_score(self, client):
        """5,000,000 endowment cents alongside 1,000,000 annual cents still scores 15.00.

        PRD 3.2: "A gift enters a recalculation's input set only when it belongs
        to the donor being scored, its `gift_date` is at or before the
        recalculation's `cutoff_date`, and its `designation` is
        `ATHLETICS_ANNUAL` or `CAPITAL`."

        Design: Corner/calculations/endowment_gifts_are_excluded_from_the_scoring_input_set_in_both_variants
        """
        set_clock(client, f.instant(2026, 4, 1))
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        endowment = add_received_gift(
            client, donor["id"], 5000000, f.instant(2026, 3, 1), designation=ENDOWMENT
        )
        annual = add_received_gift(
            client,
            donor["id"],
            1000000,
            f.instant(2026, 3, 1),
            designation=ATHLETICS_ANNUAL,
        )
        assert endowment["counts_toward_points"] is False
        assert annual["counts_toward_points"] is True

        cycle = open_cycle(client, 2026)
        computed = run_cycle(client, cycle["id"])
        assert computed["status"] == RECALC_COMPUTED
        assert computed["donors_processed_count"] == 1

        assert_donor_points(
            read_donor(client, donor["id"]),
            certified_base_points="15.00",
            certified_points="15.00",
            provisional_points="15.00",
        )

    def test_the_designation_filter_holds_under_both_variants(self, client):
        """Both ledger generations report the same 10.00 giving component.

        PRD 3.2: "An `ENDOWMENT` gift never scores, no matter how large or how
        well settled."

        Design: Corner/calculations/endowment_gifts_are_excluded_from_the_scoring_input_set_in_both_variants
        """
        set_clock(client, f.instant(2026, 4, 1))
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        add_received_gift(
            client, donor["id"], 5000000, f.instant(2026, 3, 1), designation=ENDOWMENT
        )
        add_received_gift(
            client,
            donor["id"],
            1000000,
            f.instant(2026, 3, 1),
            designation=ATHLETICS_ANNUAL,
        )
        cycle = open_cycle(client, 2026)
        run_cycle(client, cycle["id"])

        _latest_component(
            client, donor["id"], ENTRY_CUMULATIVE_GIVING, VARIANT_CERTIFIED, "10.00"
        )
        _latest_component(
            client, donor["id"], ENTRY_CUMULATIVE_GIVING, VARIANT_PROVISIONAL, "10.00"
        )
        assert read_donor(client, donor["id"])["consecutive_giving_years"] == 1


class TestTheCutoffIsAGiftDateBoundaryNotACycleYearBoundary:
    """An in-cycle gift dated after the cutoff is still excluded."""

    def test_a_gift_dated_after_the_cutoff_does_not_score(self, client):
        """4,000,000 cents dated 2026-08-15 leaves the score at 15.00, not 67.50.

        PRD 3.2: "A gift enters a recalculation's input set only when it belongs
        to the donor being scored, its `gift_date` is at or before the
        recalculation's `cutoff_date`, and its `designation` is
        `ATHLETICS_ANNUAL` or `CAPITAL`."

        Design: Corner/calculations/gifts_dated_after_the_cutoff_are_excluded_from_the_scoring_input_set
        """
        set_clock(client, f.instant(2026, 9, 1))
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        early = add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
        late = add_received_gift(client, donor["id"], 4000000, f.instant(2026, 8, 15))

        cycle = open_cycle(
            client, 2026, dispute_window_end=f.instant(2026, 11, 30)
        )
        run_cycle(client, cycle["id"])

        assert_donor_points(
            read_donor(client, donor["id"]),
            certified_base_points="15.00",
            certified_points="15.00",
            provisional_points="15.00",
        )
        assert early["cycle_year"] == 2026
        assert late["cycle_year"] == 2026

    def test_the_run_refreshes_the_stored_total_from_the_certified_input_set(
        self, client
    ):
        """The run overwrites the running total with the input-set total alone.

        The gift dated 2026-08-15 is added to `cumulative_giving_cents` the
        moment it is recorded, but the run then rewrites the field from the
        CERTIFIED input set, which the cutoff excludes it from.

        PRD 3.2: "When a gift is recorded with `gift_status` already `RECEIVED`,
        its `amount_cents` is added to the donor's `cumulative_giving_cents`
        immediately and the donor's `version` advances by 1."

        PRD 3.3: "Every donor's `cumulative_giving_cents` and
        `consecutive_giving_years` are refreshed by the run to the values the
        CERTIFIED input set produced, so those two stored fields always describe
        the last completed run."

        Design: Corner/calculations/gifts_dated_after_the_cutoff_are_excluded_from_the_scoring_input_set
        """
        set_clock(client, f.instant(2026, 9, 1))
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
        add_received_gift(client, donor["id"], 4000000, f.instant(2026, 8, 15))

        before_the_run = read_donor(client, donor["id"])
        assert_cents(
            before_the_run["cumulative_giving_cents"],
            5000000,
            "cumulative_giving_cents before the run",
        )

        cycle = open_cycle(
            client, 2026, dispute_window_end=f.instant(2026, 11, 30)
        )
        run_cycle(client, cycle["id"])

        row = read_donor(client, donor["id"])
        assert_cents(row["cumulative_giving_cents"], 1000000, "cumulative_giving_cents")
        assert row["consecutive_giving_years"] == 1
        _latest_component(
            client, donor["id"], ENTRY_CUMULATIVE_GIVING, VARIANT_CERTIFIED, "10.00"
        )


def _two_streak_shapes(client):
    """One donor missing 2026 and one missing 2025, on identical lifetime giving."""
    set_clock(client, f.instant(2026, 7, 1))
    graced = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, graced["id"], 1000000, f.instant(2024, 5, 1))
    add_received_gift(client, graced["id"], 1000000, f.instant(2025, 5, 1))

    gapped = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, gapped["id"], 1000000, f.instant(2024, 5, 1))
    add_received_gift(client, gapped["id"], 1000000, f.instant(2026, 5, 1))

    cycle = open_cycle(client, 2026)
    return graced, gapped, cycle


class TestTheStreakGraceIsSpentOnlyOnTheCycleYearItself:
    """Same giving, different gap position, different streak."""

    def test_a_missing_cycle_year_spends_the_grace_and_reaches_two(self, client):
        """2024 plus 2025 with no 2026 gift is a streak of 2.

        PRD 3.3: "Start at the recalculation's `cycle_year`; if that year does not
        qualify, step back exactly one year — this one-year grace is applied at
        most once, and never again later in the walk."

        Design: Corner/calculations/streak_grace_year_is_applied_once_and_the_scan_stops_at_the_first_gap
        """
        graced, _gapped, cycle = _two_streak_shapes(client)
        computed = run_cycle(client, cycle["id"])
        assert computed["donors_processed_count"] == 2

        row = read_donor(client, graced["id"])
        assert row["consecutive_giving_years"] == 2
        assert_donor_points(row, certified_base_points="30.00", label="graced donor")
        _latest_component(
            client, graced["id"], ENTRY_CONSECUTIVE_YEARS, VARIANT_CERTIFIED, "10.00"
        )

    def test_an_interior_gap_stops_the_scan_at_one(self, client):
        """2024 plus 2026 is a streak of 1, because 2026 qualified and 2025 did not.

        PRD 3.3: "From the year now under examination, count upward by one for
        each consecutive qualifying year while stepping back one year at a time,
        and stop at the first year that does not qualify."

        Design: Corner/calculations/streak_grace_year_is_applied_once_and_the_scan_stops_at_the_first_gap
        """
        _graced, gapped, cycle = _two_streak_shapes(client)
        run_cycle(client, cycle["id"])

        row = read_donor(client, gapped["id"])
        assert row["consecutive_giving_years"] == 1
        assert_donor_points(row, certified_base_points="25.00", label="gapped donor")
        _latest_component(
            client, gapped["id"], ENTRY_CONSECUTIVE_YEARS, VARIANT_CERTIFIED, "5.00"
        )

    def test_the_two_donors_are_separated_by_the_streak_alone(self, client):
        """Identical lifetime giving isolates the streak rule from the giving bands.

        PRD 3.3: "Third, the **consecutive-year component**: the donor's
        consecutive-giving streak, or 20 if the streak exceeds 20, multiplied by
        5 points per year."

        Design: Corner/calculations/streak_grace_year_is_applied_once_and_the_scan_stops_at_the_first_gap
        """
        graced, gapped, cycle = _two_streak_shapes(client)
        run_cycle(client, cycle["id"])

        for donor in (graced, gapped):
            row = read_donor(client, donor["id"])
            assert_cents(
                row["cumulative_giving_cents"], 2000000, "cumulative_giving_cents"
            )
            _latest_component(
                client,
                donor["id"],
                ENTRY_CUMULATIVE_GIVING,
                VARIANT_CERTIFIED,
                "20.00",
            )


def _donor_with_four_renewals(client):
    """One donor whose renewal history repeats 2025, plus a single 2026 gift."""
    set_clock(client, f.instant(2026, 7, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    for cycle_year in (2024, 2025, 2025, 2026):
        renew_season(client, donor["id"], cycle_year)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = open_cycle(client, 2026)
    return donor, cycle


class TestSeasonTicketTenureCountsDistinctCycleYears:
    """A repeated renewal year must not buy a second season of tenure."""

    def test_a_repeated_renewal_year_does_not_increment_the_count(self, client):
        """Four calls across three distinct years leave the count at 3.

        PRD 3.1: "The renewal operation carries a single `cycle_year`, and each
        distinct `cycle_year` counts once: recording a year not already on file
        increments `season_ticket_seasons_purchased` by 1 and advances the
        donor's `version` by 1, and if `season_ticket_first_cycle_year` was
        previously unset it is filled in from this call."

        Design: Corner/calculations/repeated_season_ticket_renewal_for_one_cycle_year_counts_once_toward_tenure
        """
        donor, _cycle = _donor_with_four_renewals(client)

        row = read_donor(client, donor["id"])
        assert row["season_ticket_seasons_purchased"] == 3
        assert row["season_ticket_first_cycle_year"] == 2024

    def test_the_tenure_component_scores_three_seasons_not_four(self, client):
        """Three seasons at 3 points each is 9, so the score is 24.00.

        PRD 3.3: "Fourth, the **season-ticket tenure component**: the donor's
        `season_ticket_seasons_purchased`, or 30 if that count exceeds 30,
        multiplied by 3 points per season."

        Design: Corner/calculations/repeated_season_ticket_renewal_for_one_cycle_year_counts_once_toward_tenure
        """
        donor, cycle = _donor_with_four_renewals(client)
        run_cycle(client, cycle["id"])

        assert_donor_points(
            read_donor(client, donor["id"]),
            certified_base_points="24.00",
            certified_points="24.00",
        )
        _latest_component(
            client,
            donor["id"],
            ENTRY_SEASON_TICKET_TENURE,
            VARIANT_CERTIFIED,
            "9.00",
        )
        _latest_component(
            client, donor["id"], ENTRY_ALUMNI_STATUS, VARIANT_CERTIFIED, "0.00"
        )


def _two_donors_whose_variants_invert(client):
    """A pledge-heavy donor who leads on PROVISIONAL and trails on CERTIFIED."""
    set_clock(client, f.instant(2026, 4, 1))
    pledger = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, pledger["id"], 3000000, f.instant(2026, 3, 1))
    add_gift(
        client,
        pledger["id"],
        5000000,
        f.instant(2026, 4, 1),
        gift_status=GIFT_PLEDGED,
    )

    settled = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, settled["id"], 5000000, f.instant(2026, 3, 1))

    cycle = certified_cycle(client, 2026)
    event = create_event(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    return pledger, settled, event


class TestOnlyTheCertifiedVariantDrivesTheRanking:
    """Both figures are stored; only one of them may order the pool."""

    def test_the_two_variants_disagree_and_invert_the_pair(self, client):
        """112.50 against 67.50 on PROVISIONAL, 37.50 against 67.50 on CERTIFIED.

        PRD 3.4: "The **PROVISIONAL** variant admits gifts whose `gift_status` is
        `PLEDGED` as well as those whose `gift_status` is `RECEIVED`, so an
        unsettled pledge both raises the tiered giving component and is allowed
        to carry the consecutive-year streak; this is the generous figure quoted
        to the donor in the recalculation communication."

        Design: Corner/calculations/ranking_and_slotting_select_the_certified_variant_never_the_provisional_one
        """
        pledger, settled, _event = _two_donors_whose_variants_invert(client)

        assert_donor_points(
            read_donor(client, pledger["id"]),
            provisional_points="112.50",
            certified_base_points="37.50",
            certified_points="37.50",
            label="pledger",
        )
        assert_donor_points(
            read_donor(client, settled["id"]),
            provisional_points="67.50",
            certified_points="67.50",
            label="settled donor",
        )

    def test_rank_position_follows_the_certified_figure(self, client):
        """The settled 67.50 donor takes rank 1 over the 112.50 provisional figure.

        PRD 3.5: "The pool is ordered on four keys, applied in strict sequence:
        `certified_points` descending, then `cumulative_giving_cents`
        descending, then `consecutive_giving_years` descending, then
        `created_at` ascending."

        Design: Corner/calculations/ranking_and_slotting_select_the_certified_variant_never_the_provisional_one
        """
        pledger, settled, _event = _two_donors_whose_variants_invert(client)

        assert read_donor(client, settled["id"])["rank_position"] == 1
        assert read_donor(client, pledger["id"])["rank_position"] == 2

    def test_the_published_slot_order_follows_the_same_figure(self, client):
        """Slot 0 belongs to the settled donor and slot 1 to the pledger.

        PRD 3.4: "The **CERTIFIED** variant admits gifts whose `gift_status` is
        `RECEIVED` only, so a pledged gift is excluded from the giving bands
        *and* its `cycle_year` does not qualify for the streak; this is the
        figure that drives ranking, slotting and seat eligibility, and it is
        frozen at certification."

        Design: Corner/calculations/ranking_and_slotting_select_the_certified_variant_never_the_provisional_one
        """
        pledger, settled, event = _two_donors_whose_variants_invert(client)
        published = publish_slots(client, event["id"])
        assert published["published_slot_count"] == 2
        assert published["scheduled_slot_count"] == 2

        first = slot_for_donor(client, event["id"], settled["id"])
        assert first["slot_index"] == 0
        assert first["rank_at_publish"] == 1
        assert_instant(first["slot_start"], "2026-09-01T00:00:00.000Z", "slot_start")

        second = slot_for_donor(client, event["id"], pledger["id"])
        assert second["slot_index"] == 1
        assert second["rank_at_publish"] == 2
        assert_instant(second["slot_start"], "2026-09-03T00:00:00.000Z", "slot_start")


def _dispute_under_review_on_a_communicated_cycle(client):
    """A 15.00-point donor with an UNDER_REVIEW dispute claiming 10.00 points."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])
    communicate_cycle(client, cycle["id"])

    dispute = file_dispute(client, donor["id"], cycle["id"], 10.00)
    validate_success(client.review_dispute(dispute["id"], headers=ANALYST))
    return donor, cycle, dispute


class TestAnUpheldDisputeIsFoldedRatherThanAdded:
    """The adjustment reconciles once and the re-run must not double it."""

    def test_upholding_reconciles_the_donor_immediately(self, client):
        """7.50 granted lifts 15.00 to 22.50 without touching the base.

        PRD 3.4: "Upholding it, `UNDER_REVIEW → UPHELD`, sets
        `granted_points_delta` from the payload and `decided_by_user_id` to the
        decider's `X-User-ID`, stamps `decided_at` with the current logical clock
        instant, adds `granted_points_delta` to the donor's
        `dispute_adjustment_points`, recomputes the donor's `certified_points`,
        and advances both the dispute's `version` and the donor's `version` by
        1."

        Design: Corner/calculations/upholding_a_dispute_reconciles_certified_points_and_the_fold_is_not_repeated
        """
        donor, _cycle, dispute = _dispute_under_review_on_a_communicated_cycle(client)

        decided = validate_success(
            client.decide_dispute(
                dispute["id"],
                f.dispute_decision_payload(DECISION_UPHOLD, granted_points_delta=7.50),
                headers=POLICY,
            )
        )
        assert decided["status"] == DISPUTE_UPHELD
        assert_points(decided["granted_points_delta"], "7.50", "granted_points_delta")
        assert_points(decided["claimed_points_delta"], "10.00", "claimed_points_delta")
        assert decided["decided_by_user_id"] == POLICY_USER_ID

        assert_donor_points(
            read_donor(client, donor["id"]),
            certified_base_points="15.00",
            certified_points="22.50",
            dispute_adjustment_points="7.50",
        )

    def test_the_second_pass_folds_the_same_adjustment_once(self, client):
        """The re-run reports 22.50 again, not 30.00.

        PRD 3.4: "That second pass recomputes every donor's points, this time
        folding in the `dispute_adjustment_points` produced by disputes that were
        upheld, appends a fresh generation of ledger rows, resets
        `communication_sent_count` to 0 because the donors must be told again,
        and advances the recalculation's `version` by 1."

        Design: Corner/calculations/upholding_a_dispute_reconciles_certified_points_and_the_fold_is_not_repeated
        """
        donor, cycle, dispute = _dispute_under_review_on_a_communicated_cycle(client)
        client.decide_dispute(
            dispute["id"],
            f.dispute_decision_payload(DECISION_UPHOLD, granted_points_delta=7.50),
            headers=POLICY,
        )

        rerun = run_cycle(client, cycle["id"])
        assert rerun["status"] == RECALC_COMPUTED

        assert_donor_points(
            read_donor(client, donor["id"]),
            dispute_adjustment_points="7.50",
            certified_base_points="15.00",
            certified_points="22.50",
        )
        _latest_component(
            client,
            donor["id"],
            ENTRY_DISPUTE_ADJUSTMENT,
            VARIANT_CERTIFIED,
            "7.50",
        )


def _buffered_event(client):
    """A two-donor pool and a 60-minute event with a 30-minute buffer."""
    set_clock(client, f.instant(2026, 4, 1))
    leader = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, leader["id"], 2000000, f.instant(2026, 3, 1))
    follower = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, follower["id"], 1000000, f.instant(2026, 3, 1))

    cycle = certified_cycle(client, 2026)
    event = create_event(
        client,
        cycle["id"],
        f.instant(2026, 9, 1),
        f.instant(2026, 9, 1, 4),
        60,
        slot_buffer_minutes=30,
    )
    return leader, follower, event


class TestSlotBufferMinutesOpensAGapBetweenSlots:
    """The buffer advances the next slot_start without stretching slot_end."""

    def test_the_first_slot_is_exactly_slot_minutes_long(self, client):
        """Slot 0 runs 00:00 to 01:00 with the buffer contributing nothing yet.

        PRD 3.8: "Taking the ranked pool in order with a zero-based counter, each
        donor's `slot_index` is their position in that order; their `slot_start`
        is `window_start` advanced by the counter multiplied by the sum of
        `slot_minutes` and `slot_buffer_minutes`, expressed in minutes; and their
        `slot_end` is their `slot_start` advanced by `slot_minutes`."

        Design: Corner/calculations/slot_buffer_minutes_opens_a_gap_that_belongs_to_no_slot
        """
        leader, _follower, event = _buffered_event(client)
        published = publish_slots(client, event["id"])
        assert published["status"] == EVENT_SLOTS_PUBLISHED
        assert published["published_slot_count"] == 2
        assert published["scheduled_slot_count"] == 2
        assert published["slot_minutes"] == 60
        assert published["slot_buffer_minutes"] == 30

        first = slot_for_donor(client, event["id"], leader["id"])
        assert first["slot_index"] == 0
        assert first["rank_at_publish"] == 1
        assert_instant(first["slot_start"], "2026-09-01T00:00:00.000Z", "slot_start")
        assert_instant(first["slot_end"], "2026-09-01T01:00:00.000Z", "slot_end")

    def test_the_second_slot_starts_after_the_buffer_gap(self, client):
        """Slot 1 runs 01:30 to 02:30, so 01:00 to 01:30 belongs to nobody.

        PRD 3.8: "Each slot is **half-open**, including `slot_start` and
        excluding `slot_end`: a pick at exactly `slot_end` belongs to the next
        slot, never to this one, and is rejected against this slot with
        `ERR_OUTSIDE_SLOT_WINDOW`."

        Design: Corner/calculations/slot_buffer_minutes_opens_a_gap_that_belongs_to_no_slot
        """
        _leader, follower, event = _buffered_event(client)
        publish_slots(client, event["id"])

        second = slot_for_donor(client, event["id"], follower["id"])
        assert second["slot_index"] == 1
        assert second["rank_at_publish"] == 2
        assert_instant(second["slot_start"], "2026-09-01T01:30:00.000Z", "slot_start")
        assert_instant(second["slot_end"], "2026-09-01T02:30:00.000Z", "slot_end")
        assert second["slot_status"] == SLOT_SCHEDULED

    def test_the_buffered_schedule_still_fits_inside_the_window(self, client):
        """The last slot_end at 02:30 is before window_end, so nothing overflows.

        PRD 3.8: "If the last slot's `slot_end` would fall strictly after
        `window_end`, nothing at all is published and the request is rejected
        with `ERR_SLOT_WINDOW_OVERFLOW` — the schedule is all-or-nothing."

        Design: Corner/calculations/slot_buffer_minutes_opens_a_gap_that_belongs_to_no_slot
        """
        _leader, follower, event = _buffered_event(client)
        publish_slots(client, event["id"])

        second = slot_for_donor(client, event["id"], follower["id"])
        window_end = read_event(client, event["id"])["window_end"]
        assert_instant(window_end, "2026-09-01T04:00:00.000Z", "window_end")
        assert second["slot_end"] < window_end


def _linked_household_at_sixty_seven_fifty(client):
    """Two JOINT_HOUSEHOLD partners, the first scored to 67.50."""
    set_clock(client, f.instant(2026, 4, 1))
    first = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=JOINT_HOUSEHOLD
    )
    second = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=JOINT_HOUSEHOLD
    )
    link_partners(client, first, second)
    add_received_gift(client, first["id"], 5000000, f.instant(2026, 3, 1))
    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])
    return first, second


class TestTheDivorceCapIsAnInclusiveHalfOfTheBalance:
    """0.50 of 67.50 is exactly 33.75, and 33.76 is one hundredth too far."""

    def test_the_boundary_amount_is_accepted_under_the_divorce_cap(self, client):
        """33.75 lands in REQUESTED with the cap and ceiling both recorded.

        PRD 3.6: "`transfer_pct_cap` is a fraction, carried to 2 decimal places
        and always greater than zero and at most 1: a `DEATH` basis permits the
        entire balance, 1.00; an `ENTITY_DISSOLUTION` basis likewise permits
        1.00; a `DIVORCE` basis permits half, 0.50; and an
        `ENTITY_GIVING_REALIGNMENT` basis permits a quarter, 0.25."

        Design: Corner/calculations/divorce_basis_caps_a_transfer_at_exactly_half_the_certified_balance
        """
        first, second = _linked_household_at_sixty_seven_fifty(client)
        row = read_donor(client, first["id"])
        assert_donor_points(row, certified_points="67.50", label="source")
        assert row["entity_type"] == JOINT_HOUSEHOLD
        assert row["household_partner_donor_id"] == second["id"]

        created = validate_success(
            request_transfer(
                client, first["id"], second["id"], BASIS_DIVORCE, 33.75
            ),
            201,
        )
        assert_points(created["transfer_pct_cap"], "0.50", "transfer_pct_cap")
        assert_points(
            created["max_transferable_points"], "33.75", "max_transferable_points"
        )
        assert_points(created["points_amount"], "33.75", "points_amount")

    def test_the_satisfied_precondition_keeps_the_transfer_out_of_the_fork(self, client):
        """A mutually linked household pair needs no policy exception.

        PRD 3.6: "A `DIVORCE` basis expects the source donor's `entity_type` to
        be `JOINT_HOUSEHOLD` **and** their `household_partner_donor_id` to equal
        `recipient_donor_id` — the reciprocal household link established earlier
        is precisely what satisfies this."

        Design: Corner/calculations/divorce_basis_caps_a_transfer_at_exactly_half_the_certified_balance
        """
        first, second = _linked_household_at_sixty_seven_fifty(client)
        created = validate_success(
            request_transfer(
                client, first["id"], second["id"], BASIS_DIVORCE, 33.75
            ),
            201,
        )

        assert created["exception_required"] is False
        assert created["status"] == TRANSFER_REQUESTED

    def test_one_hundredth_over_the_ceiling_is_refused(self, client):
        """33.76 exceeds max_transferable_points and is rejected with 422.

        PRD 3.6: "If `points_amount` exceeds either `max_transferable_points` or
        the source donor's current `certified_points`, the request is rejected
        with `ERR_TRANSFER_AMOUNT_EXCEEDS_BALANCE`; the same pair of ceilings is
        re-checked at approval time, because the source's balance can move
        between the two calls."

        Design: Corner/calculations/divorce_basis_caps_a_transfer_at_exactly_half_the_certified_balance
        """
        first, second = _linked_household_at_sixty_seven_fifty(client)
        validate_success(
            request_transfer(
                client, first["id"], second["id"], BASIS_DIVORCE, 33.75
            ),
            201,
        )

        refused = request_transfer(
            client, first["id"], second["id"], BASIS_DIVORCE, 33.76
        )
        validate_error(refused, ERR_TRANSFER_AMOUNT_EXCEEDS_BALANCE, 422)

        _rows, meta = validate_list(
            client.list_donor_point_transfers(first["id"], headers=OFFICER)
        )
        assert_page_meta(meta, total_count=1)
        assert_donor_points(
            read_donor(client, first["id"]),
            transferred_points_out="0.00",
            label="source",
        )
        assert_donor_points(
            read_donor(client, second["id"]),
            transferred_points_in="0.00",
            label="recipient",
        )


def _four_donors_across_three_buckets(client):
    """A retained, a new, a lapsed-risk and an entirely giftless donor."""
    set_clock(client, f.instant(2026, 4, 1))
    retained = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, retained["id"], 1000000, f.instant(2025, 3, 1))
    add_received_gift(client, retained["id"], 1000000, f.instant(2026, 3, 1))

    newcomer = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, newcomer["id"], 1000000, f.instant(2026, 3, 1))

    at_risk = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, at_risk["id"], 1000000, f.instant(2023, 3, 1))

    giftless = register_donor(client, alumni_status=NON_ALUMNUS)

    cycle = certified_cycle(client, 2026)
    return (retained, newcomer, at_risk, giftless), cycle


class TestRetentionAnalysisUsesTwoDifferentDenominators:
    """The rate divides by the risk pool; the average divides by the whole pool."""

    def test_the_three_buckets_are_exclusive_and_not_exhaustive(self, client):
        """The giftless donor falls into none of the three counts.

        PRD 3.5: "It buckets the donors the cycle scored by the streak the cycle
        actually computed: `retained_donor_count` is the number of donors whose
        `consecutive_giving_years` is at least 2, `new_donor_count` is the number
        whose `consecutive_giving_years` equals exactly 1, and
        `lapsed_risk_donor_count` is the number whose `consecutive_giving_years`
        equals 0 while their `cumulative_giving_cents` is strictly greater than
        zero — a donor who has given historically but did not give in the streak
        window."

        Design: Corner/calculations/retention_analysis_buckets_four_donors_and_divides_by_the_risk_denominator
        """
        _donors, cycle = _four_donors_across_three_buckets(client)

        analysis = retention(client, cycle["id"])
        assert analysis["cycle_year"] == 2026
        assert analysis["donors_processed_count"] == 4
        assert analysis["retained_donor_count"] == 1
        assert analysis["new_donor_count"] == 1
        assert analysis["lapsed_risk_donor_count"] == 1

    def test_the_retention_rate_divides_by_retained_plus_lapsed_risk(self, client):
        """One retained over a risk pool of two is 0.5000, not 0.2500.

        PRD 3.5: "The `retention_rate` is `retained_donor_count` divided by the
        sum of `retained_donor_count` and `lapsed_risk_donor_count`, except that
        the divisor is 1 whenever that sum is zero, and the quotient is rounded
        half up to 4 decimal places."

        Design: Corner/calculations/retention_analysis_buckets_four_donors_and_divides_by_the_risk_denominator
        """
        _donors, cycle = _four_donors_across_three_buckets(client)

        analysis = retention(client, cycle["id"])
        assert_ratio(analysis["retention_rate"], "0.5000", "retention_rate")

    def test_the_average_divides_by_every_donor_the_cycle_scored(self, client):
        """55.00 over 4 donors is 13.75, a different denominator from the rate.

        PRD 3.5: "The `average_certified_points` is the sum of
        `certified_points` across all scored donors divided by
        `donors_processed_count`, except that the divisor is 1 whenever
        `donors_processed_count` is zero, rounded half up to 2 decimal places."

        Design: Corner/calculations/retention_analysis_buckets_four_donors_and_divides_by_the_risk_denominator
        """
        donors, cycle = _four_donors_across_three_buckets(client)
        retained, _newcomer, at_risk, giftless = donors

        analysis = retention(client, cycle["id"])
        assert_points(
            analysis["certified_points_sum"], "55.00", "certified_points_sum"
        )
        assert_points(
            analysis["average_certified_points"],
            "13.75",
            "average_certified_points",
        )
        assert_donor_points(
            read_donor(client, retained["id"]),
            certified_points="30.00",
            label="retained donor",
        )
        assert_donor_points(
            read_donor(client, at_risk["id"]),
            certified_points="10.00",
            label="lapsed-risk donor",
        )
        assert_donor_points(
            read_donor(client, giftless["id"]),
            certified_points="0.00",
            label="giftless donor",
        )


def _two_identically_scored_donors(client):
    """A genuine tie separated only by created_at, one logical second apart."""
    set_clock(client, f.instant(2026, 4, 1))
    earlier = register_donor(client, alumni_status=NON_ALUMNUS)
    set_clock(client, f.instant(2026, 4, 1, 0, 0, 1))
    later = register_donor(client, alumni_status=NON_ALUMNUS)

    add_received_gift(client, later["id"], 1000000, f.instant(2026, 3, 1))
    add_received_gift(client, earlier["id"], 1000000, f.instant(2026, 3, 1))

    cycle = certified_cycle(client, 2026)
    event = create_event(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    return earlier, later, event


class TestEqualScoresAreBrokenByCreatedAtAscending:
    """The fourth sort key is the only thing that can order a true tie."""

    def test_the_pair_really_ties_on_the_first_three_keys(self, client):
        """Identical points, identical giving and identical streaks.

        PRD 3.5: "The pool is ordered on four keys, applied in strict sequence:
        `certified_points` descending, then `cumulative_giving_cents`
        descending, then `consecutive_giving_years` descending, then
        `created_at` ascending."

        Design: Corner/calculations/equal_scoring_donors_are_ranked_by_created_at_ascending
        """
        earlier, later, _event = _two_identically_scored_donors(client)

        for donor, label in ((earlier, "earlier"), (later, "later")):
            assert_donor_points(
                read_donor(client, donor["id"]),
                certified_points="15.00",
                cumulative_giving_cents=1000000,
                consecutive_giving_years=1,
                label=label,
            )

    def test_the_earlier_created_at_takes_rank_one(self, client):
        """The tie-break is chronological, and the id is never an input.

        PRD 3.5: "Ties are impossible, because `created_at` is unique per donor
        and settles any remaining ambiguity — and a donor's `id` is **never** an
        input to the ordering."

        Design: Corner/calculations/equal_scoring_donors_are_ranked_by_created_at_ascending
        """
        earlier, later, event = _two_identically_scored_donors(client)

        assert read_donor(client, earlier["id"])["rank_position"] == 1
        assert read_donor(client, later["id"])["rank_position"] == 2

        published = publish_slots(client, event["id"])
        assert published["published_slot_count"] == 2
        first = slot_for_donor(client, event["id"], earlier["id"])
        assert first["slot_index"] == 0
        assert first["rank_at_publish"] == 1


def _empty_section_at_one_fifty(client):
    """Two available seats, no assignments at all: ratio zero by the carve-out."""
    set_clock(client, f.instant(2026, 8, 1))
    section, _seats = create_section_with_seats(
        client,
        [("N", 1), ("N", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=150000,
        required_points_per_seat=0.00,
    )
    return section


class TestAnEmptySectionIsNormalRatherThanPremium:
    """A zero ratio only reaches PREMIUM when no seat is left available."""

    def test_the_zero_divisor_carve_out_does_not_make_the_section_premium(
        self, client
    ):
        """Ratio 0.0000 with seats still available falls through to NORMAL.

        PRD 3.7: "`pricing_posture` is computed from the section's own counters:
        the underwater ratio is `underwater_seat_count` divided by
        `assigned_seat_count`, except that the divisor is 1 whenever
        `assigned_seat_count` is zero, rounded half up to 4 decimal places."

        PRD 3.7: "The branch order is pinned and `SOFT` is evaluated first and
        wins outright — when the ratio is at least 0.30 the posture is `SOFT`;
        otherwise, when the ratio is exactly zero **and** `seats_available` is
        zero, the posture is `PREMIUM`; otherwise it is `NORMAL`."

        Design: Corner/calculations/an_empty_section_lands_in_normal_posture_and_recommends_the_unchanged_requirement
        """
        section = _empty_section_at_one_fifty(client)

        assert_seat_inventory(
            section,
            seats_available=2,
            seats_committed_count=0,
            decommissioned_seat_count=0,
            assigned_seat_count=0,
            underwater_seat_count=0,
            seat_row_count=2,
            label="SEC-N",
        )
        assert section["pricing_posture"] == POSTURE_NORMAL

        report = sensitivity(client, section["id"])
        assert report["section_code"] == section["section_code"]
        assert report["assigned_seat_count"] == 0
        assert report["underwater_seat_count"] == 0
        assert_ratio(report["underwater_ratio"], "0.0000", "underwater_ratio")
        assert report["pricing_posture"] == POSTURE_NORMAL

    def test_normal_posture_recommends_the_requirement_unchanged(self, client):
        """No 0.90 and no 1.10 multiplier: the recommendation is the rate itself.

        PRD 3.7: "That recommendation is `per_seat_requirement_cents` multiplied
        by 0.90 and rounded half up to whole cents when the posture is `SOFT`,
        multiplied by 1.10 and rounded half up to whole cents when the posture is
        `PREMIUM`, and simply `per_seat_requirement_cents` unchanged when the
        posture is `NORMAL`."

        PRD 3.7: "It also opens `requirement_history` with a single entry pairing
        the opening `per_seat_requirement_cents` with a `cycle_year` taken from
        the UTC calendar year of the current logical clock instant."

        Design: Corner/calculations/an_empty_section_lands_in_normal_posture_and_recommends_the_unchanged_requirement
        """
        section = _empty_section_at_one_fifty(client)

        report = sensitivity(client, section["id"])
        assert_cents(
            report["per_seat_requirement_cents"], 150000, "per_seat_requirement_cents"
        )
        assert_cents(
            report["recommended_requirement_cents"],
            150000,
            "recommended_requirement_cents",
        )
        assert_points(
            report["required_points_per_seat"], "0.00", "required_points_per_seat"
        )
        history = report["requirement_history"]
        assert len(history) == 1, "expected one opening history entry, got {0!r}".format(
            history
        )
        assert history[0]["cycle_year"] == 2026
        assert_cents(
            history[0]["per_seat_requirement_cents"],
            150000,
            "requirement_history[0].per_seat_requirement_cents",
        )

    def test_a_reprice_moves_the_recommendation_and_appends_to_history(self, client):
        """The recommendation tracks the new rate; the old pairing survives.

        PRD 3.7: "A reprice supplies a new `per_seat_requirement_cents`, the
        `cycle_year` the new rate takes effect for, and
        `expected_section_version`; it replaces `per_seat_requirement_cents`,
        appends the new pairing to `requirement_history`, and advances the
        section's `version` by 1."

        Design: Corner/calculations/an_empty_section_lands_in_normal_posture_and_recommends_the_unchanged_requirement
        """
        section = _empty_section_at_one_fifty(client)

        repriced = reprice_section(client, section["id"], 200000, 2027)
        assert_cents(
            repriced["per_seat_requirement_cents"], 200000, "per_seat_requirement_cents"
        )
        assert repriced["version"] == section["version"] + 1

        report = sensitivity(client, section["id"])
        assert report["pricing_posture"] == POSTURE_NORMAL
        assert_ratio(report["underwater_ratio"], "0.0000", "underwater_ratio")
        assert_cents(
            report["recommended_requirement_cents"],
            200000,
            "recommended_requirement_cents",
        )
        history = report["requirement_history"]
        assert len(history) == 2, "expected two history entries, got {0!r}".format(
            history
        )
        assert history[0]["cycle_year"] == 2026
        assert_cents(
            history[0]["per_seat_requirement_cents"],
            150000,
            "requirement_history[0].per_seat_requirement_cents",
        )
        assert history[1]["cycle_year"] == 2027
        assert_cents(
            history[1]["per_seat_requirement_cents"],
            200000,
            "requirement_history[1].per_seat_requirement_cents",
        )


def _three_seat_section_and_a_certified_cycle(client):
    """A section whose third seat is the surplus one, plus a cycle to reseat on."""
    set_clock(client, f.instant(2026, 8, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    section, seats = create_section_with_seats(
        client,
        [("D", 1), ("D", 2), ("D", 3)],
        seat_capacity=3,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    return section, seats, cycle


class TestReseatingRetiresTheSurplusSeatInCreatedAtOrder:
    """Shrinking capacity from 3 to 2 retires the third seat created, not any other."""

    def test_reprice_stores_the_new_figures_without_applying_them(self, client):
        """Survey blocks the section; reprice only parks the two values.

        PRD 3.7: "Its side effect is to set `status` to `UNDER_RENOVATION`, which
        blocks every pick into this section for the duration."

        PRD 3.7: "It stores both values on the section without applying either
        one yet; `post_renovation_capacity` and `post_renovation_requirement_cents`
        must each be strictly greater than zero when present, and both remain null
        until this action runs."

        Design: Corner/calculations/reseating_decommissions_the_surplus_seat_by_created_at_ascending
        """
        section, _seats, _cycle = _three_seat_section_and_a_certified_cycle(client)
        assert section["post_renovation_capacity"] is None
        assert section["post_renovation_requirement_cents"] is None

        surveyed = survey_section(client, section["id"])
        assert surveyed["renovation_status"] == RENOVATION_SURVEYED
        assert surveyed["status"] == SECTION_UNDER_RENOVATION

        repriced = reprice_renovation(client, section["id"], 2, 120000)
        assert repriced["renovation_status"] == RENOVATION_REPRICED
        assert repriced["post_renovation_capacity"] == 2
        assert_cents(
            repriced["post_renovation_requirement_cents"],
            120000,
            "post_renovation_requirement_cents",
        )
        assert repriced["seat_capacity"] == 3
        assert_cents(
            repriced["per_seat_requirement_cents"],
            100000,
            "per_seat_requirement_cents",
        )
        assert len(repriced["requirement_history"]) == 1

    def test_start_reseating_decommissions_the_third_seat_created(self, client):
        """The surplus seat is chosen by creation order, and only that seat moves.

        PRD 3.7: "Seats beyond the new capacity are retired: taking the section's
        seats in `created_at` ascending order — never in `id` order — every seat
        still in `seat_status` `AVAILABLE` whose ordinal position in that order
        exceeds `post_renovation_capacity` moves `AVAILABLE → DECOMMISSIONED`,
        shifting one seat out of `seats_available` and into
        `decommissioned_seat_count` and advancing that seat's `version` by 1."

        PRD 2.9: "After every request, including every cascade, the sum of
        `seats_available`, `seats_committed_count` and
        `decommissioned_seat_count` must equal `seat_row_count`."

        Design: Corner/calculations/reseating_decommissions_the_surplus_seat_by_created_at_ascending
        """
        section, seats, cycle = _three_seat_section_and_a_certified_cycle(client)
        survey_section(client, section["id"])
        reprice_renovation(client, section["id"], 2, 120000)

        reseating = start_reseating(client, section["id"], cycle["id"])
        assert reseating["renovation_status"] == RENOVATION_RESEATING
        assert reseating["reseating_recalculation_id"] == cycle["id"]
        assert_seat_inventory(
            reseating,
            seats_available=2,
            seats_committed_count=0,
            decommissioned_seat_count=1,
            seat_row_count=3,
            label="SEC-D",
        )

        for kept in seats[:2]:
            after = read_seat(client, kept["id"])
            assert after["seat_status"] == SEAT_AVAILABLE, (
                "seat {0}/{1} must stay AVAILABLE".format(
                    after["row_label"], after["seat_number"]
                )
            )
            assert after["version"] == kept["version"]

        retired = read_seat(client, seats[2]["id"])
        assert retired["seat_status"] == SEAT_DECOMMISSIONED
        assert retired["version"] == seats[2]["version"] + 1

    def test_the_new_capacity_rate_and_history_entry_are_applied_together(
        self, client
    ):
        """Capacity and rate move to the parked figures and history gains a pairing.

        PRD 3.7: "The section's `seat_capacity` is replaced by
        `post_renovation_capacity` and its `per_seat_requirement_cents` by
        `post_renovation_requirement_cents`, and a new `requirement_history` entry
        is appended pairing the new requirement with the `cycle_year` of the
        reseating recalculation."

        PRD 3.7: "It sets `status` back to `OPEN`, unblocking picks, and recomputes
        `pricing_posture` from the post-reseating underwater ratio."

        Design: Corner/calculations/reseating_decommissions_the_surplus_seat_by_created_at_ascending
        """
        section, _seats, cycle = _three_seat_section_and_a_certified_cycle(client)
        survey_section(client, section["id"])
        reprice_renovation(client, section["id"], 2, 120000)

        reseating = start_reseating(client, section["id"], cycle["id"])
        assert reseating["seat_capacity"] == 2
        assert_cents(
            reseating["per_seat_requirement_cents"],
            120000,
            "per_seat_requirement_cents",
        )
        history = reseating["requirement_history"]
        assert len(history) == 2, "expected two history entries, got {0!r}".format(
            history
        )
        assert history[0]["cycle_year"] == 2026
        assert_cents(
            history[0]["per_seat_requirement_cents"],
            100000,
            "requirement_history[0].per_seat_requirement_cents",
        )
        assert history[1]["cycle_year"] == 2026
        assert_cents(
            history[1]["per_seat_requirement_cents"],
            120000,
            "requirement_history[1].per_seat_requirement_cents",
        )

        completed = renovation_action(client, section["id"], ACTION_COMPLETE)
        assert completed["renovation_status"] == RENOVATION_COMPLETED
        assert completed["status"] == SECTION_OPEN
        assert completed["pricing_posture"] == POSTURE_NORMAL


def _one_seat_holder_below_a_higher_ranked_bystander(client):
    """Rank 1 never picks; rank 2 ends up the section's only ASSIGNED holder."""
    set_clock(client, f.instant(2026, 8, 1))
    bystander = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, bystander["id"], 5000000, f.instant(2026, 3, 1))
    holder = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, holder["id"], 1000000, f.instant(2026, 3, 1))

    cycle = certified_cycle(client, 2026)
    section, seats = create_section_with_seats(
        client,
        [("Q", 1), ("Q", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    season = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    holder_slot = slot_for_donor(client, season["id"], holder["id"])
    bystander_slot = slot_for_donor(client, season["id"], bystander["id"])

    set_clock(client, f.instant(2026, 9, 3, 12))
    assignment = pick_seat_ok(
        client, holder_slot["id"], seats[0]["id"], holder["id"]
    )
    # confirm_assignment already invoices and pays the row in full, so calling
    # invoice_and_pay first would try to invoice an already-INVOICED row.
    assignment = confirm_assignment(client, assignment["id"])
    assert assignment["occupancy_status"] == OCCUPANCY_ASSIGNED
    assert assignment["payment_status"] == PAYMENT_PAID

    return {
        "bystander": bystander,
        "holder": holder,
        "cycle": cycle,
        "section": section,
        "season_event": season,
        "holder_season_slot": holder_slot,
        "bystander_season_slot": bystander_slot,
    }


class TestThePostseasonPoolIsRestrictedToSeatHolders:
    """The same four-key ordering over a pool that excludes the top donor."""

    def test_the_top_ranked_donor_is_left_out_of_the_postseason_pool(self, client):
        """One slot for the seat holder; none at all for the higher-ranked donor.

        PRD 3.5: "The candidate pool for a selection event admits a donor when the
        donor's `donor_status` is `ACTIVE` or `LAPSED`, when their
        `certified_points` is at least the event's `eligible_donor_min_points`,
        and — for a `POSTSEASON` or `AWAY_GAME` event — when the donor holds at
        least one seat assignment whose `occupancy_status` is `ASSIGNED`."

        Design: Corner/calculations/postseason_pool_excludes_the_top_ranked_donor_who_holds_no_assigned_seat
        """
        state = _one_seat_holder_below_a_higher_ranked_bystander(client)

        assert_donor_points(
            read_donor(client, state["bystander"]["id"]),
            certified_points="67.50",
            rank_position=1,
            label="bystander",
        )
        assert_donor_points(
            read_donor(client, state["holder"]["id"]),
            certified_points="15.00",
            rank_position=2,
            label="holder",
        )

        postseason = create_event(
            client,
            state["cycle"]["id"],
            f.instant(2026, 9, 6),
            f.instant(2026, 9, 8),
            1440,
            event_type=EVENT_POSTSEASON,
        )
        published = publish_slots(client, postseason["id"])
        assert published["event_type"] == EVENT_POSTSEASON
        assert published["status"] == EVENT_SLOTS_PUBLISHED
        assert published["published_slot_count"] == 1
        assert published["scheduled_slot_count"] == 1

        rows, meta = validate_list(
            client.list_selection_slots(
                headers=OFFICER,
                params={
                    "selection_event_id": postseason["id"],
                    "donor_id": state["bystander"]["id"],
                },
            )
        )
        assert_page_meta(meta, total_count=0)
        assert rows == [], "the excluded donor must have no postseason slot"

    def test_the_single_slot_keeps_the_ranking_it_was_published_with(self, client):
        """Slot index 0 carries rank_at_publish 2 and the window's first day.

        PRD 3.8: "It ranks the eligible pool on the four keys of §3.5 and creates
        one slot per ranked donor, each carrying the donor's `donor_id`, its
        `selection_event_id`, a `slot_index`, a `slot_start`, a `slot_end`, and
        `rank_at_publish` — the donor's `rank_position` as observed at
        publication, which is the comparand the staleness check later reads."

        Design: Corner/calculations/postseason_pool_excludes_the_top_ranked_donor_who_holds_no_assigned_seat
        """
        state = _one_seat_holder_below_a_higher_ranked_bystander(client)

        postseason = create_event(
            client,
            state["cycle"]["id"],
            f.instant(2026, 9, 6),
            f.instant(2026, 9, 8),
            1440,
            event_type=EVENT_POSTSEASON,
        )
        publish_slots(client, postseason["id"])

        slot = slot_for_donor(client, postseason["id"], state["holder"]["id"])
        assert slot["slot_index"] == 0
        assert slot["rank_at_publish"] == 2
        assert slot["slot_status"] == SLOT_SCHEDULED
        assert_instant(slot["slot_start"], f.instant(2026, 9, 6), "slot_start")
        assert_instant(slot["slot_end"], f.instant(2026, 9, 7), "slot_end")

    def test_publishing_the_second_event_leaves_the_first_events_slots_alone(
        self, client
    ):
        """The season-ticket slots keep their own statuses and the ranks stand.

        PRD 3.5: "Postseason and away-game events reuse the identical ordering but
        restrict the pool to existing seat holders, which is how a high-point donor
        with no assigned seat is excluded from an otherwise identical ranking."

        Design: Corner/calculations/postseason_pool_excludes_the_top_ranked_donor_who_holds_no_assigned_seat
        """
        state = _one_seat_holder_below_a_higher_ranked_bystander(client)

        postseason = create_event(
            client,
            state["cycle"]["id"],
            f.instant(2026, 9, 6),
            f.instant(2026, 9, 8),
            1440,
            event_type=EVENT_POSTSEASON,
        )
        publish_slots(client, postseason["id"])

        consumed = read_slot(client, state["holder_season_slot"]["id"])
        assert consumed["slot_status"] == SLOT_CONSUMED
        unused = read_slot(client, state["bystander_season_slot"]["id"])
        assert unused["slot_status"] == SLOT_SCHEDULED
        assert unused["rank_at_publish"] == 1

        assert read_donor(client, state["bystander"]["id"])["rank_position"] == 1
        assert read_donor(client, state["holder"]["id"])["rank_position"] == 2
