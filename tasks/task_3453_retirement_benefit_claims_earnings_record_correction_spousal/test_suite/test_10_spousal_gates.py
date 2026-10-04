"""Auxiliary-claim approval gates: verified relationship, entitled covered
worker, and the marriage-duration / divorce-wait fiscal rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_relationship,
    create_worker,
    create_worker_with_awi_record,
    file_auxiliary_claim,
    file_claim,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestSpousalCrossEntityGates:
    def test_relationship_not_verified_gate_then_success(self, api):
        """PRD §3.4: "Every auxiliary type additionally requires its
        `relationship_id` to resolve to a `VERIFIED` relationship, else
        `ERR_RELATIONSHIP_NOT_VERIFIED` (422)."

        With the relationship still ASSERTED the approve is rejected; after
        verification the identical approve succeeds (spousal base
        dime_floor(0.5*20,880) = 10,440, 60 early months at 25/3600 then 5/1200
        gives 6,780; no own PIA, family maximum not binding, no pension).

        Design: Difficulty/cross_entity_state_dependency/spousal_approve_gated_on_relationship_and_covered_worker
        """
        hub = create_worker_with_awi_record(2019, 2023, full_name="Entitled Hub")
        hub_claim = file_claim(hub["id"], "RETIREMENT", "2026-06")
        approve_claim(hub_claim["id"])

        spouse = create_worker(full_name="Spouse X")
        rel = create_relationship(hub["id"], spouse["id"], "CURRENT_SPOUSE", "2000-01-01")
        claim = file_auxiliary_claim(spouse["id"], "SPOUSAL", "2026-06", rel["id"])

        resp = api.approve_claim(claim["id"], CS)
        validate_error(resp, ApiErrorId.ERR_RELATIONSHIP_NOT_VERIFIED, 422)
        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "FILED"

        validate_success(api.verify_relationship(rel["id"], CS))
        entitled = approve_claim(claim["id"])
        assert entitled["status"] == "ENTITLED"
        assert entitled["monthly_benefit_cents"] == 6_780

    def test_spouse_not_entitled_gate_with_verified_relationship(self, api):
        """PRD §3.4: "`SPOUSAL` requires the covered worker to hold a `RETIREMENT`
        claim in `ENTITLED` or `SUSPENDED` status — otherwise
        `ERR_SPOUSE_NOT_ENTITLED` (422) — and the marriage must have lasted at
        least twelve months by `entitlement_month`, otherwise
        `ERR_MARRIAGE_DURATION_INSUFFICIENT` (422)."

        The covered worker's claim is only FILED; the verified relationship does
        not rescue the approve.

        Design: Difficulty/cross_entity_state_dependency/spousal_approve_gated_on_relationship_and_covered_worker
        """
        hub = create_worker_with_awi_record(2019, 2023, full_name="Filed Hub")
        file_claim(hub["id"], "RETIREMENT", "2026-06")  # never approved

        spouse = create_worker(full_name="Spouse Y")
        rel = create_relationship(hub["id"], spouse["id"], "CURRENT_SPOUSE", "2000-01-01",
                                  verify=True)
        claim = file_auxiliary_claim(spouse["id"], "SPOUSAL", "2026-06", rel["id"])

        resp = api.approve_claim(claim["id"], CS)
        validate_error(resp, ApiErrorId.ERR_SPOUSE_NOT_ENTITLED, 422)

        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "FILED"


class TestMarriageDurationRules:
    def test_current_spouse_under_one_year_marriage_rejected(self, api):
        """PRD §3.4: "`SPOUSAL` requires the covered worker to hold a `RETIREMENT`
        claim in `ENTITLED` or `SUSPENDED` status — otherwise
        `ERR_SPOUSE_NOT_ENTITLED` (422) — and the marriage must have lasted at
        least twelve months by `entitlement_month`, otherwise
        `ERR_MARRIAGE_DURATION_INSUFFICIENT` (422)."

        Married 2026-01-01, entitlement 2026-06: five months, short of twelve.

        Design: Corner/validations/current_spouse_under_one_year_marriage_rejected
        """
        hub = create_worker_with_awi_record(2019, 2023, full_name="Short Marriage Hub")
        hub_claim = file_claim(hub["id"], "RETIREMENT", "2026-06")
        approve_claim(hub_claim["id"])

        spouse = create_worker(full_name="Short Marriage Spouse")
        rel = create_relationship(hub["id"], spouse["id"], "CURRENT_SPOUSE", "2026-01-01",
                                  verify=True)
        claim = file_auxiliary_claim(spouse["id"], "SPOUSAL", "2026-06", rel["id"])

        resp = api.approve_claim(claim["id"], CS)
        validate_error(resp, ApiErrorId.ERR_MARRIAGE_DURATION_INSUFFICIENT, 422)

        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "FILED"

    def test_divorced_spouse_two_year_wait_rejected(self, api):
        """PRD §3.4: "When the covered worker holds no `ENTITLED` or `SUSPENDED`
        `RETIREMENT` claim, the divorced spouse may still be independently
        entitled, but only once `entitlement_month` is at least 24 months after
        the `divorce_date`; an earlier attempt is rejected with
        `ERR_DIVORCE_WAITING_PERIOD` (422)."

        Divorced 2025-06-01, entitlement 2026-06: twelve months after the
        divorce, short of twenty-four, with the covered worker not yet entitled.

        Design: Corner/validations/divorced_spouse_two_year_wait_rejected
        """
        covered = create_worker_with_awi_record(2019, 2023, full_name="Not Yet Entitled")
        ex = create_worker(full_name="Early Divorcee")
        rel = create_relationship(
            covered["id"], ex["id"], "DIVORCED_SPOUSE", "2010-01-01",
            divorce_date="2025-06-01", verify=True,
        )
        claim = file_auxiliary_claim(ex["id"], "DIVORCED_SPOUSAL", "2026-06", rel["id"])

        resp = api.approve_claim(claim["id"], CS)
        validate_error(resp, ApiErrorId.ERR_DIVORCE_WAITING_PERIOD, 422)

        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "FILED"
