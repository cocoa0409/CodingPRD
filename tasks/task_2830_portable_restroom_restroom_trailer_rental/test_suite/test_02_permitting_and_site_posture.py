"""Permit filings, the revision cycle, expiry and the site-posture roll-up."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_instants_equal,
    assert_placement_permit,
    assert_route_density,
    assert_site_gate,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
COORDINATOR = TEST_USERS["permit_coordinator_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestFilingLifecycle:
    """The declared from-states of the filing state machine."""

    def test_01_a_drafted_filing_lands_in_draft_with_no_revision_history(self):
        """Creation lands on DRAFT with revision_round 0 and both audit fields null.

        PRD 3.2: "A drafted filing lands in `status` `DRAFT` with `revision_round`
        of 0, `rejection_reason` null and `submitted_by_user_id` null"
        PRD 2.5: "a `DRAFT` filing and a `SUBMITTED` filing both contribute
        `PENDING`"

        Design: Corner/state_machines/newly_created_placement_permit_starts_in_draft_with_revision_round_zero
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Foxglove Municipal", account_type="MUNICIPAL", credit_terms_days=45
        )
        site = fx.register_site(
            account["id"],
            "Foxglove Commons",
            jurisdiction_code="MN-HE-CITY",
            access_class="GATED",
            gate_open_minute=480,
            gate_close_minute=1020,
        )

        permit = validate_success(
            api_client.create_placement_permit(
                {
                    "site_id": site["id"],
                    "permit_kind": "PLACEMENT",
                    "authority_ref": "PL-9401",
                    "effective_from": "2026-08-01",
                    "effective_to": "2026-11-30",
                },
                COORDINATOR,
            ),
            201,
        )

        assert_placement_permit(permit)
        assert permit["status"] == "DRAFT", (
            f"a drafted filing lands in DRAFT, got {permit['status']}"
        )
        assert permit["revision_round"] == 0, (
            f"a drafted filing has revision_round 0, got {permit['revision_round']}"
        )
        assert permit["rejection_reason"] is None
        assert permit["submitted_by_user_id"] is None

        assert_site_gate(
            fx.read_site(site["id"]), permit_status="PENDING",
            site_posture="RESTRICTED",
        )

    def test_02_approving_a_filing_still_in_draft_is_refused(self):
        """approve is declared only from SUBMITTED, so a DRAFT row refuses it.

        PRD 3.2: "Approval advances `SUBMITTED → APPROVED` and requires an
        `authority_decision_ref` in the payload; it is permitted only while the
        logical clock's current calendar date is on or before the filing's
        `effective_to`, so a filing whose window has already elapsed cannot be
        approved into usefulness."
        PRD 2.11: "State-machine legality: the target row is in a state from which
        the requested transition is declared, and every same-entity or
        guard-entity state precondition of that transition holds —
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/approving_a_permit_still_in_draft_is_refused
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Sable Ridge Events", account_type="EVENT", credit_terms_days=15
        )
        site = fx.register_site(
            account["id"], "Sable Ridge Lawn", jurisdiction_code="CO-DE-CITY",
            access_class="OPEN_LOT",
        )
        permit = fx.file_permit(
            site["id"], "PL-9301", effective_from="2026-08-01",
            effective_to="2026-12-31",
        )
        assert permit["status"] == "DRAFT"

        validate_error(
            api_client.approve_placement_permit(
                permit["id"], {"authority_decision_ref": "AD-9301"}, OFFICER
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        after = fx.read_permit(permit["id"])
        assert after["status"] == "DRAFT", (
            f"the refused approval must write nothing, got {after['status']}"
        )
        assert after["revision_round"] == 0
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="PENDING",
            site_posture="RESTRICTED",
        )

    def test_03_approving_an_already_approved_filing_a_second_time_is_refused(self):
        """The approve action is not idempotent and leaves the row untouched.

        PRD 3.2: "Deciding a filing belongs to the `ComplianceOfficer`, never to
        the coordinator who filed it."
        PRD 2.11: "State-machine legality: the target row is in a state from which
        the requested transition is declared, and every same-entity or
        guard-entity state precondition of that transition holds —
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/approving_an_already_approved_permit_a_second_time_is_rejected
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Marigold Municipal", account_type="MUNICIPAL", credit_terms_days=30
        )
        site = fx.register_site(
            account["id"], "Marigold Depot", jurisdiction_code="WI-DA-CITY",
            access_class="OPEN_LOT",
        )
        permit = fx.file_permit(
            site["id"], "PL-9601", effective_from="2026-08-01",
            effective_to="2026-12-31",
        )
        fx.submit_permit(permit["id"])
        approved = fx.approve_permit(permit["id"], "AD-FIRST")
        assert approved["status"] == "APPROVED"
        assert approved["revision_round"] == 1
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="APPROVED", site_posture="OPEN"
        )

        validate_error(
            api_client.approve_placement_permit(
                permit["id"], {"authority_decision_ref": "AD-SECOND"}, OFFICER
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        replayed = fx.read_permit(permit["id"])
        assert replayed["status"] == "APPROVED"
        assert replayed["revision_round"] == approved["revision_round"], (
            "a refused transition must not bump the revision round"
        )
        assert replayed["version"] == approved["version"], (
            "a refused transition must not bump the version"
        )
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="APPROVED", site_posture="OPEN"
        )

    def test_04_an_expired_filing_can_never_be_refiled(self):
        """The clock sweep expires the filing and locks it out of the refile path.

        PRD 3.2: "When a `PlatformAdmin` repositions the logical clock (§2.4), the
        service sweeps every filing in `APPROVED` whose `effective_to` falls
        strictly before the new calendar date and transitions it `APPROVED →
        EXPIRED`, processing filings in `created_at` ascending order."
        PRD 3.2: "`EXPIRED` is a terminal state — an expired filing is never
        revived, only superseded by a newer filing of the same kind."
        PRD 2.4: "The response reports the new `current_utc` together with three
        counters describing the sweep that repositioning triggered:
        `expired_permit_count`, `blocked_site_count` and
        `suspended_schedule_count`."

        Design: Corner/state_machines/resubmitting_an_expired_permit_is_refused_by_terminal_state_lockdown
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Juniper Fairgrounds", account_type="EVENT", credit_terms_days=15
        )
        site = fx.register_site(
            account["id"],
            "Juniper Infield",
            jurisdiction_code="AZ-MA-CITY",
            access_class="OPEN_LOT",
            right_of_way_required=False,
            gate_open_minute=360,
            gate_close_minute=1200,
            max_truck_length_ft=40,
        )
        permit = fx.file_permit(
            site["id"], "PL-9501", effective_from="2026-08-01",
            effective_to="2026-08-05",
        )
        fx.submit_permit(permit["id"])
        approved = fx.approve_permit(permit["id"], "AD-9501")
        assert approved["status"] == "APPROVED"
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="APPROVED", site_posture="OPEN"
        )

        sweep = fx.reposition_clock("2026-08-06T00:00:00Z")
        assert_instants_equal(
            sweep["current_utc"], "2026-08-06T00:00:00.000Z", "current_utc"
        )
        assert sweep["expired_permit_count"] == 1, (
            "one APPROVED filing lapsed, the sweep reports "
            f"{sweep['expired_permit_count']}"
        )
        assert sweep["blocked_site_count"] == 1, (
            f"one site became blocked, the sweep reports {sweep['blocked_site_count']}"
        )
        assert sweep["suspended_schedule_count"] == 0, (
            "no schedule exists to suspend, the sweep reports "
            f"{sweep['suspended_schedule_count']}"
        )

        expired = fx.read_permit(permit["id"])
        assert expired["status"] == "EXPIRED", (
            "2026-08-06 falls strictly after effective_to 2026-08-05, so the "
            f"filing must be EXPIRED, got {expired['status']}"
        )
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="EXPIRED", site_posture="BLOCKED"
        )

        validate_error(
            api_client.submit_placement_permit(
                permit["id"], COORDINATOR, {"submission_note": "please renew"}
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        locked = fx.read_permit(permit["id"])
        assert locked["status"] == "EXPIRED"
        assert locked["revision_round"] == 1, (
            "the refused refile leaves revision_round at 1, got "
            f"{locked['revision_round']}"
        )


class TestPostureRollUp:
    """The worst-of roll-up over the kinds a site requires."""

    def test_05_a_right_of_way_site_stays_restricted_until_both_kinds_approve(self):
        """The missing kind contributes NONE and dominates the approved one.

        PRD 2.5: "Every site requires a `PLACEMENT` permit."
        PRD 2.5: "A site whose `right_of_way_required` flag is true additionally
        requires a `RIGHT_OF_WAY` permit; a site whose flag is false requires only
        the placement kind."
        PRD 2.5: "If no filing of a required kind exists at all, that kind
        contributes `NONE`."
        PRD 2.5: "The site's `permit_status` is then the worst of those per-kind
        contributions, where "worst" is fixed by this precedence list read from the
        front: `REJECTED` is worst, then `EXPIRED`, then `NONE`, then `PENDING`,
        and `APPROVED` is best."
        PRD 2.5: "A `RESTRICTED` governing site rejects three of those four —
        contract mobilization, deployment creation and visit planning — with
        `ERR_SITE_POSTURE_RESTRICTED` (HTTP 409); relocation is deliberately
        exempt, because moving a unit onto a merely restricted site is how the
        field recovers from a tip-over."

        Design: Corner/calculations/site_posture_propagates_the_worst_of_every_required_permit_kind
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Hollyhock Streetworks", account_type="MUNICIPAL", credit_terms_days=45
        )
        site = fx.register_site(
            account["id"],
            "Hollyhock Median",
            jurisdiction_code="OR-MU-CITY",
            access_class="OPEN_LOT",
            right_of_way_required=True,
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        placement = fx.file_permit(
            site["id"], "PL-10501", effective_from="2026-08-01",
            effective_to="2026-12-31",
        )
        fx.submit_permit(placement["id"])
        fx.approve_permit(placement["id"], "AD-10501")
        contract = fx.quote_contract(fx.raise_contract(account["id"], site["id"]))
        assert contract["quoted_cents"] == 91500

        assert_site_gate(
            fx.read_site(site["id"]), permit_status="NONE",
            site_posture="RESTRICTED",
        )
        validate_error(
            api_client.activate_rental_contract(contract["id"], SALES),
            "ERR_SITE_POSTURE_RESTRICTED",
            409,
        )

        right_of_way = fx.file_permit(
            site["id"], "RW-10501", permit_kind="RIGHT_OF_WAY",
            effective_from="2026-08-01", effective_to="2026-12-31",
        )
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="PENDING",
            site_posture="RESTRICTED",
        )

        fx.submit_permit(right_of_way["id"])
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="PENDING",
            site_posture="RESTRICTED",
        )

        fx.approve_permit(right_of_way["id"], "AD-RW-10501")
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="APPROVED", site_posture="OPEN"
        )

        activated = validate_success(
            api_client.activate_rental_contract(contract["id"], SALES)
        )
        assert activated["fulfillment_state"] == "ACTIVE", (
            "the identical activate call must succeed once the roll-up reaches "
            f"APPROVED, got {activated['fulfillment_state']}"
        )


def _marston_rejected_filing():
    """Site whose only PLACEMENT filing has been submitted once and rejected."""
    fx.reposition_clock("2026-08-03T08:00:00Z")
    account = fx.open_account(
        "City of Marston Parks", account_type="MUNICIPAL", credit_terms_days=45
    )
    site = fx.register_site(
        account["id"],
        "Marston Fairgrounds",
        jurisdiction_code="OR-MA-CITY",
        access_class="GATED",
        right_of_way_required=False,
        gate_open_minute=420,
        gate_close_minute=1140,
        max_truck_length_ft=32,
    )
    permit = fx.file_permit(
        site["id"], "PL-6001", effective_from="2026-08-01",
        effective_to="2026-11-30",
    )
    assert permit["revision_round"] == 0
    round_one = fx.submit_permit(permit["id"], "round 1")
    assert round_one["revision_round"] == 1
    fx.reject_permit(permit["id"], "AD-6001", "site plan missing ADA path")
    return account, site, permit


class TestRevisionCycle:
    """REJECTED → SUBMITTED is a genuine cycle, capped at three rounds."""

    def test_06_refiling_a_rejected_permit_re_enters_submitted_and_counts_rounds(self):
        """Each refile increments revision_round and re-enters SUBMITTED.

        PRD 3.2: "Each submission increments `revision_round` by one — so a first
        submission moves it from 0 to 1 — and stamps `submitted_by_user_id` with
        the acting `X-User-ID`."
        PRD 3.2: "`REJECTED → SUBMITTED` is a genuine cycle: the same submit
        action re-files a rejected permit, incrementing `revision_round` again and
        re-stamping `submitted_by_user_id`, and the recomputation pulls the site
        out of `BLOCKED` back to `RESTRICTED` for as long as the new filing is
        pending."
        PRD 3.2: "The text of the previous round's rejection is retained in
        `rejection_reason` across the resubmission — it is not cleared."

        Design: Difficulty/non_linear_state_machine/permit_reject_resubmit_cycle_increments_revision_round_to_limit
        """
        account, site, permit = _marston_rejected_filing()
        rejected = fx.read_permit(permit["id"])
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "site plan missing ADA path"
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="REJECTED",
            site_posture="BLOCKED",
        )

        round_two = fx.submit_permit(permit["id"], "round 2")
        assert round_two["revision_round"] == 2, (
            f"the second submission moves the round to 2, got {round_two['revision_round']}"
        )
        assert round_two["status"] == "SUBMITTED", (
            "REJECTED → SUBMITTED re-enters a state the row had already left, got "
            f"{round_two['status']}"
        )
        assert round_two["rejection_reason"] == "site plan missing ADA path", (
            "the previous round's rejection text is retained across the refile, got "
            f"{round_two['rejection_reason']!r}"
        )
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="PENDING",
            site_posture="RESTRICTED",
        )

        fx.reject_permit(permit["id"], "AD-6002", "encroachment into travel lane")
        round_three = fx.submit_permit(permit["id"], "round 3")
        assert round_three["revision_round"] == 3, (
            f"the third submission moves the round to 3, got {round_three['revision_round']}"
        )
        assert round_three["status"] == "SUBMITTED"

    def test_07_a_fourth_submission_is_refused_at_the_revision_ceiling(self):
        """Once revision_round reaches three the authority entertains no more.

        PRD 3.2: "The cycle is capped: a resubmission is permitted only while
        `revision_round` is strictly less than three, so the third round of
        revisions is the last one the authority will entertain and a further
        resubmission is rejected with `ERR_PERMIT_REVISION_LIMIT` (HTTP 409)."
        PRD 3.2: "Note that the blocked posture of a site never prevents a
        refiling — a coordinator may always refile against a site that its own
        rejection blocked, which is the entire point of the loop."

        Design: Difficulty/non_linear_state_machine/permit_reject_resubmit_cycle_increments_revision_round_to_limit
        """
        account, site, permit = _marston_rejected_filing()
        fx.submit_permit(permit["id"], "round 2")
        fx.reject_permit(permit["id"], "AD-6002", "encroachment into travel lane")
        fx.submit_permit(permit["id"], "round 3")
        fx.reject_permit(permit["id"], "AD-6003", "still non-compliant")

        validate_error(
            api_client.submit_placement_permit(
                permit["id"], COORDINATOR, {"submission_note": "round 4"}
            ),
            "ERR_PERMIT_REVISION_LIMIT",
            409,
        )

        final = fx.read_permit(permit["id"])
        assert final["revision_round"] == 3, (
            f"the refused submit must not increment the round, got {final['revision_round']}"
        )
        assert final["status"] == "REJECTED"
        assert final["rejection_reason"] == "still non-compliant"
        assert_site_gate(
            fx.read_site(site["id"]), permit_status="REJECTED",
            site_posture="BLOCKED",
        )


def _harborline_environment():
    """An OPEN site carrying one ACTIVE schedule, one PLANNED future visit and a
    second, later PLACEMENT filing sitting in SUBMITTED."""
    fx.reposition_clock("2026-08-03T08:00:00Z")
    account = fx.open_account(
        "Harborline Civil", account_type="CONSTRUCTION", credit_terms_days=30
    )
    site = fx.register_site(
        account["id"],
        "Harborline Pier 4",
        jurisdiction_code="WA-TA-CITY",
        access_class="OPEN_LOT",
        right_of_way_required=False,
        gate_open_minute=360,
        gate_close_minute=1080,
        max_truck_length_ft=40,
    )
    permit_one = fx.file_permit(
        site["id"], "PL-7101", effective_from="2026-08-01",
        effective_to="2026-12-31",
    )
    fx.submit_permit(permit_one["id"])
    fx.approve_permit(permit_one["id"], "AD-7101")
    assert_site_gate(
        fx.read_site(site["id"]), permit_status="APPROVED", site_posture="OPEN"
    )

    route = fx.create_route("RT-MON-21", truck_capacity_units=20)
    contract = fx.quote_contract(
        fx.raise_thirteen_unit_contract(account["id"], site["id"])
    )
    schedule = fx.attach_schedule(contract["id"], route["id"], "MON", 480, 600)
    assert schedule["state"] == "ACTIVE"
    visit = fx.plan_visit(schedule["id"], "2026-08-17", 480, 540)
    assert visit["state"] == "PLANNED"
    assert_route_density(
        fx.read_route(route["id"]), committed_units=13, density_planned_pct=65
    )

    permit_two = fx.file_permit(
        site["id"], "PL-7102", effective_from="2026-08-15",
        effective_to="2026-12-31",
    )
    fx.submit_permit(permit_two["id"], "renewal filing")
    return {
        "account": account, "site": site, "permit_one": permit_one,
        "permit_two": permit_two, "route": route, "contract": contract,
        "schedule": schedule, "visit": visit,
    }


class TestRejectionCascade:
    """A rejection blocks the site, and the block suspends everything below it."""

    def test_08_rejecting_the_latest_filing_blocks_the_site_and_suspends_schedules(
        self,
    ):
        """The newest filing of a kind wins outright, and BLOCKED suspends schedules.

        PRD 2.5: "For each required kind, the service considers all permit filings
        of that kind on the site and selects the single latest one by `created_at`
        descending — the newest filing of a kind wins outright, and older filings
        of the same kind are ignored entirely."
        PRD 3.2: "First, the site's `permit_status` and `site_posture` are
        recomputed. The worst-of roll-up now yields `REJECTED`, so `site_posture`
        becomes `BLOCKED`."
        PRD 3.2: "Second — caused by the posture becoming `BLOCKED`, not by the
        rejection itself — every service schedule whose contract sits on that site
        and whose `state` is `ACTIVE` transitions `ACTIVE → SUSPENDED`, processed
        in `created_at` ascending order."

        Design: Difficulty/transitive_cascade/permit_reject_cascades_site_posture_schedule_route_density_and_visit
        """
        env = _harborline_environment()

        rejected = fx.reject_permit(
            env["permit_two"]["id"], "AD-7102", "encroachment on the pier apron"
        )
        assert rejected["status"] == "REJECTED"

        assert_site_gate(
            fx.read_site(env["site"]["id"]), permit_status="REJECTED",
            site_posture="BLOCKED",
        )
        assert fx.read_schedule(env["schedule"]["id"])["state"] == "SUSPENDED", (
            "the schedule must be suspended by the posture becoming BLOCKED"
        )
        assert fx.read_permit(env["permit_one"]["id"])["status"] == "APPROVED", (
            "the cascade must never touch the older, still-approved filing"
        )

    def test_09_the_suspension_releases_route_capacity_and_cancels_future_visits(self):
        """Route figures fall to zero, the future visit cancels, and no money moves.

        PRD 3.2: "Third — caused by each schedule leaving `ACTIVE` —
        `committed_units` is recomputed for each affected route and then
        `density_planned_pct` is recomputed from it, exactly as described in §3.5."
        PRD 3.2: "Fourth — caused by the same schedule suspensions — every service
        visit on those schedules whose `state` is `PLANNED` and whose
        `scheduled_date` is on or after the logical clock's current calendar date
        transitions `PLANNED → CANCELLED`, processed in `created_at` ascending
        order."
        PRD 3.2: "Visits already in the past are left alone, and cancellation is
        not a missed service: no credit is created."

        Design: Difficulty/transitive_cascade/permit_reject_cascades_site_posture_schedule_route_density_and_visit
        """
        env = _harborline_environment()

        fx.reject_permit(
            env["permit_two"]["id"], "AD-7102", "encroachment on the pier apron"
        )

        assert_route_density(
            fx.read_route(env["route"]["id"]),
            committed_units=0,
            density_planned_pct=0,
        )
        assert fx.read_visit(env["visit"]["id"])["state"] == "CANCELLED", (
            "the visit on 2026-08-17 falls on or after the clock date 2026-08-03 "
            "and must be cancelled"
        )

        charges, charge_meta = validate_paginated(
            api_client.list_charge_events(
                OFFICER, {"contract_id": env["contract"]["id"]}
            )
        )
        assert charge_meta["total_count"] == 0, (
            f"a cancellation generates no charge, got {charges}"
        )
        contract = fx.read_contract(env["contract"]["id"])
        assert contract["credit_accrued_cents"] == 0
        account = fx.read_account(env["account"]["id"])
        assert account["open_credit_balance_cents"] == 0
        assert account["billing_hold"] is False
