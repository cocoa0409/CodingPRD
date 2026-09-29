"""Multi-hop cascades that reach rows the request never names."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    habitat_conservation_plan_payload,
    listing_change_payload,
    monitoring_report_payload,
)
from test_helpers.fixtures import (
    REGISTRAR,
    REVIEWER,
    build_scenario,
    read_action,
    read_bank,
    set_clock,
    read_consultation,
    read_permit,
    read_plan,
    read_proponent,
    setup_take_threshold_cascade,
    submit_biological_assessment,
)
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_error_envelope,
    assert_same_instant,
    assert_take_ledger_identity,
    assert_unpaginated_list,
)


class TestTakeExceedanceCascade:
    """One monitoring report reaches the permit, plan, action, consultation and proponent."""

    def test_a_report_below_the_trigger_cascades_nothing(self, api):
        """Two of the four authorised units leave the permit active.

        PRD: "Once past the guard, `take_consumed_units` becomes the previous
        `take_consumed_units` plus `take_units_reported`, rounded half up to two
        decimal places, and `take_remaining_units` becomes `authorized_take_units`
        minus the new `take_consumed_units`".

        PRD: "`due_at` is `period_end` advanced by 45 calendar days, and it is a
        date-only value."

        Design: Difficulty/transitive_cascade/take_exceedance_cascade_six_hops_from_report_to_compliance_score
        """
        scenario = setup_take_threshold_cascade()

        assert scenario["r1"]["due_at"] == "2027-02-14"
        assert scenario["r1"]["is_late"] is False
        permit = scenario["permit_after_r1"]
        assert permit["take_consumed_units"] == 2.00
        assert permit["take_remaining_units"] == 2.00
        assert permit["status"] == "ACTIVE"

    def test_the_second_report_suspends_the_permit_on_an_inclusive_threshold(self, api):
        """Exactly reaching the trigger is enough to suspend.

        PRD: "When `take_consumed_units` is at or above `reinitiation_trigger_units` -
        the boundary is inclusive, so exact equality suspends the permit - and the
        permit is `ACTIVE`, the take-exceedance cascade fires in five hops. Hop one is
        the report row itself, now `SUBMITTED` with its take applied. Hop two moves the
        permit `ACTIVE - SUSPENDED` and increases `suspension_count` by 1."

        PRD: "On an incidental take permit, `authorized_take_units` always equals
        `take_consumed_units` plus `take_remaining_units`."

        Design: Difficulty/transitive_cascade/take_exceedance_cascade_six_hops_from_report_to_compliance_score
        """
        scenario = setup_take_threshold_cascade()

        assert scenario["r2"]["status"] == "SUBMITTED"
        assert scenario["r2"]["due_at"] == "2027-05-15"
        assert scenario["r2"]["is_late"] is True
        permit = read_permit(scenario["permit"]["id"])
        assert permit["take_consumed_units"] == 3.60
        assert permit["take_remaining_units"] == 0.40
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_count"] == 1
        assert_take_ledger_identity(permit)

    def test_the_cascade_reaches_the_plan_the_action_and_the_consultation(self, api):
        """Hops three, four and five land on rows the request never named.

        PRD: "Hop three moves the plan `IMPLEMENTING - SUSPENDED_IMPLEMENTATION` and
        sets `assurance_review_required` to true ... Hop four moves the action
        `PERMITTED - REINITIATION_PENDING` with `reinitiation_reason` set to
        `TAKE_EXCEEDANCE`. Hop five reaches the consultation named by the action's
        `active_consultation_id`: if and only if its `status` is `OPINION_ISSUED`, it
        moves `OPINION_ISSUED - REINITIATION_REQUIRED`, stamping
        `reinitiation_triggered_at` and increasing `reinitiation_count` by 1".

        Design: Difficulty/transitive_cascade/take_exceedance_cascade_six_hops_from_report_to_compliance_score
        """
        scenario = setup_take_threshold_cascade()

        plan = read_plan(scenario["plan"]["id"])
        assert plan["plan_status"] == "SUSPENDED_IMPLEMENTATION"
        assert plan["assurance_review_required"] is True
        action = read_action(scenario["action"]["id"])
        assert action["status"] == "REINITIATION_PENDING"
        assert action["reinitiation_reason"] == "TAKE_EXCEEDANCE"
        consultation = read_consultation(scenario["consultation"]["id"])
        assert consultation["status"] == "REINITIATION_REQUIRED"
        assert consultation["reinitiation_count"] == 1
        assert_same_instant(
            consultation["reinitiation_triggered_at"], "2027-05-20T00:00:00Z"
        )

    def test_the_cascade_reaches_the_proponent_compliance_score(self, api):
        """An open reinitiation costs eighteen points at zero age.

        PRD: "after which the owning proponent's `open_reinitiation_count` increases by
        1 and its `compliance_standing_score` is recomputed."

        PRD: "Each of the proponent's consultations currently sitting in
        `REINITIATION_REQUIRED` contributes a weight of 18, dated at that
        consultation's `reinitiation_triggered_at`."

        PRD: "Reports that are `SUBMITTED` but not yet adjudicated contribute nothing".

        The still-`SUBMITTED` late report contributes nothing, because only an accepted
        late report is a penalty event.

        Design: Difficulty/transitive_cascade/take_exceedance_cascade_six_hops_from_report_to_compliance_score
        """
        scenario = setup_take_threshold_cascade()

        proponent = read_proponent(scenario["proponent"]["id"])

        assert proponent["open_reinitiation_count"] == 1
        assert proponent["compliance_variant_applied"] == "ROLLING_12_MONTH"
        assert proponent["compliance_standing_score"] == 82.00

    def test_the_funding_fields_are_untouched_by_the_whole_cascade(self, api):
        """No hop of the cascade moves money.

        PRD: "Neither dimension's transitions are constrained by the other's position
        except where a specific rule says so."

        PRD: "`funding_status` becomes `FULLY_ASSURED` when `endowment_secured_cents`
        is at least `endowment_required_cents`".

        Design: Difficulty/transitive_cascade/take_exceedance_cascade_six_hops_from_report_to_compliance_score
        """
        scenario = setup_take_threshold_cascade()

        plan = read_plan(scenario["plan"]["id"])

        assert plan["endowment_required_cents"] == 5_026_514
        assert plan["endowment_secured_cents"] == 5_026_514
        assert plan["funding_status"] == "FULLY_ASSURED"

    def test_resuming_review_unwinds_only_the_two_consultation_hops(self, api):
        """A fresh assessment restarts the clock without releasing the permit.

        PRD: "From `REINITIATION_REQUIRED - UNDER_REVIEW`, the statutory clock
        **restarts** rather than extends ... in the same request the action named by
        `project_action_id` leaves `REINITIATION_PENDING` for `FORMAL_CONSULTATION` with
        its `reinitiation_reason` reset to `NONE`, and the owning proponent's
        `open_reinitiation_count` and `compliance_standing_score` are recomputed."

        Design: Difficulty/transitive_cascade/take_exceedance_cascade_six_hops_from_report_to_compliance_score
        """
        scenario = setup_take_threshold_cascade()

        consultation = submit_biological_assessment(
            scenario["consultation"]["id"], scenario["proponent"]
        )

        assert consultation["status"] == "UNDER_REVIEW"
        action = read_action(scenario["action"]["id"])
        assert action["status"] == "FORMAL_CONSULTATION"
        assert action["reinitiation_reason"] == "NONE"
        assert read_permit(scenario["permit"]["id"])["status"] == "SUSPENDED"
        assert read_plan(scenario["plan"]["id"])["plan_status"] == "SUSPENDED_IMPLEMENTATION"


class TestSpeciesUplistingCascade:
    """A registry write on a species reaches rows in four hops."""

    def _uplist_the_threatened_species(self):
        scenario = build_scenario("opinion")
        scenario["listing_change"] = get_success_data(
            api_client.change_species_listing(
                scenario["threatened_species"]["id"],
                listing_change_payload(
                    new_listing_status="ENDANGERED",
                    rationale="Range-wide decline documented in the 5-year status review.",
                ),
                REGISTRAR,
            ),
            200,
        )
        return scenario

    def test_the_listing_change_writes_its_own_three_fields(self, api):
        """Hop zero is the species row itself.

        PRD: "Every accepted change sets `listing_status` to `new_listing_status`,
        increases `listing_change_count` by 1, and stamps `last_listing_change_at` with
        the current logical clock."

        Design: Difficulty/transitive_cascade/species_uplisting_cascade_four_hops_from_registry_write
        """
        scenario = self._uplist_the_threatened_species()

        species = scenario["listing_change"]
        assert species["listing_status"] == "ENDANGERED"
        assert species["listing_change_count"] == 1
        assert_same_instant(species["last_listing_change_at"], "2026-10-01T00:00:00Z")

    def test_only_the_uplisted_species_determinations_are_flagged(self, api):
        """The cascade is conditional on the species, not on the action.

        PRD: "First, every presence determination for the uplisted species whose
        `presence_status` is either `PRESENT` or `PRESUMED_PRESENT` has
        `requires_reevaluation` set to true, processed in `created_at` ascending order".

        The endangered species was not uplisted, so its determination on the same
        action keeps `requires_reevaluation` false.

        Design: Difficulty/transitive_cascade/species_uplisting_cascade_four_hops_from_registry_write
        """
        scenario = self._uplist_the_threatened_species()

        uplisted, _meta = validate_paginated(
            api.list_presence_determinations(
                scenario["proponent_headers"],
                params={"species_id": scenario["threatened_species"]["id"]},
            )
        )
        untouched, _meta = validate_paginated(
            api.list_presence_determinations(
                scenario["proponent_headers"],
                params={"species_id": scenario["species"]["id"]},
            )
        )

        assert [row["requires_reevaluation"] for row in uplisted] == [True]
        assert [row["requires_reevaluation"] for row in untouched] == [False]

    def test_the_cascade_reaches_the_action_and_the_consultation(self, api):
        """Hops two and three carry a reason distinct from take exceedance.

        PRD: "Second, each project action affected through those determinations whose
        `status` is `CONSULTATION_CONCLUDED`, `HCP_DEVELOPMENT`, or `PERMITTED` moves to
        `REINITIATION_PENDING` with `reinitiation_reason` set to `SPECIES_UPLISTED` ...
        Third, for each such action, the consultation named by its
        `active_consultation_id` moves from `OPINION_ISSUED` to `REINITIATION_REQUIRED`
        ... stamping `reinitiation_triggered_at` with the current logical clock and
        increasing `reinitiation_count` by 1."

        Design: Difficulty/transitive_cascade/species_uplisting_cascade_four_hops_from_registry_write
        """
        scenario = self._uplist_the_threatened_species()
        assert scenario["action"]["status"] == "CONSULTATION_CONCLUDED"
        assert scenario["action"]["reinitiation_reason"] == "NONE"

        action = read_action(scenario["action"]["id"])
        consultation = read_consultation(scenario["consultation"]["id"])

        assert action["status"] == "REINITIATION_PENDING"
        assert action["reinitiation_reason"] == "SPECIES_UPLISTED"
        assert consultation["status"] == "REINITIATION_REQUIRED"
        assert consultation["reinitiation_count"] == 1
        assert_same_instant(
            consultation["reinitiation_triggered_at"], "2026-10-01T00:00:00Z"
        )

    def test_the_cascade_tail_reaches_the_proponent(self, api):
        """Hop four re-derives the proponent's open count and score.

        PRD: "each affected proponent has `open_reinitiation_count` re-derived, with
        `compliance_standing_score` re-derived on its next read."

        This proponent has filed no monitoring report at all, so no report period ends
        inside the window and the lifetime variant applies.

        Design: Difficulty/transitive_cascade/species_uplisting_cascade_four_hops_from_registry_write
        """
        scenario = self._uplist_the_threatened_species()

        proponent = read_proponent(scenario["proponent"]["id"])

        assert proponent["open_reinitiation_count"] == 1
        assert proponent["compliance_variant_applied"] == "LIFETIME"
        assert proponent["compliance_standing_score"] == 82.00

    def test_reinitiation_does_not_rewrite_the_issued_opinion(self, api):
        """The opinion keeps the ledger it was issued with.

        PRD: "Biological opinions are immutable and are discoverable only through the
        consultation's opinion list beyond the creation response itself."

        Design: Difficulty/transitive_cascade/species_uplisting_cascade_four_hops_from_registry_write
        """
        scenario = self._uplist_the_threatened_species()

        rows = assert_unpaginated_list(
            api.list_biological_opinions(scenario["consultation"]["id"], REVIEWER)
        )

        assert len(rows) == 1
        assert rows[0]["conclusion"] == scenario["opinion"]["conclusion"]
        assert rows[0]["authorized_take_units"] == 4.00

    def test_leaving_the_join_closes_plan_development(self, api):
        """The plan gate reads the action's current state, not its history.

        PRD: "Three gates apply. The action's `status` must be
        `CONSULTATION_CONCLUDED`."

        Design: Difficulty/transitive_cascade/species_uplisting_cascade_four_hops_from_registry_write
        """
        scenario = self._uplist_the_threatened_species()

        response = api.create_habitat_conservation_plan(
            scenario["action"]["id"],
            habitat_conservation_plan_payload(),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_a_lateral_listing_change_fires_no_hop(self, api):
        """Holding the rank writes three fields and nothing else.

        PRD: "Whether anything else happens depends entirely on the direction of travel
        on the rank ladder: **raising** the rank starts the uplisting cascade, while
        lowering it or holding it at the same rank starts nothing beyond those three
        field writes."

        Design: Difficulty/transitive_cascade/species_uplisting_cascade_four_hops_from_registry_write
        """
        scenario = self._uplist_the_threatened_species()

        again = get_success_data(
            api.change_species_listing(
                scenario["threatened_species"]["id"],
                listing_change_payload(new_listing_status="ENDANGERED"),
                REGISTRAR,
            ),
            200,
        )

        assert again["listing_change_count"] == 2
        assert read_consultation(scenario["consultation"]["id"])["reinitiation_count"] == 1


class TestPermitExpiryCascade:
    """A clock write closes the plan and releases commitments, sparing the bank."""

    def _permit_with_a_one_year_term(self):
        return build_scenario("permit", plan_overrides={"permit_term_years": 1})

    def test_the_term_end_and_the_bank_split_before_expiry(self, api):
        """A one-year term ends on the same month and day of the next year.

        PRD: "`term_end` is `term_start` with its year advanced by the plan's
        `permit_term_years`, keeping the same month and day".

        PRD: "every commitment in `RESERVED` moves `RESERVED - SECURED` in `created_at`
        ascending order, and for each such commitment whose `mechanism` is
        `CONSERVATION_BANK_CREDIT` the bank's `credits_reserved` decreases by `units`
        while its `credits_transferred` increases by the same `units`, preserving the
        ledger identity."

        Design: Difficulty/transitive_cascade/clock_advance_expiry_cascade_releases_commitments_without_bank_movement
        """
        scenario = self._permit_with_a_one_year_term()

        assert scenario["permit"]["term_end"] == "2027-10-01"
        assert scenario["permit"]["status"] == "ACTIVE"
        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_available"] == 440.28
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 59.72
        assert_bank_ledger_identity(bank)

    def test_repositioning_the_clock_expires_the_permit_and_closes_the_plan(self, api):
        """One day past the term runs all three hops.

        PRD: "When the logical clock is repositioned, every permit whose `status` is
        `ACTIVE` or `SUSPENDED` and whose `term_end` is earlier than the new clock value
        expires ... The permit moves to `EXPIRED` ... The parent plan then moves to the
        terminal `CLOSED` ... Finally every commitment on that plan whose `status` is
        `SECURED` moves `SECURED - RELEASED` in `created_at` ascending order".

        Design: Difficulty/transitive_cascade/clock_advance_expiry_cascade_releases_commitments_without_bank_movement
        """
        scenario = self._permit_with_a_one_year_term()

        set_clock("2027-10-02T00:00:00Z")

        assert read_permit(scenario["permit"]["id"])["status"] == "EXPIRED"
        assert read_plan(scenario["plan"]["id"])["plan_status"] == "CLOSED"
        rows = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(
                scenario["plan"]["id"], scenario["proponent_headers"]
            )
        )
        assert [row["status"] for row in rows] == ["RELEASED", "RELEASED"]
        assert [row["created_at"] for row in rows] == sorted(
            row["created_at"] for row in rows
        )

    def test_the_expiry_release_carries_no_bank_ledger_change(self, api):
        """Transferred credits stay transferred.

        PRD: "and here the release carries **no conservation bank ledger change
        whatsoever**. Credits already counted into `credits_transferred` stay there
        permanently; the land was bought and the obligation was discharged."

        Design: Difficulty/transitive_cascade/clock_advance_expiry_cascade_releases_commitments_without_bank_movement
        """
        scenario = self._permit_with_a_one_year_term()

        set_clock("2027-10-02T00:00:00Z")

        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_available"] == 440.28
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 59.72
        assert_bank_ledger_identity(bank)

    def test_expiry_is_not_a_reinitiation_and_stops_at_the_commitments(self, api):
        """The action keeps its permitted state and the money is left alone.

        PRD: "Each expiry runs a three-hop cascade."

        PRD: "a cascade either completes in full or, when a validation rejects the
        request, leaves every row exactly as it was - there are no partial cascades."

        Design: Difficulty/transitive_cascade/clock_advance_expiry_cascade_releases_commitments_without_bank_movement
        """
        scenario = self._permit_with_a_one_year_term()

        set_clock("2027-10-02T00:00:00Z")

        assert read_action(scenario["action"]["id"])["status"] == "PERMITTED"
        plan = read_plan(scenario["plan"]["id"])
        assert plan["endowment_required_cents"] == 5_026_514
        assert plan["endowment_secured_cents"] == 5_026_514

    def test_an_expired_permit_accepts_no_further_report(self, api):
        """The report gate reads the permit status.

        PRD: "Monitoring reports are the proponent's ongoing obligation and are filed
        against an `ACTIVE` permit only; a report aimed at a permit in `SUSPENDED` or
        `EXPIRED` is `ERR_PERMIT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/clock_advance_expiry_cascade_releases_commitments_without_bank_movement
        """
        scenario = self._permit_with_a_one_year_term()

        set_clock("2027-10-02T00:00:00Z")

        # The expiry cascade touches the permit, so its version moves with the
        # clock write; the guard is refreshed afterwards to keep rung 8 satisfied
        # and leave rung 10 as the rule under probe.
        version = read_permit(scenario["permit"]["id"])["version"]

        response = api.create_monitoring_report(
            scenario["permit"]["id"],
            monitoring_report_payload(version),
            scenario["proponent_headers"],
        )
        assert_error_envelope(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)

    def test_the_cascade_is_not_re_run_on_a_later_clock_write(self, api):
        """Only ACTIVE or SUSPENDED permits are eligible to expire.

        PRD: "every permit whose `status` is `ACTIVE` or `SUSPENDED` and whose `term_end`
        is earlier than the new clock value expires".

        PRD: "The parent plan then moves to the terminal `CLOSED`".

        Design: Difficulty/transitive_cascade/clock_advance_expiry_cascade_releases_commitments_without_bank_movement
        """
        scenario = self._permit_with_a_one_year_term()
        set_clock("2027-10-02T00:00:00Z")

        set_clock("2027-11-01T00:00:00Z")

        permit = read_permit(scenario["permit"]["id"])
        assert permit["status"] == "EXPIRED"
        assert permit["suspension_count"] == 0
        assert read_plan(scenario["plan"]["id"])["plan_status"] == "CLOSED"
