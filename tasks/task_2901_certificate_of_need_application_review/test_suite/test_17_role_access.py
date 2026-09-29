"""The role matrix of §4: each denial is endpoint-scoped and runs before other checks."""

from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import UNKNOWN_APPLICATION_ID
from test_helpers.factories import certificate_payload
from test_helpers.fixtures import (
    ADMIN,
    PUBLIC,
    REVIEWER,
    refresh_applicant,
    refresh_cycle,
    seed_applicant,
    seed_batching_cycle,
)
from test_helpers.test_users import make_applicant_headers


class TestComparativeDecisionIsOfficerOnly:
    def test_an_applicant_is_refused_before_any_quorum_check_runs(self):
        """The role denial pre-empts the score-sheet rules on an unscored cycle.

        PRD §2.1: "When the headers are present, the role must be one of the seven
        declared roles **and** must be listed for the addressed endpoint in §4;
        otherwise the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.8: "**Role admissibility.** `X-User-Role` is one of the seven declared
        roles and that role is listed for the endpoint in §4 — otherwise
        `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        PRD §4: "| POST | `/batching-cycles/{id}/comparative-decision` | Run the
        comparative review: rank the competing applications, allocate the unmet need
        pool and record every decision | `DecisionOfficer` |"

        Design: Corner/rbac/applicant_cannot_run_the_comparative_decision_returns_unauthorized
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()
        assert world["cycle"]["status"] == "OPEN_FOR_LOI"

        response = api_client.run_comparative_decision(
            world["cycle"]["id"],
            {"decision_note": "Applicant attempts to decide its own batch"},
            make_applicant_headers(applicant["id"]),
        )

        body = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert body["error_id"] != ApiErrorId.ERR_INSUFFICIENT_SCORE_SHEETS
        assert body["error_id"] != ApiErrorId.ERR_NO_ELIGIBLE_APPLICATIONS
        cycle = refresh_cycle(world["cycle"]["id"])
        assert cycle["status"] == "OPEN_FOR_LOI"
        assert cycle["version"] == world["cycle"]["version"]
        assert cycle["unallocated_bed_need"] == 19


class TestIssuanceIsOfficerOnly:
    def test_a_review_analyst_is_refused_before_the_application_is_resolved(self):
        """The named application does not exist, yet the role check answers first.

        PRD §2.8: "**Role admissibility.** `X-User-Role` is one of the seven declared
        roles and that role is listed for the endpoint in §4 — otherwise
        `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        PRD §2.8: "When a request violates more than one rule, exactly one error is
        returned: the one belonging to the lowest-numbered rule in the following
        order."
        PRD §4: "| POST | `/certificates` | Issue a certificate of need for an
        approved application once its appeal window has closed | `DecisionOfficer` |"

        Design: Corner/rbac/review_analyst_cannot_issue_a_certificate_returns_unauthorized
        """
        applicant = seed_applicant()

        response = api_client.create_certificate(
            certificate_payload(UNKNOWN_APPLICATION_ID), REVIEWER
        )

        body = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert body["error_id"] != ApiErrorId.ERR_APPLICATION_NOT_FOUND
        _, meta = validate_paginated(api_client.list_certificates(ADMIN))
        assert meta["total_count"] == 0
        assert refresh_applicant(applicant["id"])["compliance_strike_count"] == 0


class TestApplicantReadsAreStaffAndOwnerOnly:
    def test_a_public_participant_is_refused_a_row_the_applicant_may_read(self):
        """The denial is per endpoint: the same caller still lists cycles freely.

        PRD §2.8: "**Role admissibility.** `X-User-Role` is one of the seven declared
        roles and that role is listed for the endpoint in §4 — otherwise
        `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        PRD §4: "| GET | `/applicants/{id}` | Read an applicant including program
        standing and strike count | `ProgramAdmin`, `IntakeAnalyst`, `ReviewAnalyst`,
        `DecisionOfficer`, `AppealBoardMember`, `Applicant` |"
        PRD §4: "| GET | `/batching-cycles` | List cycles, filterable by planning
        area, pinned formula, service type and status | `ProgramAdmin`,
        `IntakeAnalyst`, `ReviewAnalyst`, `DecisionOfficer`, `AppealBoardMember`,
        `Applicant`, `PublicParticipant` |"

        Design: Corner/rbac/public_participant_cannot_read_an_applicant_row_returns_unauthorized
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()
        own_read = get_success_data(
            api_client.get_applicant(
                applicant["id"], make_applicant_headers(applicant["id"])
            )
        )
        assert own_read["standing"] == "GOOD"

        response = api_client.get_applicant(applicant["id"], PUBLIC)

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        cycles, meta = validate_paginated(api_client.list_batching_cycles(PUBLIC))
        assert meta["total_count"] == 1
        assert [cycle["id"] for cycle in cycles] == [world["cycle"]["id"]]
