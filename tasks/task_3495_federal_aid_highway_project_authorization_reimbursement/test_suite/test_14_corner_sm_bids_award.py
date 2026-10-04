"""Corner queue — state_machines (Project/Bid): the advertisement window
boundary, award state gating, INELIGIBLE terminal lockout, and the pinned
lowest-responsive selection with its submission-order tie-break
(PRD §3.6, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advertise_project,
    api_client,
    assert_bid,
    authorize_project,
    award_project,
    clear_project,
    create_bid_entry,
    determine_project_eligible,
    get_success_data,
    open_project_bids,
    set_clock,
    setup_stip_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


def _eligible_cleared_project(api):
    """Approved STIP whose single project is ELIGIBLE with both clearances
    CLEARED (default apportionment covers the estimate)."""
    pipeline = setup_stip_pipeline(
        program_code="NHPP",
        eligible_activity_codes=["ROAD_RESURFACING"],
        state_code="AZ",
        project_specs=[{"total_estimated_cost_cents": 100_000}],
    )
    project = pipeline["projects"][0]
    determine_project_eligible(project["id"])
    clear_project(project["id"])
    return project


def _bidding_project(api):
    """ELIGIBLE+cleared project authorized for 80,000 and advertised."""
    project = _eligible_cleared_project(api)
    authorize_project(project["id"], initial_obligated_cents=80_000,
                      agreement_number="FA-ADV")
    advertise_project(project["id"])  # advertised_on_date = 2026-10-15 clock
    return project


def _bids_opened_project(api, bids):
    project = _bidding_project(api)
    opened = open_project_bids(project["id"], bids)
    return project, opened


class TestBidsAndAwardStateMachine:
    def test_award_while_bidding_returns_invalid_state(self, api):
        """PRD §2.7: "6. State gate: the target resource must be in a valid
        from-state for the requested action, else `ERR_INVALID_STATE` (409)."
        PRD §3.6: "A successful award moves the winning Bid from `SUBMITTED` to
        `AWARDED`, moves every other Bid of the project to `NOT_AWARDED` (both
        terminal statuses for a Bid), records the winner on the Project's
        `awarded_bid_id`, and moves the Project from `BIDS_OPENED` to
        `UNDER_CONSTRUCTION`."

        Award is defined from BIDS_OPENED; on a merely BIDDING project the
        state gate fires.

        Design: Corner/state_machines/award_while_bidding_returns_invalid_state
        """
        project = _bidding_project(api)
        set_clock("2026-11-06T00:00:00Z")  # window elapsed; open-bids never called
        resp = api.award_project(
            project["id"],
            {"bid_id": NON_EXISTENT_UUID, "dbe_commitment_pct": 0.10},
            H["fhwa_reviewer"],
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

    def test_open_bids_window_boundary_twenty_one_days(self, api):
        """PRD §3.6: "Sealed bids may be opened only after the statutory
        advertisement window: the logical clock must have reached at least 21
        days after `advertised_on_date` — exactly 21 days passes — else
        `ERR_ADVERTISEMENT_PERIOD_SHORT` (409)."
        PRD §3.6: "The server creates one Bid per entry, in `SUBMITTED` status,
        with `project_id` taken from the path and `submission_seq` set to the
        entry's 0-based position in the payload array — a value that matters,
        because it is the only tie-break the award knows."

        Advertised 2026-10-15: +20 days (2026-11-04) fails; exactly +21
        (2026-11-05) succeeds and the payload order becomes submission_seq.

        Design: Corner/state_machines/open_bids_window_boundary_twenty_one_days
        """
        project = _bidding_project(api)

        set_clock("2026-11-04T00:00:00Z")  # +20 days
        early = api.open_bids(
            project["id"],
            {"bids": [create_bid_entry("A", 90_000, True)]},
            H["state_dot_engineer"],
        )
        error = validate_error(early, ApiErrorId.ERR_ADVERTISEMENT_PERIOD_SHORT)
        assert early.status_code == 409, (
            f"+20 days must fail the 21-day window, got {early.status_code} ({error})"
        )

        set_clock("2026-11-05T00:00:00Z")  # exactly +21 days
        opened = api.open_bids(
            project["id"],
            {
                "bids": [
                    create_bid_entry("A", 90_000, True),
                    create_bid_entry("B", 95_000, True),
                ]
            },
            H["state_dot_engineer"],
        )
        project_after = validate_success(opened)
        assert project_after["status"] == "BIDS_OPENED"

        rows, meta = validate_paginated(
            api.list_project_bids(project["id"], H["fhwa_reviewer"])
        )
        assert meta["total_count"] == 2
        assert [b["submission_seq"] for b in rows] == [0, 1], (
            "submission_seq must equal the 0-based payload position"
        )
        for row in rows:
            assert_bid(row)
            assert row["status"] == "SUBMITTED"

    def test_project_ineligible_is_terminal(self, api):
        """PRD §3.3: "A `determination` of `INELIGIBLE` moves the Project to
        the terminal `INELIGIBLE` status with no further checks."
        PRD §3.3: "Eligibility determination belongs to the
        `FHWADivisionAdmin`, acts only on a `NOMINATED` Project (any other
        status yields `ERR_INVALID_STATE`), and first requires the owning STIP
        to be `APPROVED`, else `ERR_STIP_NOT_APPROVED` (409)."
        PRD §3.6: "Once `AUTHORIZED`, a `StateDOTEngineer` advertises the
        Project, which stamps `advertised_on_date` from the logical clock and
        moves the Project from `AUTHORIZED` to `BIDDING`."

        Neither re-determination nor advertisement is defined from INELIGIBLE.

        Design: Corner/state_machines/project_ineligible_is_terminal
        """
        pipeline = setup_stip_pipeline(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            state_code="AZ",
            project_specs=[{"total_estimated_cost_cents": 1_000}],
        )
        project = pipeline["projects"][0]
        resp = api.determine_eligibility(
            project["id"], {"determination": "INELIGIBLE"}, H["fhwa_division_admin"]
        )
        assert validate_success(resp)["status"] == "INELIGIBLE"

        again = api.determine_eligibility(
            project["id"], {"determination": "ELIGIBLE"}, H["fhwa_division_admin"]
        )
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)

        advertised = api.advertise_project(project["id"], H["state_dot_engineer"])
        validate_error(advertised, ApiErrorId.ERR_INVALID_STATE)

        reread = get_success_data(api.get_project(project["id"], H["fhwa_reviewer"]))
        assert reread["status"] == "INELIGIBLE"

    def test_bid_tie_breaks_by_submission_order(self, api):
        """PRD §3.6: "The winner is determined by a pinned selection rule:
        among this project's Bid rows that are responsive and still
        `SUBMITTED`, order by `bid_amount_cents` ascending, breaking ties by
        `submission_seq` ascending — the earlier array position wins, and
        resource ids are never consulted."
        PRD §3.6: "and the named bid must be the winner under the selection
        rule, else `ERR_AWARD_NOT_LOWEST_RESPONSIVE` (422)."
        PRD §3.6: "A successful award moves the winning Bid from `SUBMITTED` to
        `AWARDED`, moves every other Bid of the project to `NOT_AWARDED` (both
        terminal statuses for a Bid), records the winner on the Project's
        `awarded_bid_id`, and moves the Project from `BIDS_OPENED` to
        `UNDER_CONSTRUCTION`."

        Two responsive bids tie at 90,000: the seq-1 bid is not awardable; the
        seq-0 bid is.

        Design: Corner/state_machines/bid_tie_breaks_by_submission_order
        """
        project, bids = _bids_opened_project(
            api,
            [
                create_bid_entry("First", 90_000, True),
                create_bid_entry("Second", 90_000, True),
            ],
        )
        bid_first, bid_second = bids[0], bids[1]
        assert bid_first["submission_seq"] == 0
        assert bid_second["submission_seq"] == 1

        wrong = api.award_project(
            project["id"],
            {"bid_id": bid_second["id"], "dbe_commitment_pct": 0.10},
            H["fhwa_reviewer"],
        )
        error = validate_error(wrong, ApiErrorId.ERR_AWARD_NOT_LOWEST_RESPONSIVE)
        assert wrong.status_code == 422, (
            "the tied seq-1 bid must lose to the earlier array position; got "
            f"{wrong.status_code} ({error})"
        )

        awarded = award_project(project["id"], bid_first["id"], 0.10)
        assert awarded["status"] == "UNDER_CONSTRUCTION"
        assert awarded["awarded_bid_id"] == bid_first["id"]

        rows, _meta = validate_paginated(
            api.list_project_bids(project["id"], H["fhwa_reviewer"])
        )
        by_id = {b["id"]: b for b in rows}
        assert by_id[bid_first["id"]]["status"] == "AWARDED"
        assert by_id[bid_second["id"]]["status"] == "NOT_AWARDED"

    def test_lowest_responsive_skips_cheaper_nonresponsive_bid(self, api):
        """PRD §3.6: "the pool must contain at least one responsive bid, else
        `ERR_NO_RESPONSIVE_BIDS` (422), a check evaluated before the named bid
        is inspected; the named `bid_id` must reference a Bid of this project
        with `is_responsive` true, else `ERR_BID_NOT_RESPONSIVE` (422); and the
        named bid must be the winner under the selection rule, else
        `ERR_AWARD_NOT_LOWEST_RESPONSIVE` (422)."

        The cheaper non-responsive bid (80,000) is invisible to the selector:
        naming it fails, and the responsive 90,000 bid is the awardable winner.

        Design: Corner/state_machines/lowest_responsive_skips_cheaper_nonresponsive_bid
        """
        project, bids = _bids_opened_project(
            api,
            [
                create_bid_entry("CheapNR", 80_000, False),
                create_bid_entry("FairR", 90_000, True),
            ],
        )
        bid_nr, bid_r = bids[0], bids[1]

        wrong = api.award_project(
            project["id"],
            {"bid_id": bid_nr["id"], "dbe_commitment_pct": 0.10},
            H["fhwa_reviewer"],
        )
        error = validate_error(wrong, ApiErrorId.ERR_BID_NOT_RESPONSIVE)
        assert wrong.status_code == 422, (
            f"naming a non-responsive bid must fail, got {wrong.status_code} ({error})"
        )

        awarded = award_project(project["id"], bid_r["id"], 0.10)
        assert awarded["status"] == "UNDER_CONSTRUCTION"
        assert awarded["awarded_bid_id"] == bid_r["id"]
