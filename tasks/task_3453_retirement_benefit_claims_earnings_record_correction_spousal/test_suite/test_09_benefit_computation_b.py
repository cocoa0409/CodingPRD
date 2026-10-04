"""Claiming-age boundaries, the delayed-credit cap at 70, survivor reduction,
and immediate read-after-write consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_relationship,
    create_worker,
    create_worker_with_awi_record,
    file_claim,
    make_claimant_headers,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestClaimingAgeBoundary:
    def test_claiming_age_exactly_62_is_eligible(self, api):
        """PRD §3.4: "the claimant's `claiming_age_months` — their age in whole
        months at `entitlement_month` — must be at least 744 (exactly 62 years)
        for `RETIREMENT`, `SPOUSAL`, and `DIVORCED_SPOUSAL`, and at least 720 (60
        years) for `SURVIVOR`; claiming after age 70 — more than 840 months — is
        likewise rejected, in both cases with `ERR_AGE_INELIGIBLE` (422)."

        Born 1964-06, entitlement 2026-06: exactly 744 months — the boundary is
        inclusive.

        Design: Difficulty/boundary_precision_check/claiming_age_exactly_62_boundary
        """
        worker = create_worker(full_name="Boundary A", birth_year=1964, birth_month=6)
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])

        assert entitled["status"] == "ENTITLED"
        assert entitled["claiming_age_months"] == 744

    def test_claiming_age_743_rejected(self, api):
        """PRD §3.4: "the claimant's `claiming_age_months` — their age in whole
        months at `entitlement_month` — must be at least 744 (exactly 62 years)
        for `RETIREMENT`, `SPOUSAL`, and `DIVORCED_SPOUSAL`, and at least 720 (60
        years) for `SURVIVOR`; claiming after age 70 — more than 840 months — is
        likewise rejected, in both cases with `ERR_AGE_INELIGIBLE` (422)."

        Born 1964-07, entitlement 2026-06: 743 months — one month short.

        Design: Difficulty/boundary_precision_check/claiming_age_exactly_62_boundary
        """
        worker = create_worker(full_name="Boundary B", birth_year=1964, birth_month=7)
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")

        resp = api.approve_claim(claim["id"], CS)
        validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE, 422)

        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "FILED"


class TestDelayedCreditsAndSurvivor:
    def test_claiming_at_exactly_70_uses_full_drc_cap(self, api):
        """PRD §3.4: "claiming after age 70 — more than 840 months — is likewise
        rejected, in both cases with `ERR_AGE_INELIGIBLE` (422)."
        PRD §3.5: "When the claimant is at or past full retirement age, the factor
        is one, increased by one one-hundred-fiftieth for each delayed-credit
        month: the months after full retirement age up to the month the claimant
        reaches 840 months (age 70), plus the `drc_months` accrued during
        voluntary suspension (§3.6)."

        Claiming at exactly 840 months: 36 delayed months, factor 1 + 36/150 =
        1.24; monthly = dime_floor(12,510 * 1.24) = 15,510 on PIA 12,510.

        Design: Corner/calculations/claiming_at_exactly_70_uses_full_drc_cap
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Age Seventy")
        claim = file_claim(worker["id"], "RETIREMENT", "2034-06")
        entitled = approve_claim(claim["id"])

        assert entitled["status"] == "ENTITLED"
        assert entitled["claiming_age_months"] == 840
        assert entitled["reduction_months"] == 0
        assert entitled["monthly_benefit_cents"] == 15_510

    def test_survivor_benefit_reduction_at_age_60(self, api):
        """PRD §3.5: "The amount is reduced by half of one percent for each month
        the claimant's age at entitlement falls below the survivor full retirement
        age of 804 months (67 years), dime-floored once; the government pension
        offset then applies exactly as in the fourth spousal step above."
        PRD §3.4: "`SURVIVOR` requires the covered worker to be `DECEASED`,
        otherwise `ERR_WORKER_NOT_DECEASED` (422), and the marriage must have
        lasted at least nine months measured at the covered worker's
        `death_date`, otherwise `ERR_MARRIAGE_DURATION_INSUFFICIENT`."

        Widow born 1966-06 claiming at 2026-06 (exactly 720 months): factor
        1 - 84*0.005 = 0.58; monthly = dime_floor(20,880 * 0.58) = 12,110.

        Design: Corner/calculations/survivor_benefit_reduction_at_age_60
        """
        covered = create_worker_with_awi_record(2019, 2023, full_name="Dead Worker")
        own_claim = file_claim(covered["id"], "RETIREMENT", "2026-06")
        approve_claim(own_claim["id"])
        validate_success(api.report_death(covered["id"], "2026-08-20", CS))

        widow = create_worker(full_name="Widow", birth_year=1966, birth_month=6)
        rel = create_relationship(covered["id"], widow["id"], "WIDOW", "2010-01-01")
        validate_success(api.verify_relationship(rel["id"], CS))

        claim = file_claim(
            widow["id"], "SURVIVOR", "2026-06", relationship_id=rel["id"]
        )
        entitled = approve_claim(claim["id"])

        assert entitled["status"] == "ENTITLED"
        assert entitled["claiming_age_months"] == 720
        assert entitled["monthly_benefit_cents"] == 12_110


class TestImmediateConsistency:
    def test_immediate_visibility_of_mutation_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §2.8: "Every cascade hop mutates the affected record directly, exactly
        as if the change had been requested on that record itself".

        The approve response itself carries the fully computed claim; a follow-up
        read returns identical values.

        Design: Corner/consistency_model/immediate_visibility_of_mutation_in_same_response
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Immediate")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")

        entitled = approve_claim(claim["id"])
        assert entitled["status"] == "ENTITLED"
        assert entitled["monthly_benefit_cents"] == 8_750

        fetched = validate_success(api.get_claim(claim["id"], CS))
        assert fetched["status"] == entitled["status"]
        assert fetched["monthly_benefit_cents"] == entitled["monthly_benefit_cents"]
        assert fetched["pia_cents"] == entitled["pia_cents"]
        assert fetched["version"] == entitled["version"] == 2
