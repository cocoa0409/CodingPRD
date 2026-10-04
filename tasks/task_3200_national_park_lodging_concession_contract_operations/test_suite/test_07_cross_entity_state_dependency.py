"""One entity's valid transitions depend on another entity's state.

A filing cannot be adjudicated against a study that is not REGISTERED at the
moment of adjudication (PRD 3.2); a CLOSED season cannot reconcile while any
hire attached to it is still HIRED or ARRIVED (PRD 3.4).
"""

from test_helpers import constants as C
from test_helpers.api_errors import (
    ERR_UNRECONCILED_SEASON,
)
from test_helpers.assertions import (
    get_success_data,
    validate_error,
)
from test_helpers.fixtures import (
    active_contract,
    add_housing_unit,
    add_room_class,
    add_study,
    hire_employee,
    read_hire,
    reset_clock,
    set_clock,
    submit_filing,
)
from test_helpers.test_users import (
    HR_MANAGER,
    OPS_MANAGER,
    RATE_ANALYST,
    RATE_MANAGER,
)


class TestFilingGatedByStudyState:
    """A stale-for-the-season study never carries a filing to UNDER_REVIEW."""

    def _scenario(self, client, valid_through="2026-06-01T00:00:00Z"):
        """ACTIVE contract with a 2028 season and a study whose
        valid_through (default 2026-06-01) precedes the season open
        (2028-06-01)."""
        reset_clock(client)
        contract, _unused, _lines = active_contract(client)
        contract_id = contract["id"]
        from test_helpers.fixtures import add_season
        season = add_season(
            client, contract_id,
            year=2028,
            open_date="2028-06-01T00:00:00Z",
            close_date="2028-09-01T00:00:00Z",
            lottery_open_date="2027-12-01T00:00:00Z",
            lottery_window_hours=72,
        )
        room_class = add_room_class(client, contract_id)
        study = add_study(
            client, contract_id, title="Old study",
            prepared_at="2025-06-01T00:00:00Z",
            valid_through=valid_through,
        )
        return contract_id, season["id"], room_class["id"], study["id"]

    def test_creation_against_a_study_expired_for_the_season_is_rejected(
        self, client
    ):
        """PRD 3.2: "The cited study must still be valid for the season: if
        the study's `valid_through` falls before the season's `open_date`,
        the submission is rejected with `ERR_STUDY_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/filing_review_gated_by_study_registered_state
        """
        from test_helpers.api_errors import ERR_STUDY_EXPIRED
        from test_helpers import factories as f

        contract_id, season_id, room_class_id, study_id = self._scenario(client)
        from test_helpers.fixtures import contract_version
        response = client.create_filing(
            contract_id,
            f.filing_payload(
                season_id, room_class_id, study_id,
                contract_version(client, contract_id),
            ),
            headers=RATE_MANAGER,
        )
        validate_error(response, ERR_STUDY_EXPIRED)

    def test_review_requires_the_study_to_still_be_registered(self, client):
        """PRD 3.2: "Starting review moves a `SUBMITTED` filing to
        `UNDER_REVIEW`, and is permitted only while the cited study is still
        `REGISTERED`; otherwise the request is rejected with
        `ERR_STUDY_NOT_CURRENT`."

        Design: Difficulty/cross_entity_state_dependency/filing_review_gated_by_study_registered_state
        """
        contract_id, season_id, room_class_id, study_id = self._scenario(
            client, valid_through="2028-06-01T00:00:00Z"
        )
        filing = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
        )
        # Advance the logical clock past the study's valid_through horizon so
        # the study is no longer current at review time.
        set_clock(client, "2028-06-02T00:00:00Z")
        response = client.start_review_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        )
        from test_helpers.api_errors import ERR_STUDY_NOT_CURRENT
        validate_error(response, ERR_STUDY_NOT_CURRENT)
        reread = get_success_data(client.get_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        ))
        assert reread["status"] == C.FILING_SUBMITTED


class TestSeasonReconcileGatedByHires:
    """A CLOSED season reconciles only once every hire is terminal."""

    def _setup(self, client):
        """ACTIVE contract; one ARRIVED hire; clock past the season close."""
        reset_clock(client)
        contract, season, lines = active_contract(client)
        contract_id = contract["id"]
        unit = add_housing_unit(client, contract_id, unit_code="DORM-C1",
                                bed_count=4)
        hire = hire_employee(
            client, contract_id, season["id"],
            lines[C.LINE_LODGING]["id"], unit["id"],
        )
        client.mark_arrived(contract_id, hire["id"], headers=HR_MANAGER)
        set_clock(client, "2027-09-02T00:00:00Z")
        return contract_id, season["id"], hire

    def test_reconcile_blocked_while_a_hire_is_still_arrived(self, client):
        """PRD 3.4: "Reconciliation requires that every seasonal hire attached
        to the season has reached a terminal state — `DEPARTED`, `NO_SHOW`,
        or `TERMINATED` — and that every gross receipts report whose
        `period_month` overlaps the season has been `ACCEPTED`; if either
        condition fails, the request is rejected with
        `ERR_UNRECONCILED_SEASON`."

        Design: Difficulty/cross_entity_state_dependency/season_reconcile_gated_by_hire_terminal_states
        """
        contract_id, season_id, hire = self._setup(client)
        assert read_hire(client, contract_id, hire["id"])["status"] == C.HIRE_ARRIVED
        response = client.reconcile_season(
            contract_id, season_id, headers=OPS_MANAGER
        )
        validate_error(response, ERR_UNRECONCILED_SEASON)

    def test_reconcile_succeeds_after_the_hire_departs(self, client):
        """PRD 3.4: "A successful reconciliation moves the season to
        `RECONCILED` and bumps the contract's `version` by one as a
        bubble-up."

        Design: Difficulty/cross_entity_state_dependency/season_reconcile_gated_by_hire_terminal_states
        """
        contract_id, season_id, hire = self._setup(client)
        client.mark_departed(contract_id, hire["id"], headers=HR_MANAGER)
        reconciled = get_success_data(client.reconcile_season(
            contract_id, season_id, headers=OPS_MANAGER
        ))
        assert reconciled["status"] == C.SEASON_RECONCILED
