"""Admission-side rejection ladder: the queue, the gate and the squad.

Each class triggers one business rule at a time on a single endpoint with every
other rule on that endpoint satisfied, so a refusal can only be explained by the
rule under test.
"""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    BondPaymentPlan,
    CaseSeverity,
    DuesStatus,
    HouseholdStanding,
    PriorityTier,
    RegistrationStatus,
    SanctionType,
    Squad,
    WaitlistStatus,
    assertions as a,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    guest_visit_payload,
    household_payment_payload,
    membership_payload,
    next_offer_payload,
    transition_payload,
    waitlist_entry_payload,
)
from test_helpers.test_users import (
    MEMBERSHIP_CHAIR,
    POOL_MANAGER,
    SWIM_TEAM_COACH,
    TREASURER,
)

ADMISSION_CLOCK = "2027-06-01T09:00:00Z"
ADMISSION_JOIN_DATE = "2027-06-01"


def _two_categories_and_two_households(api):
    """A queue-bearing FAMILY category, a queue-free COUPLE one, two households.

    Household BIG carries eight people, above both categories' caps; household A
    carries four, which is exactly ``max_household_size`` on the COUPLE category.
    """
    fx.set_clock(api, ADMISSION_CLOCK)
    family = fx.create_family_category(api, waitlist_required=True)
    couple = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    big = fx.create_household(
        api, primary_contact_name="Oversized Household",
        address_line="171 Cedar Court", member_count=8, prior_member=False,
    )
    admissible = fx.create_household(
        api, primary_contact_name="Admissible Household",
        address_line="172 Cedar Court", member_count=4, prior_member=False,
    )
    assert family["waitlist_required"] is True
    assert couple["waitlist_required"] is False
    return {
        "family": family, "couple": couple, "season": season,
        "big": big, "admissible": admissible,
    }


def _attempt_membership(api, household_id, category_id, season_id,
                        join_date=ADMISSION_JOIN_DATE,
                        bond_payment_plan=BondPaymentPlan.INSTALLMENTS):
    return api.create_membership(
        membership_payload(
            household_id=household_id, membership_category_id=category_id,
            season_id=season_id, join_date=join_date,
            bond_payment_plan=bond_payment_plan,
        ),
        MEMBERSHIP_CHAIR,
    )


def _attempt_waitlist_entry(api, household_id, category_id,
                            priority_tier=PriorityTier.STANDARD):
    return api.create_waitlist_entry(
        waitlist_entry_payload(
            household_id=household_id, membership_category_id=category_id,
            priority_tier=priority_tier,
        ),
        MEMBERSHIP_CHAIR,
    )


class TestTheMembershipAdmissionGateRefusesFourDifferentWays:
    """POST /swim-club/memberships is four rules, not one."""

    def test_an_oversized_household_is_stopped_at_both_doors(self, api):
        """The size cap guards the queue as well as the sale.

        PRD §3.3: "A household whose `member_count` exceeds the category's
        `max_household_size` is refused with `ERR_HOUSEHOLD_SIZE_EXCEEDED`."

        PRD §3.2: "when the household's `member_count` exceeds the category's
        `max_household_size` (`ERR_HOUSEHOLD_SIZE_EXCEEDED`)"

        Design: Corner/validations/violation_to_error_membership_admission_gate_rejects_four_distinct_ways
        """
        ctx = _two_categories_and_two_households(api)

        validate_error(
            _attempt_membership(api, ctx["big"]["id"], ctx["family"]["id"],
                                ctx["season"]["id"]),
            ApiErrorId.HOUSEHOLD_SIZE_EXCEEDED, 422,
        )
        validate_error(
            _attempt_waitlist_entry(api, ctx["big"]["id"], ctx["family"]["id"]),
            ApiErrorId.HOUSEHOLD_SIZE_EXCEEDED, 422,
        )

        rows, _ = validate_paginated(
            api.list_waitlist_entries(
                MEMBERSHIP_CHAIR, {"household_id": ctx["big"]["id"]}
            )
        )
        assert rows == []

    def test_a_fitting_household_still_needs_an_accepted_offer(self, api):
        """Size is satisfied and the queue rule fires on its own.

        PRD §3.3: "Where the category's `waitlist_required` is true, the
        household must already hold a waitlist entry for that same category in
        `ACCEPTED` status, and its absence is reported as
        `ERR_WAITLIST_OFFER_REQUIRED`."

        Design: Corner/validations/violation_to_error_membership_admission_gate_rejects_four_distinct_ways
        """
        ctx = _two_categories_and_two_households(api)

        body = validate_error(
            _attempt_membership(api, ctx["admissible"]["id"],
                                ctx["family"]["id"], ctx["season"]["id"]),
            ApiErrorId.WAITLIST_OFFER_REQUIRED, 409,
        )
        assert body["error_id"] != ApiErrorId.HOUSEHOLD_SIZE_EXCEEDED

        rows, _ = validate_paginated(
            api.list_memberships(
                MEMBERSHIP_CHAIR, {"household_id": ctx["admissible"]["id"]}
            )
        )
        assert rows == []

    def test_the_duplicate_entry_rule_covers_waiting_and_accepted_alike(self, api):
        """A different priority tier does not make a second entry distinct.

        PRD §3.2: "Joining is refused when the household already holds an entry
        for that same category in `WAITING`, `OFFERED` or `ACCEPTED`
        (`ERR_DUPLICATE_WAITLIST_ENTRY`)"

        Design: Corner/validations/violation_to_error_membership_admission_gate_rejects_four_distinct_ways
        """
        ctx = _two_categories_and_two_households(api)
        entry = fx.join_waitlist(api, ctx["admissible"]["id"],
                                 ctx["family"]["id"],
                                 priority_tier=PriorityTier.STANDARD)
        assert entry["status"] == WaitlistStatus.WAITING

        validate_error(
            _attempt_waitlist_entry(api, ctx["admissible"]["id"],
                                    ctx["family"]["id"],
                                    priority_tier=PriorityTier.LEGACY),
            ApiErrorId.DUPLICATE_WAITLIST_ENTRY, 409,
        )

        offered = fx.extend_next_offer(api, ctx["family"]["id"])
        assert offered["id"] == entry["id"]
        assert offered["status"] == WaitlistStatus.OFFERED
        accepted = fx.respond_to_offer(api, entry["id"],
                                       ctx["admissible"]["id"], "ACCEPT")
        assert accepted["status"] == WaitlistStatus.ACCEPTED

        validate_error(
            _attempt_waitlist_entry(api, ctx["admissible"]["id"],
                                    ctx["family"]["id"]),
            ApiErrorId.DUPLICATE_WAITLIST_ENTRY, 409,
        )

    def test_the_accepted_offer_admits_exactly_one_membership(self, api):
        """The offer discharges the queue rule and the season slot is then taken.

        PRD §3.3: "A household that already holds a membership for the same
        season whose `access_status` is anything other than `LAPSED` or
        `TERMINATED` is refused as a duplicate (`ERR_DUPLICATE_MEMBERSHIP`)"

        Design: Corner/validations/violation_to_error_membership_admission_gate_rejects_four_distinct_ways
        """
        ctx = _two_categories_and_two_households(api)
        fx.setup_accepted_waitlist_entry(api, ctx["admissible"]["id"],
                                         ctx["family"]["id"])

        membership = validate_success(
            _attempt_membership(api, ctx["admissible"]["id"],
                                ctx["family"]["id"], ctx["season"]["id"]),
            201,
        )
        assert membership["dues_status"] == DuesStatus.UNBILLED
        assert membership["access_status"] == AccessStatus.PENDING

        validate_error(
            _attempt_membership(api, ctx["admissible"]["id"],
                                ctx["family"]["id"], ctx["season"]["id"],
                                join_date="2027-06-02"),
            ApiErrorId.DUPLICATE_MEMBERSHIP, 409,
        )

        rows, _ = validate_paginated(
            api.list_memberships(
                MEMBERSHIP_CHAIR,
                {"household_id": ctx["admissible"]["id"],
                 "season_id": ctx["season"]["id"]},
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == membership["id"]


def _a_suspended_household_holding_the_only_queue_entry(api):
    """One LEGACY WAITING entry whose household is suspended afterwards.

    The entry is created while the household is still in ``GOOD_STANDING``, so
    the eligibility filter of PRD §3.2 can only be applied at selection time.
    """
    fx.set_clock(api, ADMISSION_CLOCK)
    family = fx.create_family_category(api, waitlist_required=True)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Suspended Queue Household",
        address_line="181 Cedar Court", member_count=4, prior_member=False,
    )
    entry = fx.join_waitlist(api, household["id"], family["id"],
                             priority_tier=PriorityTier.LEGACY)
    case = fx.sanction_household(api, household["id"], CaseSeverity.SEVERE,
                                 SanctionType.SUSPENSION)
    return {
        "family": family, "season": season, "household": household,
        "entry": entry, "case": case,
    }


class TestTheOfferSelectorSkipsASuspendedHouseholdAndFindsNothing:
    """An empty candidate set is not the same thing as an empty table."""

    def test_the_entry_is_the_certain_winner_until_the_sanction_lands(self, api):
        """LEGACY ranks 0 and the suspension arrives after the entry exists.

        PRD §3.2: "`LEGACY` ranks 0, `SIBLING` ranks 1, `STANDARD` ranks 2, so a
        lower rank is served first."

        Design: Corner/validations/violation_to_error_the_selector_skips_a_suspended_household_and_finds_nothing
        """
        ctx = _a_suspended_household_holding_the_only_queue_entry(api)

        a.assert_waitlist_entry(ctx["entry"],
                                expected_status=WaitlistStatus.WAITING)
        assert ctx["entry"]["priority_tier"] == PriorityTier.LEGACY
        assert ctx["entry"]["priority_tier_rank"] == 0
        assert fx.read_household(
            api, ctx["household"]["id"]
        )["standing"] == HouseholdStanding.SUSPENDED

    def test_the_selector_reports_an_empty_queue_and_touches_nothing(self, api):
        """A WAITING row exists and the offer is still refused.

        PRD §3.2: "The candidate set is every entry in `WAITING` for the
        requested category whose household is in `GOOD_STANDING`; entries whose
        household is on `PROBATION`, `SUSPENDED` or `EXPELLED` are skipped and
        their status is left untouched"

        PRD §3.2: "If the candidate set is empty the request is rejected with
        `ERR_WAITLIST_EMPTY`."

        Design: Corner/validations/violation_to_error_the_selector_skips_a_suspended_household_and_finds_nothing
        """
        ctx = _a_suspended_household_holding_the_only_queue_entry(api)

        validate_error(
            api.next_waitlist_offer(next_offer_payload(ctx["family"]["id"]),
                                    MEMBERSHIP_CHAIR),
            ApiErrorId.WAITLIST_EMPTY, 409,
        )

        entry = fx.read_waitlist_entry(api, ctx["entry"]["id"])
        assert entry["status"] == WaitlistStatus.WAITING
        assert entry["offered_at"] is None
        assert entry["offer_expires_at"] is None
        assert entry["version"] == ctx["entry"]["version"]

    def test_a_fresh_entry_is_refused_for_the_standing_not_the_duplicate(self, api):
        """Two rules hold at once and the higher band names the error.

        PRD §2.9: "the acting or referenced household is not suspended or
        expelled (`ERR_HOUSEHOLD_SUSPENDED`, 409)"

        Design: Corner/validations/violation_to_error_the_selector_skips_a_suspended_household_and_finds_nothing
        """
        ctx = _a_suspended_household_holding_the_only_queue_entry(api)

        body = validate_error(
            _attempt_waitlist_entry(api, ctx["household"]["id"],
                                    ctx["family"]["id"]),
            ApiErrorId.HOUSEHOLD_SUSPENDED, 409,
        )
        assert body["error_id"] != ApiErrorId.DUPLICATE_WAITLIST_ENTRY

        rows, _ = validate_paginated(
            api.list_waitlist_entries(
                MEMBERSHIP_CHAIR, {"household_id": ctx["household"]["id"]}
            )
        )
        assert len(rows) == 1

    def test_the_same_standing_outranks_the_missing_offer_on_a_sale(self, api):
        """Band 11 is reached before band 15 on the membership endpoint too.

        PRD §3.3: "A household whose `standing` is `SUSPENDED` or `EXPELLED`
        cannot buy in at all (`ERR_HOUSEHOLD_SUSPENDED`)."

        Design: Corner/validations/violation_to_error_the_selector_skips_a_suspended_household_and_finds_nothing
        """
        ctx = _a_suspended_household_holding_the_only_queue_entry(api)

        body = validate_error(
            _attempt_membership(api, ctx["household"]["id"],
                                ctx["family"]["id"], ctx["season"]["id"]),
            ApiErrorId.HOUSEHOLD_SUSPENDED, 409,
        )
        assert body["error_id"] != ApiErrorId.WAITLIST_OFFER_REQUIRED


GATE_CLOCK = "2027-07-11T09:00:00Z"
PRESEASON_VISIT = "2027-05-01T14:00:00Z"
FUTURE_VISIT = "2027-07-20T14:00:00Z"
SATURDAY_VISIT = "2027-07-10T14:00:00Z"
THURSDAY_VISIT = "2027-07-08T14:00:00Z"
FRIDAY_VISIT = "2027-07-09T14:00:00Z"


def _a_household_with_no_passes_at_the_gate(api):
    """An ACTIVE SINGLE membership whose category grants no free passes."""
    fx.set_clock(api, GATE_CLOCK)
    category = fx.create_single_category(api)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Gate Rules Household",
        address_line="191 Cedar Court", member_count=1, prior_member=False,
    )
    membership = fx.setup_membership(
        api, household["id"], category["id"], season["id"],
        join_date="2027-07-01", bond_payment_plan=BondPaymentPlan.FULL,
    )
    membership = fx.invoice_membership(api, membership["id"])
    assert membership["access_status"] == AccessStatus.ACTIVE
    assert category["guest_pass_allotment"] == 0
    return {"category": category, "season": season, "household": household,
            "membership": membership}


def _attempt_visit(api, ctx, guest_count, visit_start_iso, sponsor_name):
    """Record a visit with a freshly read household version, so §2.7 is silent."""
    household = fx.read_household(api, ctx["household"]["id"])
    return api.create_guest_visit(
        guest_visit_payload(
            membership_id=ctx["membership"]["id"],
            expected_household_version=household["version"],
            sponsor_name=sponsor_name, guest_count=guest_count,
            visit_start_iso=visit_start_iso,
        ),
        POOL_MANAGER,
    )


def _visits_of(api, ctx):
    rows, _ = validate_paginated(
        api.list_guest_visits(POOL_MANAGER,
                              {"membership_id": ctx["membership"]["id"]})
    )
    return rows


class TestTheGateChecksTheWindowTheCountAndTheLedger:
    """Four rules on POST /swim-club/guest-visits, one at a time."""

    def test_a_visit_before_the_season_opened_is_outside_the_window(self, api):
        """Being in the past does not save a date outside the window.

        PRD §3.5: "The visit's date must fall inside the season's window, from
        `open_date` to `close_date` inclusive, or the request is
        `ERR_OUTSIDE_SEASON_WINDOW`."

        Design: Corner/validations/violation_to_error_guest_visit_window_count_and_delinquency_gates
        """
        ctx = _a_household_with_no_passes_at_the_gate(api)

        validate_error(
            _attempt_visit(api, ctx, 2, PRESEASON_VISIT, "Preseason Guest"),
            ApiErrorId.OUTSIDE_SEASON_WINDOW, 422,
        )
        assert _visits_of(api, ctx) == []

    def test_a_visit_after_the_clock_has_not_happened_yet(self, api):
        """Inside the window and still refused, by the next rule down.

        PRD §3.5: "A `visit_start_iso` later than the logical clock is a visit
        that has not happened yet and is rejected with `ERR_VISIT_IN_FUTURE`."

        Design: Corner/validations/violation_to_error_guest_visit_window_count_and_delinquency_gates
        """
        ctx = _a_household_with_no_passes_at_the_gate(api)

        body = validate_error(
            _attempt_visit(api, ctx, 2, FUTURE_VISIT, "Next Week Guest"),
            ApiErrorId.VISIT_IN_FUTURE, 422,
        )
        assert body["error_id"] != ApiErrorId.OUTSIDE_SEASON_WINDOW
        assert _visits_of(api, ctx) == []

    def test_seven_guests_are_refused_and_six_are_admitted(self, api):
        """The upper bound of the inclusive range is six.

        PRD §3.5: "`guest_count` must lie between 1 and 6 inclusive; a party of
        seven at the gate is `ERR_GUEST_LIMIT_EXCEEDED`."

        PRD §3.5: "eight hundred cents per guest on a weekend, five hundred
        cents per guest on a weekday"

        Design: Corner/validations/violation_to_error_guest_visit_window_count_and_delinquency_gates
        """
        ctx = _a_household_with_no_passes_at_the_gate(api)

        validate_error(
            _attempt_visit(api, ctx, 7, SATURDAY_VISIT, "Seven Guests"),
            ApiErrorId.GUEST_LIMIT_EXCEEDED, 422,
        )
        assert _visits_of(api, ctx) == []

        visit = fx.record_visit(api, ctx["membership"]["id"],
                               ctx["household"]["id"], 6, THURSDAY_VISIT,
                               sponsor_name="Six Guests At The Limit")
        assert visit["is_weekend"] is False
        assert visit["passes_used"] == 0
        assert visit["fee_charged_cents"] == 3000
        a.assert_household_pass_ledger(
            fx.read_household(api, ctx["household"]["id"]),
            granted=0, consumed=0, balance=0, fee_owed_cents=3000,
        )

    def test_the_unpaid_gate_fee_makes_the_household_delinquent(self, api):
        """A 3000-cent guest bill is enough to close the gate, and money reopens it.

        PRD §3.4: "The household is treated as delinquent when it holds any
        membership in the season whose `dues_status` is `DELINQUENT` or
        `WRITTEN_OFF`, or when the sum of its `guest_fee_owed_cents` and its
        `party_charges_owed_cents` is greater than zero — the club's tolerance
        for outstanding household charges is exactly zero cents."

        PRD §3.2: "An `allocation` of `GUEST_FEES` lowers `guest_fee_owed_cents`
        by the amount paid"

        Design: Corner/validations/violation_to_error_guest_visit_window_count_and_delinquency_gates
        """
        ctx = _a_household_with_no_passes_at_the_gate(api)
        fx.record_visit(api, ctx["membership"]["id"], ctx["household"]["id"],
                        6, THURSDAY_VISIT, sponsor_name="Six Guests At The Limit")
        assert fx.read_membership(
            api, ctx["membership"]["id"]
        )["dues_status"] == DuesStatus.INVOICED

        validate_error(
            _attempt_visit(api, ctx, 1, FRIDAY_VISIT, "One More Guest"),
            ApiErrorId.DUES_DELINQUENT, 402,
        )
        assert len(_visits_of(api, ctx)) == 1

        household = validate_success(
            api.create_household_payment(
                ctx["household"]["id"],
                household_payment_payload(amount_cents=3000,
                                          allocation="GUEST_FEES"),
                TREASURER,
            ),
            200,
        )
        assert household["guest_fee_owed_cents"] == 0

        retried = fx.record_visit(api, ctx["membership"]["id"],
                                  ctx["household"]["id"], 1, FRIDAY_VISIT,
                                  sponsor_name="One More Guest Retried")
        assert retried["fee_charged_cents"] == 500
        assert len(_visits_of(api, ctx)) == 2


SQUAD_CLOCK = "2027-07-01T09:00:00Z"
SQUAD_JOIN_DATE = "2027-06-01"
MINI_CAPACITY = 20


def _a_mini_squad_filled_with_twenty_pending_swimmers(api):
    """Twenty PENDING MINI registrations spread over four households.

    None of the twenty is ever confirmed, so an occupancy count that looks only
    at ``CONFIRMED`` rows would see an empty squad.
    """
    fx.set_clock(api, SQUAD_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)

    memberships = []
    for index in range(1, 6):
        household = fx.create_household(
            api, primary_contact_name=f"Squad Household SF-{index}",
            address_line=f"28{index} Cedar Court", member_count=4,
            prior_member=False,
        )
        membership = fx.setup_membership(
            api, household["id"], category["id"], season["id"],
            join_date=SQUAD_JOIN_DATE, bond_payment_plan=BondPaymentPlan.FULL,
        )
        memberships.append(fx.invoice_membership(api, membership["id"]))

    incumbents = []
    for swimmer in range(1, MINI_CAPACITY + 1):
        owner = memberships[(swimmer - 1) // 5]
        incumbents.append(fx.register_swimmer(
            api, owner["id"], season["id"],
            swimmer_name=f"Mini Swimmer {swimmer:02d}",
            swimmer_birthdate=f"2016-01-{swimmer:02d}",
            squad=Squad.MINI,
        ))

    return {
        "category": category, "season": season, "memberships": memberships,
        "incumbents": incumbents, "newcomer_membership": memberships[4],
    }


def _register_the_twenty_first_swimmer(api, ctx):
    return fx.register_swimmer(
        api, ctx["newcomer_membership"]["id"], ctx["season"]["id"],
        swimmer_name="Mini Swimmer 21", swimmer_birthdate="2016-01-21",
        squad=Squad.MINI,
    )


def _attempt_confirmation(api, registration_id):
    return api.transition_registration(
        registration_id, transition_payload(RegistrationStatus.CONFIRMED),
        SWIM_TEAM_COACH,
    )


def _pending_mini_registrations(api, ctx):
    rows, _ = validate_paginated(
        api.list_registrations(
            SWIM_TEAM_COACH,
            {"season_id": ctx["season"]["id"], "squad": Squad.MINI,
             "status": RegistrationStatus.PENDING, "limit": 100},
        )
    )
    return rows


class TestAFullSquadBlocksTheWaitlistedConfirmation:
    """Occupancy counts PENDING rows, and it is counted live."""

    def test_pending_rows_occupy_the_squad(self, api):
        """Twenty places are taken without a single confirmation.

        PRD §3.6: "Each squad has a standing capacity — twenty places in `MINI`,
        thirty in `JUNIOR` and thirty in `SENIOR` — counted across the season's
        registrations in `PENDING`, `CONFIRMED` or `COMPLETED`."

        Design: Corner/validations/violation_to_error_a_full_squad_blocks_the_waitlisted_confirmation
        """
        ctx = _a_mini_squad_filled_with_twenty_pending_swimmers(api)

        assert len(_pending_mini_registrations(api, ctx)) == MINI_CAPACITY
        assert all(r["status"] == RegistrationStatus.PENDING
                   for r in ctx["incumbents"])
        newcomer_membership = fx.read_membership(
            api, ctx["newcomer_membership"]["id"]
        )
        assert newcomer_membership["access_status"] == AccessStatus.ACTIVE
        assert newcomer_membership["dues_status"] == DuesStatus.INVOICED

    def test_the_twenty_first_swimmer_is_waitlisted_rather_than_refused(self, api):
        """A full squad is not an error at creation.

        PRD §3.6: "A full squad does not reject the registration: the swimmer is
        simply born `WAITLISTED` instead of `PENDING`."

        Design: Corner/validations/violation_to_error_a_full_squad_blocks_the_waitlisted_confirmation
        """
        ctx = _a_mini_squad_filled_with_twenty_pending_swimmers(api)

        newcomer = _register_the_twenty_first_swimmer(api, ctx)
        a.assert_registration(
            newcomer, expected_status=RegistrationStatus.WAITLISTED
        )
        assert newcomer["squad_seq"] == 1

    def test_the_promotion_is_refused_while_the_squad_is_full(self, api):
        """The refusal is a capacity complaint, not a shape complaint.

        PRD §3.6: "A `WAITLISTED → CONFIRMED` move does: the count of the
        season's registrations in that same squad with `status` `PENDING`,
        `CONFIRMED` or `COMPLETED` must be strictly below the squad's capacity,
        and this is the only edge in the whole system that raises
        `ERR_SQUAD_FULL`"

        Design: Corner/validations/violation_to_error_a_full_squad_blocks_the_waitlisted_confirmation
        """
        ctx = _a_mini_squad_filled_with_twenty_pending_swimmers(api)
        newcomer = _register_the_twenty_first_swimmer(api, ctx)

        body = validate_error(
            _attempt_confirmation(api, newcomer["id"]),
            ApiErrorId.SQUAD_FULL, 409,
        )
        assert body["error_id"] != ApiErrorId.INVALID_TRANSITION
        assert fx.read_registration(
            api, newcomer["id"]
        )["status"] == RegistrationStatus.WAITLISTED

    def test_withdrawing_an_incumbent_frees_the_slot_for_the_newcomer(self, api):
        """The count is live, and the freed slot promotes the waiting swimmer.

        PRD §3.6: "From `PENDING` and from `CONFIRMED`, withdrawal releases every
        volunteer assignment of that registration still in `ASSIGNED`, and the
        freed squad slot promotes the earliest `WAITLISTED` registration for the
        same season and squad — ordered by `created_at` ascending — back to
        `PENDING`; that promotion happens only while the squad count is strictly
        below capacity."

        Design: Corner/validations/violation_to_error_a_full_squad_blocks_the_waitlisted_confirmation
        """
        ctx = _a_mini_squad_filled_with_twenty_pending_swimmers(api)
        newcomer = _register_the_twenty_first_swimmer(api, ctx)
        validate_error(_attempt_confirmation(api, newcomer["id"]),
                       ApiErrorId.SQUAD_FULL, 409)

        withdrawn = fx.transition_registration(
            api, ctx["incumbents"][0]["id"], RegistrationStatus.WITHDRAWN
        )
        assert withdrawn["status"] == RegistrationStatus.WITHDRAWN
        assert fx.read_registration(
            api, newcomer["id"]
        )["status"] == RegistrationStatus.PENDING

        confirmed = validate_success(
            _attempt_confirmation(api, newcomer["id"]), 200
        )
        assert confirmed["status"] == RegistrationStatus.CONFIRMED
        assert len(_pending_mini_registrations(api, ctx)) == MINI_CAPACITY - 1
