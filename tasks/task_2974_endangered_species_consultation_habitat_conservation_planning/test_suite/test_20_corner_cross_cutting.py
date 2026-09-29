"""The four cross-cutting layers and the one declared eventual-consistency surface.

Optimistic concurrency on both guarded writes, cascade all-or-nothing on the two
cascade-heaviest writes, the re-arming take threshold, and the two proponent
fields that move when nothing but the clock does.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_error_envelope,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    incidental_take_permit_payload,
    mitigation_commitment_payload,
    monitoring_report_payload,
    plan_decision_payload,
)
from test_helpers.fixtures import (
    APPROVER,
    AUDITOR,
    add_commitment,
    add_funding_assurance,
    adjudicate_report,
    build_scenario,
    file_monitoring_report,
    read_action,
    read_bank,
    read_consultation,
    read_permit,
    read_plan,
    read_proponent,
    set_clock,
    setup_canonical_permit,
)


class TestStaleHcpVersion:
    """The token is the plan's version, so any plan write invalidates it."""

    def test_a_funding_assurance_between_the_read_and_the_write_makes_the_token_stale(
        self, api
    ):
        """Two 412s, one from another commitment and one from a funding assurance.

        PRD: "If `expected_hcp_version` does not equal the plan's current `version`, the
        request is rejected with `ERR_STALE_HCP_VERSION` (HTTP 412) and **nothing** is
        written: no commitment row appears, no bank credit moves, no endowment aggregate
        changes."

        PRD: "On success the plan's `version` increases by 1, so a second commitment
        reusing the same `expected_hcp_version` value necessarily fails."

        PRD: "Adding a mitigation commitment to a plan - `POST
        /habitat-conservation-plans/{id}/mitigation-commitments` - requires a
        non-optional `expected_hcp_version` field carrying the `version` value the
        client last observed on that `HabitatConservationPlan`."

        The third attempt sends the same body with a freshly read version and is
        created, so the payload was never the problem; and the plan's version advances
        by exactly one per successful write and never on a refusal.

        Design: Corner/cross_cutting_complexity_layers/stale_expected_hcp_version_is_412_on_every_commitment_write
        """
        scenario = build_scenario("plan")
        plan_id = scenario["plan"]["id"]
        bank_id = scenario["bank"]["id"]
        headers = scenario["proponent_headers"]
        version_one = scenario["plan"]["version"]

        assert version_one == 1

        add_commitment(
            plan_id,
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 45.01,
                "conservation_bank_id": bank_id,
            },
        )
        after_first = read_plan(plan_id)

        assert after_first["version"] == 2
        assert after_first["endowment_required_cents"] == 3_788_402

        assert_error_envelope(
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    version_one, units=10.00, conservation_bank_id=bank_id
                ),
                headers,
            ),
            ApiErrorId.ERR_STALE_HCP_VERSION,
            412,
        )

        bank = read_bank(bank_id)
        untouched = read_plan(plan_id)

        assert bank["credits_reserved"] == 45.01
        assert bank["credits_available"] == 454.99
        assert bank["credits_transferred"] == 0.00
        assert_bank_ledger_identity(bank)
        assert untouched["endowment_required_cents"] == 3_788_402
        assert untouched["version"] == 2
        assert (
            len(
                assert_unpaginated_list(
                    api_client.list_plan_mitigation_commitments(plan_id, AUDITOR)
                )
            )
            == 1
        )

        # Exactly half of the 3,788,402-cent requirement, which is the inclusive
        # lower bound of the PARTIALLY_ASSURED band on exact integer cents.
        funded = add_funding_assurance(plan_id, scenario["proponent"], 1_894_201)
        after_funding = read_plan(plan_id)

        assert funded["funding_status"] == "PARTIALLY_ASSURED"
        assert after_funding["version"] == 3

        assert_error_envelope(
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    2, units=10.00, conservation_bank_id=bank_id
                ),
                headers,
            ),
            ApiErrorId.ERR_STALE_HCP_VERSION,
            412,
        )

        omitted = mitigation_commitment_payload(
            3, units=10.00, conservation_bank_id=bank_id
        )
        del omitted["expected_hcp_version"]
        assert_error_envelope(
            api_client.create_mitigation_commitment(plan_id, omitted, headers),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        accepted = get_success_data(
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    read_plan(plan_id)["version"],
                    units=10.00,
                    conservation_bank_id=bank_id,
                ),
                headers,
            ),
            201,
        )
        final = read_plan(plan_id)

        assert accepted["status"] == "RESERVED"
        assert accepted["units"] == 10.00
        assert final["version"] == 4


class TestStalePermitVersion:
    """The permit version moves without the caller doing anything at all."""

    def test_an_adjudication_by_the_agency_invalidates_the_clients_freshly_read_token(
        self, api
    ):
        """A rejection reverses take, bumps the permit, and strands a version read seconds earlier.

        PRD: "If `expected_permit_version` does not equal the permit's current
        `version`, the request is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412), no
        report row is created, and no take is applied to the ledger."

        PRD: "`REJECT` moves the report `SUBMITTED - REJECTED` and is a full
        compensation: the permit's `take_consumed_units` decreases by that report's
        `take_units_reported` and `take_remaining_units` is restored by the same amount,
        both rounded half up to two decimal places, and the report's half-open interval
        stops blocking new reports."

        PRD: "On an incidental take permit, `authorized_take_units` always equals
        `take_consumed_units` plus `take_remaining_units`."

        The second stale token was read straight from the server, so staleness is not a
        client bookkeeping error; and neither refusal reserves the interval, which the
        successful third attempt over the same dates proves.

        Design: Corner/cross_cutting_complexity_layers/stale_expected_permit_version_is_412_even_after_a_cascade_bump
        """
        scenario = setup_canonical_permit()
        permit_id = scenario["permit"]["id"]
        headers = scenario["proponent_headers"]
        version_one = scenario["permit"]["version"]
        set_clock("2027-05-16T00:00:00Z")
        first_report = file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-01-01",
            period_end="2027-04-01",
            take_units_reported=0.50,
            mitigation_units_verified=59.72,
        )

        assert version_one == 1
        assert first_report["status"] == "SUBMITTED"

        def refile(expected_version):
            return api_client.create_monitoring_report(
                permit_id,
                monitoring_report_payload(
                    expected_version,
                    period_start="2027-04-01",
                    period_end="2027-05-01",
                    take_units_reported=0.25,
                    mitigation_units_verified=59.72,
                ),
                headers,
            )

        assert_error_envelope(
            refile(version_one), ApiErrorId.ERR_STALE_PERMIT_VERSION, 412
        )

        after_first = read_permit(permit_id)

        assert after_first["version"] == 2
        assert after_first["take_consumed_units"] == 0.50
        assert (
            after_first["authorized_take_units"]
            == after_first["take_consumed_units"] + after_first["take_remaining_units"]
        )

        adjudicate_report(
            first_report["id"], "REJECT", note="Survey methodology not acceptable."
        )
        after_reject = read_permit(permit_id)

        assert after_reject["take_consumed_units"] == 0.00
        assert after_reject["version"] == 3
        assert after_reject["version"] != after_first["version"]
        assert (
            after_reject["authorized_take_units"]
            == after_reject["take_consumed_units"]
            + after_reject["take_remaining_units"]
        )

        assert_error_envelope(
            refile(after_first["version"]), ApiErrorId.ERR_STALE_PERMIT_VERSION, 412
        )

        before_success = assert_unpaginated_list(
            api_client.list_permit_monitoring_reports(permit_id, AUDITOR)
        )

        assert len(before_success) == 1
        assert before_success[0]["status"] == "REJECTED"

        created = get_success_data(refile(after_reject["version"]), 201)
        final = read_permit(permit_id)
        rows = assert_unpaginated_list(
            api_client.list_permit_monitoring_reports(permit_id, AUDITOR)
        )

        assert created["period_start"] == "2027-04-01"
        assert created["period_end"] == "2027-05-01"
        assert created["status"] == "SUBMITTED"
        assert final["version"] == 4
        assert final["take_consumed_units"] == 0.25
        assert (
            final["authorized_take_units"]
            == final["take_consumed_units"] + final["take_remaining_units"]
        )
        assert len(rows) == 2


class TestRefusedCascadeLeavesNothingBehind:
    """The two cascade-heaviest writes are all-or-nothing at their own rung."""

    def test_a_refused_approval_and_a_refused_issuance_move_no_downstream_row(self, api):
        """The funding gate and the segregation rule each abort a multi-hop cascade whole.

        PRD: "a cascade either completes in full or, when a validation rejects the
        request, leaves every row exactly as it was - there are no partial cascades"

        PRD: "The official's `X-User-ID` must differ from the plan's
        `approved_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD: "The permit is created in `status` `ACTIVE`, the plan moves `APPROVED -
        IMPLEMENTING`, and the action moves `HCP_DEVELOPMENT - PERMITTED`."

        The same APPROVE body succeeds once the shortfall is contributed, and only then
        do the commitments become `SECURED` and the credits move from reserved to
        transferred; the refused issuance leaves the plan `APPROVED` rather than
        `IMPLEMENTING` and the action short of `PERMITTED`, with no abandoned permit row.

        Design: Corner/cross_cutting_complexity_layers/a_refused_cascade_trigger_leaves_every_downstream_row_untouched
        """
        # Exactly half of the 5,026,514-cent requirement, which is the inclusive
        # lower bound of the PARTIALLY_ASSURED band on exact integer cents.
        scenario = build_scenario("submitted", funding_cents=2_513_257)
        plan_id = scenario["plan"]["id"]
        bank_id = scenario["bank"]["id"]
        action_id = scenario["action"]["id"]
        version_before = scenario["plan"]["version"]

        assert scenario["plan"]["plan_status"] == "SUBMITTED"
        assert scenario["plan"]["funding_status"] == "PARTIALLY_ASSURED"
        assert scenario["plan"]["endowment_required_cents"] == 5_026_514
        assert read_action(action_id)["status"] == "HCP_DEVELOPMENT"

        assert_error_envelope(
            api_client.decide_plan(plan_id, plan_decision_payload("APPROVE"), APPROVER),
            ApiErrorId.ERR_FUNDING_NOT_ASSURED,
            422,
        )

        bank = read_bank(bank_id)
        commitments = assert_unpaginated_list(
            api_client.list_plan_mitigation_commitments(plan_id, AUDITOR)
        )
        refused = read_plan(plan_id)

        assert [row["status"] for row in commitments] == ["RESERVED", "RESERVED"]
        assert bank["credits_reserved"] == 59.72
        assert bank["credits_transferred"] == 0.00
        assert bank["credits_available"] == 440.28
        assert_bank_ledger_identity(bank)
        assert refused["plan_status"] == "SUBMITTED"
        assert refused["approved_by_user_id"] is None
        assert refused["version"] == version_before

        topped_up = add_funding_assurance(plan_id, scenario["proponent"], 2_513_257)

        assert topped_up["funding_status"] == "FULLY_ASSURED"
        assert topped_up["endowment_secured_cents"] == 5_026_514

        approved = get_success_data(
            api_client.decide_plan(plan_id, plan_decision_payload("APPROVE"), APPROVER),
            200,
        )
        secured = assert_unpaginated_list(
            api_client.list_plan_mitigation_commitments(plan_id, AUDITOR)
        )
        bank_after = read_bank(bank_id)

        assert approved["plan_status"] == "APPROVED"
        assert [row["status"] for row in secured] == ["SECURED", "SECURED"]
        assert bank_after["credits_transferred"] == 59.72
        assert bank_after["credits_reserved"] == 0.00
        assert bank_after["credits_available"] == 440.28
        assert_bank_ledger_identity(bank_after)

        assert_error_envelope(
            api_client.issue_incidental_take_permit(
                plan_id, incidental_take_permit_payload(), APPROVER
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        stalled = read_plan(plan_id)
        action = read_action(action_id)
        permits = assert_unpaginated_list(
            api_client.list_plan_incidental_take_permits(plan_id, AUDITOR)
        )

        assert stalled["plan_status"] == "APPROVED"
        assert stalled["version"] == approved["version"]
        assert action["status"] == "HCP_DEVELOPMENT"
        assert action["status"] != "PERMITTED"
        assert permits == []


class TestTakeThresholdReArms:
    """Cumulative rather than per-report, and it fires again after an unwind."""

    def test_one_hundredth_fires_the_cascade_twice_while_the_consultation_counts_once(
        self, api
    ):
        """3.59 does not fire, 0.01 does, a rejection unwinds two hops of four, and 0.01 fires again.

        PRD: "When `take_consumed_units` is at or above `reinitiation_trigger_units` -
        the boundary is inclusive, so exact equality suspends the permit - and the permit
        is `ACTIVE`, the take-exceedance cascade fires in five hops."

        PRD: "If the reversal brings `take_consumed_units` **strictly below**
        `reinitiation_trigger_units` while the permit is `SUSPENDED`, the cascade unwinds:
        the permit moves `SUSPENDED - ACTIVE` and the plan moves
        `SUSPENDED_IMPLEMENTATION - IMPLEMENTING` with `assurance_review_required` set
        back to false."

        PRD: "Hop five reaches the consultation named by the action's
        `active_consultation_id`: if and only if its `status` is `OPINION_ISSUED`, it
        moves `OPINION_ISSUED - REINITIATION_REQUIRED`, stamping
        `reinitiation_triggered_at` and increasing `reinitiation_count` by 1, after which
        the owning proponent's `open_reinitiation_count` increases by 1 and its
        `compliance_standing_score` is recomputed."

        The unwind is asymmetric - the permit and the plan come back, the action and the
        consultation do not - so the second firing lifts `suspension_count` to 2 while
        `reinitiation_count` stays at 1 for want of a source state to leave.

        Design: Corner/cross_cutting_complexity_layers/the_take_threshold_re_arms_after_a_rejection_and_fires_a_second_time
        """
        scenario = setup_canonical_permit()
        permit_id = scenario["permit"]["id"]
        plan_id = scenario["plan"]["id"]
        action_id = scenario["action"]["id"]
        consultation_id = scenario["consultation"]["id"]
        proponent_id = scenario["proponent"]["id"]
        set_clock("2027-05-16T00:00:00Z")

        assert scenario["permit"]["authorized_take_units"] == 4.00
        assert scenario["permit"]["reinitiation_trigger_units"] == 3.60
        assert scenario["permit"]["suspension_count"] == 0

        def assert_take_identity(permit):
            assert (
                permit["authorized_take_units"]
                == permit["take_consumed_units"] + permit["take_remaining_units"]
            )

        file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-01-01",
            period_end="2027-02-01",
            take_units_reported=3.59,
            mitigation_units_verified=59.72,
        )
        after_first = read_permit(permit_id)

        assert after_first["status"] == "ACTIVE"
        assert after_first["take_consumed_units"] == 3.59
        assert after_first["suspension_count"] == 0
        assert_take_identity(after_first)

        second_report = file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-02-01",
            period_end="2027-03-01",
            take_units_reported=0.01,
            mitigation_units_verified=59.72,
        )
        fired = read_permit(permit_id)
        plan_fired = read_plan(plan_id)
        action_fired = read_action(action_id)
        consultation_fired = read_consultation(consultation_id)
        proponent_fired = read_proponent(proponent_id)

        assert fired["take_consumed_units"] == 3.60
        assert fired["status"] == "SUSPENDED"
        assert fired["suspension_count"] == 1
        assert_take_identity(fired)
        assert plan_fired["plan_status"] == "SUSPENDED_IMPLEMENTATION"
        assert plan_fired["assurance_review_required"] is True
        assert action_fired["status"] == "REINITIATION_PENDING"
        assert action_fired["reinitiation_reason"] == "TAKE_EXCEEDANCE"
        assert consultation_fired["status"] == "REINITIATION_REQUIRED"
        assert consultation_fired["reinitiation_count"] == 1
        assert proponent_fired["open_reinitiation_count"] == 1

        adjudicate_report(
            second_report["id"],
            "REJECT",
            note="Take tally not supported by the survey record.",
        )
        unwound = read_permit(permit_id)
        plan_unwound = read_plan(plan_id)
        action_unwound = read_action(action_id)
        consultation_unwound = read_consultation(consultation_id)

        assert unwound["take_consumed_units"] == 3.59
        assert unwound["status"] == "ACTIVE"
        assert unwound["suspension_count"] == 1
        assert_take_identity(unwound)
        assert plan_unwound["plan_status"] == "IMPLEMENTING"
        assert plan_unwound["assurance_review_required"] is False
        assert action_unwound["status"] == "REINITIATION_PENDING"
        assert consultation_unwound["status"] == "REINITIATION_REQUIRED"
        assert consultation_unwound["reinitiation_count"] == 1

        file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-03-01",
            period_end="2027-04-01",
            take_units_reported=0.01,
            mitigation_units_verified=59.72,
        )
        refired = read_permit(permit_id)
        consultation_refired = read_consultation(consultation_id)

        assert refired["take_consumed_units"] == 3.60
        assert refired["status"] == "SUSPENDED"
        assert refired["suspension_count"] == 2
        assert_take_identity(refired)
        assert consultation_refired["status"] == "REINITIATION_REQUIRED"
        assert consultation_refired["reinitiation_count"] == 1


class TestEventualConsistencySurface:
    """Exactly two fields on one resource move with the clock; nothing else does."""

    def test_the_score_changes_with_no_intervening_write_while_every_ledger_holds_still(
        self, api
    ):
        """One halving step at 181 days, a variant flip at 366, and no drift anywhere else.

        PRD: "Two fields are the deliberate exception: a proponent's
        `compliance_standing_score` and `compliance_variant_applied` are clock-dependent,
        and are re-derived - and persisted - on **every read** of that proponent
        resource, against the logical clock as it stands at that moment."

        PRD: "The consequence is that the same proponent row can return different values
        at two different clock positions with no intervening write of any kind."

        PRD: "An event older than 180 whole days carries **half** its weight; an event
        exactly 180 whole days old carries its **full** weight, because the comparison is
        strictly greater than."

        PRD: "A monitoring report that reached `REJECTED` contributes a weight of 11,
        dated at the report's `adjudicated_at`."

        PRD: "Almost every derived field in this system is reconciled immediately, inside
        the request that changes its inputs."

        The reader's role is irrelevant - the auditor, which can write nothing at all,
        sees the identical re-derived pair - and the two fields move independently: the
        last clock move flips the variant to `LIFETIME` without moving the score.

        Design: Corner/consistency_model/two_compliance_fields_lag_the_clock_while_every_other_derived_field_is_immediate
        """
        scenario = setup_canonical_permit()
        plan_id = scenario["plan"]["id"]
        bank_id = scenario["bank"]["id"]
        proponent_id = scenario["proponent"]["id"]
        set_clock("2027-05-16T00:00:00Z")
        report = file_monitoring_report(
            scenario["permit"]["id"],
            scenario["proponent"],
            period_start="2027-01-01",
            period_end="2027-04-01",
            take_units_reported=0.50,
            mitigation_units_verified=59.72,
        )
        rejected = adjudicate_report(
            report["id"], "REJECT", note="Survey effort insufficient for the period."
        )

        assert rejected["status"] == "REJECTED"
        assert rejected["adjudicated_at"].startswith("2027-05-16T00:00:00")

        plan_a = read_plan(plan_id)
        bank_a = read_bank(bank_id)

        assert plan_a["endowment_required_cents"] == 5_026_514
        assert plan_a["reserve_remaining_cents"] == 538_555
        assert bank_a["credits_transferred"] == 59.72
        assert bank_a["credits_available"] == 440.28

        first = read_proponent(proponent_id)
        again = read_proponent(proponent_id)

        assert first["compliance_standing_score"] == 89.00
        assert first["compliance_variant_applied"] == "ROLLING_12_MONTH"
        assert again["compliance_standing_score"] == first["compliance_standing_score"]
        assert again["compliance_variant_applied"] == first["compliance_variant_applied"]

        set_clock("2027-11-12T00:00:00Z")
        at_one_eighty = read_proponent(proponent_id)

        assert at_one_eighty["compliance_standing_score"] == 89.00
        assert at_one_eighty["compliance_variant_applied"] == "ROLLING_12_MONTH"

        set_clock("2027-11-13T00:00:00Z")
        at_one_eighty_one = read_proponent(proponent_id)
        auditor_view = read_proponent(proponent_id, AUDITOR)

        assert at_one_eighty_one["compliance_standing_score"] == 94.50
        assert at_one_eighty_one["compliance_variant_applied"] == "ROLLING_12_MONTH"
        assert auditor_view["compliance_standing_score"] == 94.50
        assert auditor_view["compliance_variant_applied"] == "ROLLING_12_MONTH"

        plan_b = read_plan(plan_id)
        bank_b = read_bank(bank_id)

        assert plan_b["endowment_required_cents"] == plan_a["endowment_required_cents"]
        assert plan_b["reserve_remaining_cents"] == plan_a["reserve_remaining_cents"]
        assert plan_b["version"] == plan_a["version"]
        assert bank_b["credits_transferred"] == bank_a["credits_transferred"]
        assert bank_b["credits_available"] == bank_a["credits_available"]
        assert_bank_ledger_identity(bank_b)

        set_clock("2028-04-02T00:00:00Z")
        after_window = read_proponent(proponent_id)

        assert after_window["compliance_variant_applied"] == "LIFETIME"
        assert after_window["compliance_standing_score"] == 94.50
