"""Validation violations and the error catalogue.

Auth failures precede even path resolution (PRD 2.10); nested paths resolve
left to right (PRD 2.5); duplicate (line, period) reports, segregation of
duties, OCC version staleness, the lottery release gate, enum membership and
entity-specific 404s each surface their named error id (PRD 2, 3, 5).
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_DUPLICATE_PERIOD_REPORT,
    ERR_INVALID_REQUEST,
    ERR_LOTTERY_NOT_OPEN,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_PROJECT_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_CONTRACT_VERSION,
)
from test_helpers.assertions import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    accept_report,
    accepted_report,
    active_contract,
    add_room_class,
    add_study,
    approve_filing,
    book_reservation,
    bookable_inventory,
    contract_version,
    create_contract,
    create_project,
    create_report,
    reset_clock,
    submit_filing,
    submit_report,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    AUDITOR,
    FRONT_DESK,
    HR_MANAGER,
    MAINTENANCE_CHIEF,
    OFFICER,
    OPS_MANAGER,
    RATE_ANALYST,
    RATE_MANAGER,
    headers_for,
)

UNKNOWN_CONTRACT = "00000000-0000-4000-8000-000000000000"
UNKNOWN_CHILD = "00000000-0000-4000-8000-000000000001"


class TestAuthenticationOrder:
    def test_missing_headers_beat_a_nonexistent_path(self, client):
        """PRD 2.1: "A request missing either header, or carrying a value the
        server does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)." and
        PRD 2.10: "Authentication comes first: missing or invalid `X-User-ID`
        or `X-User-Role` headers are rejected before anything else".

        Design: Corner/validations/auth_missing_header_beats_everything
        """
        reset_clock(client)
        response = client.get_contract(UNKNOWN_CONTRACT, headers={})
        validate_error(response, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_an_unrecognized_role_is_rejected_as_missing_context(self, client):
        """PRD 2.1: "A request missing either header, or carrying a value the
        server does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/auth_missing_header_beats_everything
        """
        reset_clock(client)
        response = client.get_contract(
            UNKNOWN_CONTRACT, headers=headers_for("NightAuditor", "mystery-user")
        )
        validate_error(response, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestPathResolutionOrder:
    def test_the_contract_segment_resolves_before_the_child(self, client):
        """PRD 2.5: "Nested paths are validated left to right: the contract
        identifier is resolved first (an unknown one yields
        `ERR_CONTRACT_NOT_FOUND`), and only then is the child identifier
        resolved within that contract".

        Design: Corner/validations/existence_check_validates_path_left_to_right
        """
        reset_clock(client)
        response = client.get_filing(
            UNKNOWN_CONTRACT, UNKNOWN_CHILD, headers=RATE_ANALYST
        )
        validate_error(response, ERR_CONTRACT_NOT_FOUND)

    def test_unknown_child_ids_are_entity_specific(self, client):
        """PRD 2.5: "with a missing child producing the corresponding
        not-found error — for example `ERR_SEASON_NOT_FOUND`,
        `ERR_FILING_NOT_FOUND`, or `ERR_RESERVATION_NOT_FOUND` — for the
        first path segment that fails to resolve."

        Design: Corner/errors/every_not_found_variant_is_entity_specific
        """
        reset_clock(client)
        contract = create_contract(client)
        response = client.get_reservation(
            contract["id"], UNKNOWN_CHILD, headers=FRONT_DESK
        )
        validate_error(response, ERR_RESERVATION_NOT_FOUND)
        response = client.get_capital_project(
            contract["id"], UNKNOWN_CHILD, headers=MAINTENANCE_CHIEF
        )
        validate_error(response, ERR_PROJECT_NOT_FOUND)


class TestDuplicatePeriodReport:
    def _setup(self, client):
        reset_clock(client)
        contract, _season, lines = active_contract(client)
        accepted_report(
            client, contract["id"], lines[C.LINE_LODGING]["id"],
            gross_receipts_cents=20000,
        )
        return contract, lines

    def test_a_second_accepted_period_report_for_the_line_is_rejected(
        self, client
    ):
        """PRD 3.5: "Each report belongs to one line and one month: if an
        `ACCEPTED` report already exists for the same service line and
        period, a new one is rejected with `ERR_DUPLICATE_PERIOD_REPORT`."

        Design: Corner/validations/duplicate_period_report_rejected_for_same_line
        """
        contract, lines = self._setup(client)
        response = client.create_receipts_report(
            contract["id"],
            f.receipts_report_payload(
                lines[C.LINE_LODGING]["id"],
                contract_version(client, contract["id"], headers=ACCOUNTANT),
                gross_receipts_cents=21000,
            ),
            headers=ACCOUNTANT,
        )
        validate_error(response, ERR_DUPLICATE_PERIOD_REPORT)

    def test_the_uniqueness_scope_is_line_and_period_not_period(self, client):
        """PRD 3.5: "Reporting is monthly and per service line." and "if an
        `ACCEPTED` report already exists for the same service line and
        period, a new one is rejected with `ERR_DUPLICATE_PERIOD_REPORT`."

        Design: Corner/validations/duplicate_period_report_rejected_for_same_line
        """
        contract, lines = self._setup(client)
        food = create_report(
            client, contract["id"], lines[C.LINE_FOOD]["id"],
            gross_receipts_cents=9000,
        )
        assert food["status"] == C.REPORT_DRAFT


class TestSegregationOfDuties:
    def test_the_submitter_cannot_accept_their_own_report(self, client):
        """PRD 3.5: "Acceptance is segregation-of-duties gated: the accepting
        user's `X-User-ID` must differ from the `X-User-ID` recorded at
        submission, or the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_blocks_self_acceptance
        """
        reset_clock(client)
        contract, _season, lines = active_contract(client)
        contract_id = contract["id"]
        submitter = headers_for(C.ROLE_ACCOUNTANT, "acct-jane")
        report = create_report(
            client, contract_id, lines[C.LINE_LODGING]["id"],
            creator=submitter, gross_receipts_cents=20000,
        )
        submit_report(client, contract_id, report["id"], submitter=submitter)
        response = client.accept_report(
            contract_id, report["id"],
            headers=headers_for(C.ROLE_FINANCIAL_AUDITOR, "acct-jane"),
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)

    def test_a_different_auditor_accepts(self, client):
        """PRD 3.5: "Acceptance is segregation-of-duties gated: the accepting
        user's `X-User-ID` must differ from the `X-User-ID` recorded at
        submission, or the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_blocks_self_acceptance
        """
        reset_clock(client)
        contract, _season, lines = active_contract(client)
        contract_id = contract["id"]
        report = create_report(
            client, contract_id, lines[C.LINE_LODGING]["id"],
            gross_receipts_cents=20000,
        )
        submit_report(client, contract_id, report["id"])
        accepted = accept_report(client, contract_id, report["id"])
        assert accepted["status"] == C.REPORT_ACCEPTED


class TestOptimisticConcurrency:
    def test_a_stale_expected_version_is_rejected_with_412(self, client):
        """PRD 2.8: "If the contract's current `version` differs from the
        supplied value — because, for example, another filing was approved in
        the meantime and the approval bumped the contract's version — the
        creation is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_contract_version_rejected_with_412
        """
        scenario = bookable_inventory(client, clock=None)
        contract_id = scenario["contract"]["id"]
        # The version the client last observed is the one before the first
        # filing; the approved filing has since bumped it.
        stale = scenario["version"] - 2
        payload = f.filing_payload(
            scenario["season"]["id"], scenario["room_class"]["id"],
            scenario["study"]["id"], stale,
        )
        response = client.create_filing(contract_id, payload, headers=RATE_MANAGER)
        validate_error(response, ERR_STALE_CONTRACT_VERSION)

    def test_reservation_creation_with_a_stale_version_is_rejected(self, client):
        """PRD 2.8: "When a client creates a rate filing, a gross receipts
        report, or a reservation, the request body must carry
        `expected_contract_version`, holding the contract `version` the
        client last observed. If the contract's current `version` differs
        from the supplied value ... the creation is rejected with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_reservation_create_stale_version
        """
        scenario = bookable_inventory(client)
        contract_id = scenario["contract"]["id"]
        observed = scenario["version"]
        first = book_reservation(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            observed, guest_ref="g-occ1",
        )
        assert first["id"]
        payload = f.reservation_payload(
            scenario["season"]["id"], scenario["room_class"]["id"],
            observed,  # now stale: the first create bumped the version
            guest_ref="g-occ2",
            check_in_date="2027-07-11T00:00:00Z",
            check_out_date="2027-07-12T00:00:00Z",
        )
        response = client.create_reservation(
            contract_id, payload, headers=FRONT_DESK
        )
        validate_error(response, ERR_STALE_CONTRACT_VERSION)

    def test_retrying_with_the_fresh_version_succeeds(self, client):
        """PRD 2.8: "This is a stale-view rejection, not a timing rule: it
        fires whenever the client's view of the contract predates the current
        version, regardless of how the versions came to diverge."

        Design: Corner/cross_cutting_complexity_layers/occ_reservation_create_stale_version
        """
        scenario = bookable_inventory(client)
        contract_id = scenario["contract"]["id"]
        observed = scenario["version"]
        book_reservation(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            observed, guest_ref="g-occ1",
        )
        fresh = contract_version(client, contract_id, headers=FRONT_DESK)
        second = book_reservation(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            fresh, guest_ref="g-occ2",
            check_in_date="2027-07-11T00:00:00Z",
            check_out_date="2027-07-12T00:00:00Z",
        )
        assert second["id"]


class TestLotteryReleaseGate:
    def test_a_request_before_the_window_opens_is_rejected(self, client):
        """PRD 3.3: "A request that arrives before the lottery window has
        opened is rejected with `ERR_LOTTERY_NOT_OPEN`."

        Design: Corner/errors/lottery_submission_before_window_rejected
        """
        # clock=None leaves the logical clock at the 2026-09-01 startup
        # instant, before the 2026-12-01 lottery release.
        scenario = bookable_inventory(client, clock=None)
        contract_id = scenario["contract"]["id"]
        payload = f.reservation_payload(
            scenario["season"]["id"], scenario["room_class"]["id"],
            contract_version(client, contract_id, headers=FRONT_DESK),
            guest_ref="g-early",
        )
        response = client.create_reservation(
            contract_id, payload, headers=FRONT_DESK
        )
        validate_error(response, ERR_LOTTERY_NOT_OPEN)
        rows, meta = validate_paginated(client.list_reservations(
            contract_id, headers=FRONT_DESK
        ))
        assert meta["total_count"] == 0, "no reservation row may exist"


class TestEnumMembership:
    def test_an_unknown_line_type_is_an_invalid_request(self, client):
        """PRD 4 (endpoint table): "Create a service line (LODGING / FOOD /
        RETAIL / TOURS)" and PRD 2.10 assigns malformed bodies and invalid
        enum values to `ERR_INVALID_REQUEST` via PRD 5's catalogue entry.

        Design: Corner/errors/invalid_enum_value_rejected_as_invalid_request
        """
        reset_clock(client)
        contract = create_contract(client)
        response = client.create_service_line(
            contract["id"], {"line_type": "SPA"}, headers=OFFICER
        )
        validate_error(response, ERR_INVALID_REQUEST)
