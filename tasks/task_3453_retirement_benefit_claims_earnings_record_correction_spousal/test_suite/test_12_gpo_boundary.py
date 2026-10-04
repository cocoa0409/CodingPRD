"""Government pension offset boundary: the offset exactly cancelling the spousal
excess versus leaving a 10-cent remainder.

Each leg uses its own covered worker, so each record carries exactly one
auxiliary claim and the family maximum never binds (own 14,610 + excess 10,440
= 25,050 <= FMAX 31,320) — the excess is exactly 10,440 in both legs, isolating
the GPO cents boundary the instance targets.
"""
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
    get_claim,
    list_recomputation_events,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


def _setup_spousal_at_fra(api, relationship_type, marriage_date, divorce_date=None):
    """Covered worker (PIA 20,880, RETIREMENT ENTITLED at 2026-06, monthly
    14,610); spouse with no earnings and a verified relationship; SPOUSAL /
    DIVORCED_SPOUSAL claim entitled 2031-06 at the spouse's FRA, approved while
    the pension is still 0. Returns (spouse, spousal_claim_as_approved)."""
    hub = create_worker_with_awi_record(2019, 2023, full_name="GPO Worker")
    hub_claim = file_claim(hub["id"], "RETIREMENT", "2026-06")
    approve_claim(hub_claim["id"])

    spouse = create_worker(full_name="Pension Spouse")
    rel = create_relationship(
        hub["id"], spouse["id"], relationship_type, marriage_date,
        divorce_date=divorce_date, verify=True,
    )
    claim = file_auxiliary_claim(spouse["id"],
                                 "SPOUSAL" if relationship_type == "CURRENT_SPOUSE" else "DIVORCED_SPOUSAL",
                                 "2031-06", rel["id"])
    entitled = approve_claim(claim["id"])
    assert entitled["monthly_benefit_cents"] == 10_440, "setup: excess must be 10,440 pre-GPO"
    return spouse, entitled


class TestGpoOffsetBoundary:
    def test_gpo_offset_exactly_cancels_spousal_excess(self, api):
        """PRD §3.5: "fourth, the government pension offset — two-thirds of the
        claimant's own `noncovered_pension_monthly_cents`, dime-floored — is
        subtracted, and the claim's `monthly_benefit_cents` is the remainder,
        floored at zero."
        PRD §3.1: "The write recomputes the worker's own `ENTITLED` or
        `SUSPENDED` claims — because the windfall elimination provision depends
        on the pension — and every auxiliary claim where this worker is the
        claimant, because the government pension offset depends on it."

        Pension 15,660: offset = dime_floor(2/3 * 15,660) = 10,440 == excess
        10,440, so the payable benefit drops to exactly 0 while the claim stays
        ENTITLED.

        Design: Difficulty/boundary_precision_check/gpo_offset_exactly_cancels_spousal_excess
        """
        spouse, entitled = _setup_spousal_at_fra(api, "CURRENT_SPOUSE", "2000-01-01")

        patched = validate_success(
            api.patch_worker(
                spouse["id"],
                {
                    "noncovered_pension_monthly_cents": 15_660,
                    "noncovered_pension_start_month": "2030-01",
                    "expected_worker_version": spouse["version"],
                },
                CS,
            )
        )
        assert patched["noncovered_pension_monthly_cents"] == 15_660

        claim = get_claim(entitled["id"])
        assert claim["status"] == "ENTITLED"
        assert claim["monthly_benefit_cents"] == 0, "offset 10,440 == excess 10,440"

        events = list_recomputation_events(entitled["id"])
        assert len(events) == 1
        event = events[0]
        assert event["trigger"] == "PENSION_UPDATED"
        assert event["old_monthly_benefit_cents"] == 10_440
        assert event["new_monthly_benefit_cents"] == 0
        assert event["retro_delta_cents"] == 0, "no payments yet, so no retro delta"
        assert event["resolution"] == "NONE"

    def test_gpo_offset_one_cent_less_leaves_ten_cents(self, api):
        """PRD §3.5: "fourth, the government pension offset — two-thirds of the
        claimant's own `noncovered_pension_monthly_cents`, dime-floored — is
        subtracted, and the claim's `monthly_benefit_cents` is the remainder,
        floored at zero."

        Pension 15,659: offset = dime_floor(2/3 * 15,659) = 10,430, leaving
        10,440 - 10,430 = 10 cents payable.

        Design: Difficulty/boundary_precision_check/gpo_offset_exactly_cancels_spousal_excess
        """
        spouse, entitled = _setup_spousal_at_fra(
            api, "DIVORCED_SPOUSE", "1990-01-01", divorce_date="2000-01-01"
        )

        validate_success(
            api.patch_worker(
                spouse["id"],
                {
                    "noncovered_pension_monthly_cents": 15_659,
                    "noncovered_pension_start_month": "2030-01",
                    "expected_worker_version": spouse["version"],
                },
                CS,
            )
        )

        claim = get_claim(entitled["id"])
        assert claim["status"] == "ENTITLED"
        assert claim["monthly_benefit_cents"] == 10, "offset 10,430 vs excess 10,440"
