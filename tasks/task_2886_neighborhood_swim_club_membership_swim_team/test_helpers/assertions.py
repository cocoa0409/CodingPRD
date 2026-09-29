"""Per-entity shape assertions and domain invariant checkers.

The ``assert_common_fields`` helper enforces PRD §2.4 for every entity:
"``id``, ``created_at``, ``updated_at`` and ``version``" with "``version``, an
integer that begins at 1 when the row is created and increases by exactly 1 on
every mutation of that row."
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    BATHERS_PER_GUARD,
    MIN_GUARD_COUNT,
    PER_MEMBERSHIP_RESERVE_CONTRIBUTION_CENTS,
    VOLUNTEER_CREDIT_VALUES,
    ZONE_BASE_FEE_CENTS,
)
from .types import (
    AccessStatus,
    BondStatus,
    DuesStatus,
    FacilityPosture,
    HouseholdStanding,
    ProjectStatus,
    SeasonStatus,
)

_MONEY_FIELDS_MUST_BE_INT = (
    "PRD §2.6: 'All money in this system is an integer number of cents. There "
    "are no fractional-cent fields, no floating-point money in responses'"
)


# ─── Common shape ─────────────────────────────────────

def assert_common_fields(entity: Dict[str, Any],
                         expected_version: Optional[int] = None) -> None:
    """Assert the four fields PRD §2.4 puts on every entity."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"id must be a bare UUID string with no type prefix: {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant: {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), (
        f"version must be an integer: {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, "version begins at 1 when the row is created"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_money_integer(entity: Dict[str, Any], *fields: str) -> None:
    """Assert each named money field is an integer number of cents."""
    for field in fields:
        value = entity.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}. "
            f"{_MONEY_FIELDS_MUST_BE_INT}"
        )


def assert_no_pagination_meta(meta: Dict[str, Any]) -> None:
    """PRD §2.3: "Single-resource reads carry neither of those four fields"."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, (
            f"Single-resource reads must not carry meta.{field}"
        )


# ─── Season ───────────────────────────────────────────

def assert_season(season: Dict[str, Any],
                  expected_status: Optional[str] = None,
                  expected_posture: Optional[str] = None) -> None:
    assert_common_fields(season)
    assert isinstance(season["year"], int)
    assert season["status"] in (
        SeasonStatus.PLANNED, SeasonStatus.OPEN, SeasonStatus.CLOSED
    )
    assert season["facility_posture"] in (
        FacilityPosture.OPEN, FacilityPosture.RESTRICTED, FacilityPosture.CLOSED
    )
    assert_money_integer(
        season, "reserve_contributions_cents", "reserve_unallocated_cents"
    )
    assert isinstance(season["open_critical_finding_count"], int)
    assert isinstance(season["open_major_finding_count"], int)
    if expected_status is not None:
        assert season["status"] == expected_status, (
            f"Expected season status {expected_status}, got {season['status']}"
        )
    if expected_posture is not None:
        assert season["facility_posture"] == expected_posture, (
            f"Expected facility_posture {expected_posture}, "
            f"got {season['facility_posture']}"
        )


def assert_season_born_clean(season: Dict[str, Any]) -> None:
    """PRD §3.1: a newly created season's pinned birth state."""
    assert season["status"] == SeasonStatus.PLANNED
    assert season["facility_posture"] == FacilityPosture.CLOSED
    assert season["open_critical_finding_count"] == 0
    assert season["open_major_finding_count"] == 0
    assert season["closure_started_at"] is None
    assert season["reserve_contributions_cents"] == 0
    assert season["reserve_unallocated_cents"] == 0
    assert season["version"] == 1


# ─── Membership category ──────────────────────────────

def assert_membership_category(category: Dict[str, Any]) -> None:
    assert_common_fields(category)
    assert_money_integer(
        category, "bond_cents", "initiation_fee_cents", "seasonal_dues_cents"
    )
    for flag in ("waitlist_required", "proration_allowed", "party_privileges"):
        assert isinstance(category[flag], bool), f"{flag} must be a boolean"
    assert category["max_household_size"] >= 1


# ─── Household ────────────────────────────────────────

def assert_household(household: Dict[str, Any],
                     expected_standing: Optional[str] = None) -> None:
    assert_common_fields(household)
    assert household["standing"] in (
        HouseholdStanding.GOOD_STANDING, HouseholdStanding.PROBATION,
        HouseholdStanding.SUSPENDED, HouseholdStanding.EXPELLED,
    )
    assert household["bond_status"] in (
        BondStatus.NONE, BondStatus.INSTALLMENTS,
        BondStatus.PAID, BondStatus.TRANSFERRED,
    )
    assert_money_integer(
        household, "bond_paid_cents", "guest_fee_owed_cents",
        "party_charges_owed_cents", "account_credit_cents",
    )
    assert_guest_pass_conservation(household)
    if expected_standing is not None:
        assert household["standing"] == expected_standing, (
            f"Expected standing {expected_standing}, got {household['standing']}"
        )


def assert_household_born_clean(household: Dict[str, Any]) -> None:
    """PRD §3.2: the ledger a freshly registered household is born with."""
    assert household["standing"] == HouseholdStanding.GOOD_STANDING
    assert household["conduct_points"] == 0
    assert household["bond_paid_cents"] == 0
    assert household["guest_pass_allotment_granted"] == 0
    assert household["guest_passes_consumed"] == 0
    assert household["guest_pass_balance"] == 0
    assert household["guest_fee_owed_cents"] == 0
    assert household["party_charges_owed_cents"] == 0
    assert household["account_credit_cents"] == 0
    assert household["version"] == 1


def assert_guest_pass_conservation(household: Dict[str, Any]) -> None:
    """PRD §3.5: "a household's ``guest_pass_balance`` plus its
    ``guest_passes_consumed`` always equals its
    ``guest_pass_allotment_granted``"."""
    balance = household["guest_pass_balance"]
    consumed = household["guest_passes_consumed"]
    granted = household["guest_pass_allotment_granted"]
    assert balance + consumed == granted, (
        f"Guest-pass conservation broken: balance {balance} + consumed "
        f"{consumed} != granted {granted}"
    )


def assert_household_pass_ledger(household: Dict[str, Any], granted: int,
                                 consumed: int, balance: int,
                                 fee_owed_cents: int) -> None:
    assert household["guest_pass_allotment_granted"] == granted
    assert household["guest_passes_consumed"] == consumed
    assert household["guest_pass_balance"] == balance
    assert household["guest_fee_owed_cents"] == fee_owed_cents
    assert_guest_pass_conservation(household)


# ─── Waitlist entry ───────────────────────────────────

def assert_waitlist_entry(entry: Dict[str, Any],
                          expected_status: Optional[str] = None) -> None:
    assert_common_fields(entry)
    assert is_valid_uuid(entry["household_id"])
    assert is_valid_uuid(entry["membership_category_id"])
    assert isinstance(entry["priority_tier_rank"], int)
    assert isinstance(entry["deferral_count"], int)
    assert is_iso8601_timestamp(entry["queue_key_at"])
    if expected_status is not None:
        assert entry["status"] == expected_status, (
            f"Expected waitlist status {expected_status}, got {entry['status']}"
        )


# ─── Membership ───────────────────────────────────────

def assert_membership(membership: Dict[str, Any],
                      expected_dues_status: Optional[str] = None,
                      expected_access_status: Optional[str] = None) -> None:
    assert_common_fields(membership)
    assert membership["dues_status"] in (
        DuesStatus.UNBILLED, DuesStatus.INVOICED, DuesStatus.DELINQUENT,
        DuesStatus.PAID, DuesStatus.WRITTEN_OFF,
    )
    assert membership["access_status"] in (
        AccessStatus.PENDING, AccessStatus.ACTIVE, AccessStatus.SUSPENDED,
        AccessStatus.LAPSED, AccessStatus.TERMINATED,
    )
    assert_money_integer(
        membership, "assessed_dues_cents", "initiation_fee_cents",
        "bond_installment_cents", "swim_team_fee_cents", "late_penalty_cents",
        "invoice_total_cents", "amount_paid_cents", "balance_due_cents",
        "volunteer_buyout_cents",
    )
    if expected_dues_status is not None:
        assert membership["dues_status"] == expected_dues_status, (
            f"Expected dues_status {expected_dues_status}, "
            f"got {membership['dues_status']}"
        )
    if expected_access_status is not None:
        assert membership["access_status"] == expected_access_status, (
            f"Expected access_status {expected_access_status}, "
            f"got {membership['access_status']}"
        )


def assert_membership_born_unbilled(membership: Dict[str, Any]) -> None:
    """PRD §3.3: "A membership is born with ``dues_status`` ``UNBILLED`` and
    ``access_status`` ``PENDING``"."""
    assert membership["dues_status"] == DuesStatus.UNBILLED
    assert membership["access_status"] == AccessStatus.PENDING
    assert membership["version"] == 1


def assert_balance_identity(membership: Dict[str, Any]) -> None:
    """PRD §3.4: "``balance_due_cents`` is at all times the membership's
    ``invoice_total_cents`` plus its ``volunteer_buyout_cents`` minus its
    ``amount_paid_cents``, floored at 0 so it never goes negative"."""
    expected = max(
        0,
        membership["invoice_total_cents"]
        + membership["volunteer_buyout_cents"]
        - membership["amount_paid_cents"],
    )
    assert membership["balance_due_cents"] == expected, (
        f"balance_due_cents {membership['balance_due_cents']} != max(0, "
        f"invoice_total {membership['invoice_total_cents']} + buyout "
        f"{membership['volunteer_buyout_cents']} - paid "
        f"{membership['amount_paid_cents']}) = {expected}"
    )


def assert_invoice_lines(membership: Dict[str, Any], dues: int, initiation: int,
                         bond_installment: int, swim_team_fee: int,
                         late_penalty: int, invoice_total: int) -> None:
    """Assert the five ordered invoice lines and the total of PRD §3.4."""
    assert membership["assessed_dues_cents"] == dues, (
        f"Line 1 assessed_dues_cents: expected {dues}, "
        f"got {membership['assessed_dues_cents']}"
    )
    assert membership["initiation_fee_cents"] == initiation, (
        f"Line 2 initiation_fee_cents: expected {initiation}, "
        f"got {membership['initiation_fee_cents']}"
    )
    assert membership["bond_installment_cents"] == bond_installment, (
        f"Line 3 bond_installment_cents: expected {bond_installment}, "
        f"got {membership['bond_installment_cents']}"
    )
    assert membership["swim_team_fee_cents"] == swim_team_fee, (
        f"Line 4 swim_team_fee_cents: expected {swim_team_fee}, "
        f"got {membership['swim_team_fee_cents']}"
    )
    assert membership["late_penalty_cents"] == late_penalty, (
        f"Line 5 late_penalty_cents: expected {late_penalty}, "
        f"got {membership['late_penalty_cents']}"
    )
    assert membership["invoice_total_cents"] == invoice_total, (
        f"invoice_total_cents: expected {invoice_total}, "
        f"got {membership['invoice_total_cents']}"
    )
    assert (
        dues + initiation + bond_installment + swim_team_fee + late_penalty
        == invoice_total
    ), "The pinned expectation is internally inconsistent"
    assert_balance_identity(membership)


# ─── Guest visit ──────────────────────────────────────

def assert_guest_visit(visit: Dict[str, Any],
                       expected_status: Optional[str] = None) -> None:
    assert_common_fields(visit)
    assert isinstance(visit["is_weekend"], bool)
    assert isinstance(visit["passes_used"], int)
    assert_money_integer(visit, "fee_charged_cents")
    if expected_status is not None:
        assert visit["status"] == expected_status, (
            f"Expected visit status {expected_status}, got {visit['status']}"
        )


def assert_visit_settlement(visit: Dict[str, Any], passes_used: int,
                            fee_charged_cents: int, is_weekend: bool,
                            settlement_variant: str) -> None:
    assert visit["passes_used"] == passes_used, (
        f"passes_used: expected {passes_used}, got {visit['passes_used']}"
    )
    assert visit["fee_charged_cents"] == fee_charged_cents, (
        f"fee_charged_cents: expected {fee_charged_cents}, "
        f"got {visit['fee_charged_cents']}"
    )
    assert visit["is_weekend"] is is_weekend
    assert visit["settlement_variant"] == settlement_variant


# ─── Lifeguard / certification / shift ────────────────

def assert_lifeguard(guard: Dict[str, Any],
                     expected_employment_status: Optional[str] = None) -> None:
    assert_common_fields(guard)
    assert isinstance(guard["has_valid_lifeguard_cert"], bool)
    assert isinstance(guard["has_valid_cpr_cert"], bool)
    assert isinstance(guard["scheduled_hours"], (int, float))
    if expected_employment_status is not None:
        assert guard["employment_status"] == expected_employment_status, (
            f"Expected employment_status {expected_employment_status}, "
            f"got {guard['employment_status']}"
        )


def assert_certification(cert: Dict[str, Any],
                         expected_status: Optional[str] = None) -> None:
    assert_common_fields(cert)
    assert is_valid_uuid(cert["lifeguard_id"])
    if expected_status is not None:
        assert cert["status"] == expected_status, (
            f"Expected certification status {expected_status}, "
            f"got {cert['status']}"
        )


def assert_guard_shift(shift: Dict[str, Any],
                       expected_status: Optional[str] = None) -> None:
    assert_common_fields(shift)
    assert isinstance(shift["counts_toward_ratio"], bool)
    assert isinstance(shift["duration_hours"], (int, float))
    if expected_status is not None:
        assert shift["status"] == expected_status, (
            f"Expected shift status {expected_status}, got {shift['status']}"
        )


# ─── Swim team ────────────────────────────────────────

def assert_registration(reg: Dict[str, Any],
                        expected_status: Optional[str] = None) -> None:
    assert_common_fields(reg)
    assert isinstance(reg["squad_seq"], int) and reg["squad_seq"] >= 1
    assert_money_integer(reg, "assessed_fee_cents")
    if expected_status is not None:
        assert reg["status"] == expected_status, (
            f"Expected registration status {expected_status}, "
            f"got {reg['status']}"
        )


def assert_meet(meet: Dict[str, Any],
                expected_status: Optional[str] = None) -> None:
    assert_common_fields(meet)
    assert isinstance(meet["volunteer_slots_required"], int)
    assert isinstance(meet["volunteer_slots_filled"], int)
    assert_money_integer(meet, "understaffed_penalty_cents")
    if expected_status is not None:
        assert meet["status"] == expected_status, (
            f"Expected meet status {expected_status}, got {meet['status']}"
        )


def assert_volunteer_assignment(assignment: Dict[str, Any],
                                expected_status: Optional[str] = None) -> None:
    assert_common_fields(assignment)
    job_code = assignment["job_code"]
    assert job_code in VOLUNTEER_CREDIT_VALUES, f"Unknown job_code {job_code}"
    assert assignment["credit_value"] == VOLUNTEER_CREDIT_VALUES[job_code], (
        f"PRD §3.6 stamps credit_value "
        f"{VOLUNTEER_CREDIT_VALUES[job_code]} for {job_code}, "
        f"got {assignment['credit_value']}"
    )
    if expected_status is not None:
        assert assignment["status"] == expected_status, (
            f"Expected assignment status {expected_status}, "
            f"got {assignment['status']}"
        )


# ─── Party reservation ────────────────────────────────

def assert_party_reservation(res: Dict[str, Any],
                             expected_status: Optional[str] = None) -> None:
    assert_common_fields(res)
    assert_money_integer(
        res, "lifeguard_surcharge_cents", "base_facility_fee_cents",
        "guest_overage_fee_cents", "subtotal_cents", "member_discount_cents",
        "total_charge_cents", "refunded_cents",
    )
    assert res["base_facility_fee_cents"] == ZONE_BASE_FEE_CENTS[res["zone"]], (
        f"PRD §3.7 step five pins the {res['zone']} flat fee at "
        f"{ZONE_BASE_FEE_CENTS[res['zone']]}, got "
        f"{res['base_facility_fee_cents']}"
    )
    if expected_status is not None:
        assert res["status"] == expected_status, (
            f"Expected reservation status {expected_status}, "
            f"got {res['status']}"
        )


def assert_party_pricing(res: Dict[str, Any], projected_bather_load: int,
                         required_guard_count: int, duration_hours_ceil: int,
                         lifeguard_surcharge_cents: int,
                         base_facility_fee_cents: int,
                         guest_overage_fee_cents: int, subtotal_cents: int,
                         member_discount_cents: int,
                         total_charge_cents: int) -> None:
    """Assert all nine pinned steps of the PRD §3.7 pricing sequence."""
    assert res["projected_bather_load"] == projected_bather_load, (
        f"Step 1 projected_bather_load: expected {projected_bather_load}, "
        f"got {res['projected_bather_load']}"
    )
    assert res["required_guard_count"] == required_guard_count, (
        f"Step 2 required_guard_count: expected {required_guard_count}, "
        f"got {res['required_guard_count']}"
    )
    assert res["duration_hours_ceil"] == duration_hours_ceil, (
        f"Step 3 duration_hours_ceil: expected {duration_hours_ceil}, "
        f"got {res['duration_hours_ceil']}"
    )
    assert res["lifeguard_surcharge_cents"] == lifeguard_surcharge_cents, (
        f"Step 4 lifeguard_surcharge_cents: expected "
        f"{lifeguard_surcharge_cents}, got {res['lifeguard_surcharge_cents']}"
    )
    assert res["base_facility_fee_cents"] == base_facility_fee_cents, (
        f"Step 5 base_facility_fee_cents: expected {base_facility_fee_cents}, "
        f"got {res['base_facility_fee_cents']}"
    )
    assert res["guest_overage_fee_cents"] == guest_overage_fee_cents, (
        f"Step 6 guest_overage_fee_cents: expected {guest_overage_fee_cents}, "
        f"got {res['guest_overage_fee_cents']}"
    )
    assert res["subtotal_cents"] == subtotal_cents, (
        f"Step 7 subtotal_cents: expected {subtotal_cents}, "
        f"got {res['subtotal_cents']}"
    )
    assert res["member_discount_cents"] == member_discount_cents, (
        f"Step 9 member_discount_cents: expected {member_discount_cents}, "
        f"got {res['member_discount_cents']}"
    )
    assert res["total_charge_cents"] == total_charge_cents, (
        f"Step 9 total_charge_cents: expected {total_charge_cents}, "
        f"got {res['total_charge_cents']}"
    )
    assert (
        base_facility_fee_cents + guest_overage_fee_cents
        + lifeguard_surcharge_cents == subtotal_cents
    ), "The pinned subtotal is internally inconsistent"
    assert subtotal_cents - member_discount_cents == total_charge_cents, (
        "The pinned total is internally inconsistent"
    )


# ─── Inspection finding / conduct case ────────────────

def assert_inspection_finding(finding: Dict[str, Any],
                              expected_status: Optional[str] = None) -> None:
    assert_common_fields(finding)
    assert isinstance(finding["reopen_count"], int)
    if expected_status is not None:
        assert finding["status"] == expected_status, (
            f"Expected finding status {expected_status}, "
            f"got {finding['status']}"
        )


def assert_conduct_case(case: Dict[str, Any],
                        expected_status: Optional[str] = None) -> None:
    assert_common_fields(case)
    assert isinstance(case["points_assessed"], int)
    assert isinstance(case["appeal_count"], int)
    if expected_status is not None:
        assert case["status"] == expected_status, (
            f"Expected case status {expected_status}, got {case['status']}"
        )


# ─── Capital project ──────────────────────────────────

def assert_capital_project(project: Dict[str, Any],
                           expected_status: Optional[str] = None) -> None:
    assert_common_fields(project)
    assert_money_integer(project, "budget_cents", "funded_cents")
    if expected_status is not None:
        assert project["status"] == expected_status, (
            f"Expected project status {expected_status}, "
            f"got {project['status']}"
        )


def assert_reserve_identity(season: Dict[str, Any],
                            projects: List[Dict[str, Any]]) -> None:
    """PRD §3.10: "``reserve_unallocated_cents`` plus the sum of
    ``funded_cents`` over the season's capital projects in ``FUNDED``,
    ``IN_PROGRESS`` or ``COMPLETED`` always equals
    ``reserve_contributions_cents``"."""
    allocated = sum(
        p["funded_cents"] for p in projects
        if p["status"] in (
            ProjectStatus.FUNDED, ProjectStatus.IN_PROGRESS,
            ProjectStatus.COMPLETED,
        )
    )
    assert season["reserve_unallocated_cents"] + allocated == \
        season["reserve_contributions_cents"], (
        f"Reserve identity broken: unallocated "
        f"{season['reserve_unallocated_cents']} + allocated {allocated} != "
        f"contributions {season['reserve_contributions_cents']}"
    )


def assert_reserve_counters(season: Dict[str, Any], contributions: int,
                            unallocated: int) -> None:
    assert season["reserve_contributions_cents"] == contributions, (
        f"reserve_contributions_cents: expected {contributions}, "
        f"got {season['reserve_contributions_cents']}"
    )
    assert season["reserve_unallocated_cents"] == unallocated, (
        f"reserve_unallocated_cents: expected {unallocated}, "
        f"got {season['reserve_unallocated_cents']}"
    )


def expected_per_membership_contribution(count: int) -> int:
    """PRD §3.4 / §3.10: 5000 cents booked once per membership reaching PAID."""
    return count * PER_MEMBERSHIP_RESERVE_CONTRIBUTION_CENTS


# ─── Staffing window ──────────────────────────────────

def assert_staffing_window(window: Dict[str, Any], bather_load: int,
                           required_guard_count: int,
                           scheduled_guard_count: int,
                           compliant: bool) -> None:
    assert window["bather_load"] == bather_load, (
        f"bather_load: expected {bather_load}, got {window['bather_load']}"
    )
    assert window["required_guard_count"] == required_guard_count, (
        f"required_guard_count: expected {required_guard_count}, "
        f"got {window['required_guard_count']}"
    )
    assert window["scheduled_guard_count"] == scheduled_guard_count, (
        f"scheduled_guard_count: expected {scheduled_guard_count}, "
        f"got {window['scheduled_guard_count']}"
    )
    assert window["compliant"] is compliant, (
        f"compliant: expected {compliant}, got {window['compliant']}"
    )
    assert window["scheduled_guard_count"] >= window["required_guard_count"] \
        or not window["compliant"], (
        "PRD §3.8: the verdict is compliant when the covering guard count is "
        "greater than or equal to the required count"
    )


def expected_required_guards(bather_load: int,
                             whole_facility: bool = False) -> int:
    """PRD §3.8 requirement formula, used to cross-check a pinned figure."""
    ratio_guards = -(-bather_load // BATHERS_PER_GUARD)
    base = max(ratio_guards, MIN_GUARD_COUNT)
    return base + (1 if whole_facility else 0)


# ─── Ordering ─────────────────────────────────────────

def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """PRD §2.3: "List results are ordered by ``created_at`` ascending"."""
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), (
        f"List is not ordered by created_at ascending: {stamps}"
    )


def assert_same_projection(first: Dict[str, Any], second: Dict[str, Any],
                           ignore: Optional[List[str]] = None) -> None:
    """Assert two reads of the same row agree field for field."""
    skip = set(ignore or [])
    keys = set(first) | set(second)
    mismatches = {
        k: (first.get(k), second.get(k))
        for k in keys
        if k not in skip and first.get(k) != second.get(k)
    }
    assert not mismatches, f"Projections diverge on {mismatches}"
