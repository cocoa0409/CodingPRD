"""State machines that are not straight lines: parallel dimensions and a cycle.

PRD §3.3 on the membership row: "These are two genuinely independent state
dimensions carried on the same row, and neither is a function of the other."
"""

from test_helpers import (
    AccessStatus,
    DuesStatus,
    FacilityPosture,
    FindingSeverity,
    FindingStatus,
    fixtures as fx,
)
from test_helpers.test_users import (
    HEALTH_INSPECTOR,
    HEALTH_INSPECTOR_2,
    HEALTH_INSPECTOR_USER_ID,
    HEALTH_INSPECTOR_USER_ID_2,
    POOL_MANAGER,
)

FIRST_NOTE = "Log reconstructed from the DPD test tapes; staff retrained."
SECOND_NOTE = "Second submission: continuous DPD logging installed."


def _unpaid_membership(api):
    """A FAMILY membership created on a clock strictly after dues_due_date.

    Nothing is ever paid, so balance_due_cents stays positive and the billing
    checkpoint of PRD §3.1 finds the membership.
    """
    return fx.setup_club(
        api,
        clock_iso="2027-07-06T09:00:00Z",
        category="FAMILY",
        member_count=4,
        household_overrides={
            "primary_contact_name": "Alvarez Household",
            "address_line": "14 Poolside Lane",
            "prior_member": False,
        },
        join_date="2027-07-05",
        bond_payment_plan="INSTALLMENTS",
    )


class TestMembershipDuesAndAccessAdvanceIndependently:
    """Three triggers, four distinct (dues_status, access_status) pairs."""

    def test_the_billing_checkpoint_moves_dues_and_leaves_access_alone(self, api):
        """DELINQUENT on the money dimension, still ACTIVE at the gate.

        PRD §3.1: "Step four ages the money: every membership whose
        `dues_status` is `INVOICED`, whose `balance_due_cents` is greater than 0,
        and whose season's `dues_due_date` is strictly earlier than the effective
        date moves `dues_status` to `DELINQUENT` — the due date itself is not
        delinquent."

        Design: Difficulty/non_linear_state_machine/membership_dues_and_access_dimensions_evolve_independently
        """
        ctx = _unpaid_membership(api)
        created = ctx["membership"]
        assert created["dues_status"] == DuesStatus.UNBILLED
        assert created["access_status"] == AccessStatus.PENDING

        invoiced = fx.invoice_membership(api, created["id"])
        assert invoiced["dues_status"] == DuesStatus.INVOICED
        assert invoiced["access_status"] == AccessStatus.ACTIVE
        assert invoiced["balance_due_cents"] > 0

        fx.run_billing_run(api, ctx["season"]["id"])
        aged = fx.read_membership(api, created["id"])
        assert aged["dues_status"] == DuesStatus.DELINQUENT
        assert aged["access_status"] == AccessStatus.ACTIVE

    def test_only_the_write_off_couples_the_two_dimensions(self, api):
        """A dues transition drags the access dimension with it, once.

        PRD §3.4: "In the same request the access dimension moves `ACTIVE →
        SUSPENDED` when it was `ACTIVE`, which drags the full suspension cascade
        of §3.9 behind it: every swim-team registration of that membership in
        `PENDING`, `CONFIRMED` or `WAITLISTED` is revoked and every future
        confirmed reservation is cancelled as `CANCELLED_BY_SUSPENSION`."

        Design: Difficulty/non_linear_state_machine/membership_dues_and_access_dimensions_evolve_independently
        """
        ctx = _unpaid_membership(api)
        membership_id = ctx["membership"]["id"]
        fx.invoice_membership(api, membership_id)
        fx.run_billing_run(api, ctx["season"]["id"])

        written_off = fx.write_off_membership(api, membership_id)

        assert written_off["dues_status"] == DuesStatus.WRITTEN_OFF
        assert written_off["access_status"] == AccessStatus.SUSPENDED
        assert written_off["balance_due_cents"] == 0

    def test_the_four_combined_states_are_all_distinct_and_versioned(self, api):
        """The combined state is not a function of either dimension alone.

        PRD §3.3: "a membership can be `PAID` on the money dimension while
        `SUSPENDED` on the access dimension, or `DELINQUENT` on the money
        dimension while still `ACTIVE` on the access dimension."

        Design: Difficulty/non_linear_state_machine/membership_dues_and_access_dimensions_evolve_independently
        """
        ctx = _unpaid_membership(api)
        membership_id = ctx["membership"]["id"]

        observations = [ctx["membership"]]
        observations.append(fx.invoice_membership(api, membership_id))
        fx.run_billing_run(api, ctx["season"]["id"])
        observations.append(fx.read_membership(api, membership_id))
        observations.append(fx.write_off_membership(api, membership_id))

        pairs = [(m["dues_status"], m["access_status"]) for m in observations]
        assert pairs == [
            (DuesStatus.UNBILLED, AccessStatus.PENDING),
            (DuesStatus.INVOICED, AccessStatus.ACTIVE),
            (DuesStatus.DELINQUENT, AccessStatus.ACTIVE),
            (DuesStatus.WRITTEN_OFF, AccessStatus.SUSPENDED),
        ]
        assert len(set(pairs)) == 4

        versions = [m["version"] for m in observations]
        assert versions == sorted(set(versions))


def _minor_finding(api):
    """One OPEN 2027 season carrying a single MINOR finding from hi-001."""
    season = fx.setup_open_season(api, clock_iso="2027-06-14T09:00:00Z")
    finding = fx.file_finding(
        api, season["id"], FindingSeverity.MINOR, headers=HEALTH_INSPECTOR,
        inspected_on="2027-06-12", finding_code="PH-LOG-INCOMPLETE",
        narrative="Chlorine log missing two afternoon readings.",
    )
    return season, finding


class TestInspectionFindingRemediationReopenCycle:
    """One dimension that revisits a state it has already occupied."""

    def test_remediation_submitted_is_occupied_twice(self, api):
        """OPEN, REMEDIATION_SUBMITTED, REOPENED, REMEDIATION_SUBMITTED, closed.

        PRD §3.1: "the pool manager may then submit again, and the
        `REMEDIATION_SUBMITTED → REOPENED → REMEDIATION_SUBMITTED` cycle may
        repeat without limit."

        Design: Difficulty/non_linear_state_machine/inspection_finding_remediation_reopen_cycle
        """
        season, finding = _minor_finding(api)
        visited = [finding["status"]]

        visited.append(fx.transition_finding(
            api, finding["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=FIRST_NOTE,
        )["status"])
        visited.append(fx.transition_finding(
            api, finding["id"], FindingStatus.REOPENED, HEALTH_INSPECTOR,
        )["status"])
        visited.append(fx.transition_finding(
            api, finding["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=SECOND_NOTE,
        )["status"])
        visited.append(fx.transition_finding(
            api, finding["id"], FindingStatus.VERIFIED_CLOSED,
            HEALTH_INSPECTOR_2,
        )["status"])

        assert visited == [
            FindingStatus.OPEN,
            FindingStatus.REMEDIATION_SUBMITTED,
            FindingStatus.REOPENED,
            FindingStatus.REMEDIATION_SUBMITTED,
            FindingStatus.VERIFIED_CLOSED,
        ]
        assert visited.count(FindingStatus.REMEDIATION_SUBMITTED) == 2

    def test_reopen_count_rises_only_on_the_rejection_edge(self, api):
        """The loop counter proves the machine went round rather than forward.

        PRD §3.1: "The inspector may reject the fix, moving the finding
        `REMEDIATION_SUBMITTED → REOPENED`, which raises `reopen_count` by one
        and leaves the posture unchanged because the finding is still open."

        Design: Difficulty/non_linear_state_machine/inspection_finding_remediation_reopen_cycle
        """
        season, finding = _minor_finding(api)
        assert finding["reopen_count"] == 0

        submitted = fx.transition_finding(
            api, finding["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=FIRST_NOTE,
        )
        assert submitted["reopen_count"] == 0

        reopened = fx.transition_finding(
            api, finding["id"], FindingStatus.REOPENED, HEALTH_INSPECTOR,
        )
        assert reopened["reopen_count"] == 1

        resubmitted = fx.transition_finding(
            api, finding["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=SECOND_NOTE,
        )
        assert resubmitted["reopen_count"] == 1
        assert resubmitted["remediation_note"] == SECOND_NOTE

    def test_the_verifier_differs_from_the_recorder_on_the_closing_hop(self, api):
        """hi-002 closes what hi-001 filed, and the finding is terminal.

        PRD §3.1: "Only the inspector may verify-close: moving
        `REMEDIATION_SUBMITTED → VERIFIED_CLOSED` requires that `X-User-ID`
        differ from the finding's `recorded_by_user_id`, stamps
        `verified_by_user_id` with the acting user, recomputes both finding
        counters, re-derives the posture."

        Design: Difficulty/non_linear_state_machine/inspection_finding_remediation_reopen_cycle
        """
        season, finding = _minor_finding(api)
        assert finding["recorded_by_user_id"] == HEALTH_INSPECTOR_USER_ID

        fx.transition_finding(
            api, finding["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=FIRST_NOTE,
        )
        closed = fx.transition_finding(
            api, finding["id"], FindingStatus.VERIFIED_CLOSED,
            HEALTH_INSPECTOR_2,
        )

        assert closed["status"] == FindingStatus.VERIFIED_CLOSED
        assert closed["verified_by_user_id"] == HEALTH_INSPECTOR_USER_ID_2
        assert closed["verified_by_user_id"] != closed["recorded_by_user_id"]

    def test_a_minor_finding_never_moves_the_posture_around_the_loop(self, api):
        """Posture stays OPEN at every observation of the cycle.

        PRD §3.1: "Findings of `severity` `MINOR` are counted in neither and
        never affect posture at all."

        Design: Difficulty/non_linear_state_machine/inspection_finding_remediation_reopen_cycle
        """
        season, finding = _minor_finding(api)
        postures = []

        def observe():
            fresh = fx.read_season(api, season["id"])
            postures.append(fresh["facility_posture"])
            assert fresh["open_critical_finding_count"] == 0
            assert fresh["open_major_finding_count"] == 0
            assert fresh["closure_started_at"] is None

        observe()
        fx.transition_finding(
            api, finding["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=FIRST_NOTE,
        )
        observe()
        fx.transition_finding(
            api, finding["id"], FindingStatus.REOPENED, HEALTH_INSPECTOR,
        )
        observe()
        fx.transition_finding(
            api, finding["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=SECOND_NOTE,
        )
        observe()
        fx.transition_finding(
            api, finding["id"], FindingStatus.VERIFIED_CLOSED,
            HEALTH_INSPECTOR_2,
        )
        observe()

        assert postures == [FacilityPosture.OPEN] * 5
