"""Validation priority pairs: earlier categories report before later ones
(PRD §2.11).
"""
from test_helpers import (
    ApiErrorId,
    PANEL,
    api_client,
    create_brief_payload,
    create_petition_payload,
    get_proceeding,
    new_world,
    NON_EXISTENT_UUID,
    setup_decided_proceeding,
    validate_error,
    validate_paginated,
)


class TestStateErrorBeatsBusinessConstraint:
    def test_phase_error_reported_for_over_cap_brief_on_decided_proceeding(self):
        """PRD §2.11: "A request that violates both an earlier and a later
        category always reports the earlier one." (state-machine preconditions
        are category (7); domain constraints such as page caps are (9).)

        Design: Difficulty/priority_pair_validation_conflict/state_phase_error_beats_business_constraint_page_cap
        """
        world = setup_decided_proceeding(
            institute_kw=dict(
                total_claims=2, challenged_claims=(1, 2),
                scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 60},
                        {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 58}],
                lead_judge="judge-judy",
            ),
            hearing_start="2027-01-20T13:00:00Z", hearing_end="2027-01-20T14:00:00Z",
        )
        assert world["proceeding"]["phase"] == "DECIDED"
        # 200 pages breaches the 110-page PO_RESPONSE hard cap (category 9)
        # AND the phase is DECIDED (category 7): the state error must win.
        resp = api_client.create_brief(
            world["proceeding"]["id"],
            create_brief_payload("PO_RESPONSE", 200),
            world["owner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PHASE, 409)

    def test_rejected_over_cap_brief_leaves_proceeding_unchanged(self):
        """PRD §3.5: "a `PO_RESPONSE` above 110 pages, a `PETITIONER_REPLY`
        above 65 pages, or a `PO_SUR_REPLY` above 40 pages is rejected with
        `ERR_PAGE_LIMIT_EXCEEDED`" — and a rejected brief records nothing.

        Design: Difficulty/priority_pair_validation_conflict/state_phase_error_beats_business_constraint_page_cap
        """
        world = setup_decided_proceeding(
            institute_kw=dict(
                total_claims=2, challenged_claims=(1, 2),
                scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 60},
                        {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 58}],
                lead_judge="judge-judy",
            ),
            hearing_start="2027-01-20T13:00:00Z", hearing_end="2027-01-20T14:00:00Z",
        )
        resp = api_client.create_brief(
            world["proceeding"]["id"],
            create_brief_payload("PO_RESPONSE", 200),
            world["owner_headers"],
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_PHASE, 409)
        assert err["error_id"] != ApiErrorId.ERR_PAGE_LIMIT_EXCEEDED
        proceeding = get_proceeding(world["proceeding"]["id"])
        assert proceeding["phase"] == "DECIDED"
        assert proceeding["total_overage_fee_cents"] == 0


class TestExistenceErrorBeatsFiscalError:
    def _parties_and_patent(self):
        world = new_world(petitioner_name="P11 Corp", owner_name="O11 Corp")
        return world

    def test_missing_patent_reports_404_not_fee_error(self):
        """PRD §2.11: "(3) existence of path resources, validated
        left-to-right, followed by existence of body-referenced entities (the
        404 family of §2.6)" precedes "(10) filing-fee sufficiency
        (`ERR_FEE_INSUFFICIENT`)", and "A request that violates both an
        earlier and a later category always reports the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/existence_error_beats_business_fiscal_fee_error
        """
        world = self._parties_and_patent()
        payload = create_petition_payload(
            patent_id=NON_EXISTENT_UUID,
            petitioner_id=world["petitioner"]["id"],
            challenged_claims=[1],
            fee_paid_cents=0,
            expected_patent_version=world["patent"]["version"],
        )
        resp = api_client.create_petition(payload, world["petitioner_headers"])
        validate_error(resp, ApiErrorId.ERR_PATENT_NOT_FOUND, 404)

    def test_rejected_filing_creates_no_petition(self):
        """PRD §3.3: "When `fee_paid_cents` falls below the required amount,
        the filing is rejected with `ERR_FEE_INSUFFICIENT` (HTTP 402)" — the
        fiscal check exists, but against a non-existent patent the existence
        error reports first and nothing is written.

        Design: Difficulty/priority_pair_validation_conflict/existence_error_beats_business_fiscal_fee_error
        """
        world = self._parties_and_patent()
        payload = create_petition_payload(
            patent_id=NON_EXISTENT_UUID,
            petitioner_id=world["petitioner"]["id"],
            challenged_claims=[1],
            fee_paid_cents=0,
            expected_patent_version=world["patent"]["version"],
        )
        resp = api_client.create_petition(payload, world["petitioner_headers"])
        err = validate_error(resp, ApiErrorId.ERR_PATENT_NOT_FOUND, 404)
        assert err["error_id"] != ApiErrorId.ERR_FEE_INSUFFICIENT
        rows, meta = validate_paginated(api_client.list_petitions(PANEL, params={}))
        assert meta["total_count"] == 0
        assert rows == []
