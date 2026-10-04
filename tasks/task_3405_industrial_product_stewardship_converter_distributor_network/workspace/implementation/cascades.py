"""Cascade, bubble-up and compensation logic (PRD §2.10, §3.6-§3.9).

Every row touched by a cascade is itself mutated: updated_at refreshes from the
logical clock and version increments (store.touch). Accrual recomputation bumps
the accrual only when a recomputed value actually changes.
"""

import calcs
import store
from store import STORE


def _sorted(rows):
    return sorted(rows, key=store.sort_key)


def flag_order(order, report_id):
    """CLEAR -> FLAGGED on the compliance dimension. fulfillment must not be
    CANCELLED (callers pre-filter). Returns True when the order transitioned."""
    if order["compliance_status"] != "CLEAR":
        return False
    order["compliance_status"] = "FLAGGED"
    order["flagged_by_report_id"] = report_id
    store.touch(order)
    return True


def unflag_order(order):
    order["compliance_status"] = "CLEAR"
    order["flagged_by_report_id"] = None
    store.touch(order)


def recompute_provisional_accruals(formulation_id, converter_id, distributor_id):
    """Recompute provisional_amount_cents and excluded_order_count on every
    PROVISIONAL accrual whose program matches (formulation, partner). Fires on
    order SHIP events and on FLAG/UNFLAG events (PRD §3.7)."""
    for program in STORE["programs"].values():
        if program["formulation_id"] != formulation_id:
            continue
        if program["status"] != "ACTIVE":
            continue
        if converter_id is not None:
            if program["converter_id"] != converter_id:
                continue
        elif distributor_id is not None:
            if program["distributor_id"] != distributor_id:
                continue
        else:
            continue
        accrual = accrual_for_program(program["id"])
        if accrual is None or accrual["status"] != "PROVISIONAL":
            continue
        amount, excluded = calcs.rebate_accrual_amount(program, final=False)
        if (amount != accrual["provisional_amount_cents"]
                or excluded != accrual["excluded_order_count"]):
            accrual["provisional_amount_cents"] = amount
            accrual["excluded_order_count"] = excluded
            store.touch(accrual)


def accrual_for_program(program_id):
    for accrual in STORE["accruals"].values():
        if accrual["program_id"] == program_id:
            return accrual
    return None


def _flag_and_recompute(order, report_id):
    if flag_order(order, report_id):
        recompute_provisional_accruals(
            order["formulation_id"], order["converter_id"], order["distributor_id"])


# ---------------------------------------------------------------------------
# Converter suspension cascade (manual suspend, §3.3): in-flight orders
# (PENDING/ALLOCATED, CLEAR) of this converter -> FLAGGED; flagged_by_report_id
# set only when a specific report caused the suspension.
# ---------------------------------------------------------------------------

def cascade_converter_suspension(converter_id, report_id=None):
    for order in _sorted(STORE["orders"].values()):
        if order["converter_id"] != converter_id:
            continue
        if order["fulfillment_status"] not in ("PENDING", "ALLOCATED"):
            continue
        _flag_and_recompute(order, report_id)


# ---------------------------------------------------------------------------
# Counterfeit confirmation sweep (§3.9, calc counterfeit_confirmation_sweep)
# ---------------------------------------------------------------------------

def counterfeit_confirmed_sweep(report):
    converter_suspended_now = False
    converter_id = report["implicated_converter_id"]
    if converter_id is not None:
        converter = STORE["converters"].get(converter_id)
        if converter is not None:
            if converter["status"] == "AUTHORIZED":
                converter["status"] = "SUSPENDED"
                store.touch(converter)
                converter_suspended_now = True
            elif converter["status"] == "SUSPENDED":
                converter["status"] = "REVOKED"
                store.touch(converter)

    # Link 2a: lot match — any fulfillment except CANCELLED, including SHIPPED.
    for order in _sorted(STORE["orders"].values()):
        if order["formulation_id"] != report["formulation_id"]:
            continue
        if order["lot_code"] is None or order["lot_code"] != report["lot_code"]:
            continue
        if order["fulfillment_status"] == "CANCELLED":
            continue
        _flag_and_recompute(order, report["id"])

    # Link 2b: only when this disposition actually suspended the converter —
    # the implicated converter's in-flight orders (any lot) are flagged.
    if converter_suspended_now:
        for order in _sorted(STORE["orders"].values()):
            if order["converter_id"] != converter_id:
                continue
            if order["fulfillment_status"] not in ("PENDING", "ALLOCATED"):
                continue
            _flag_and_recompute(order, report["id"])


def counterfeit_release_sweep(report):
    """CLEARED_GENUINE / INCONCLUSIVE: unflag orders whose flag names this
    report, unless another CONFIRMED_COUNTERFEIT report still matches the
    order's (formulation_id, lot_code)."""
    for order in _sorted(STORE["orders"].values()):
        if order["flagged_by_report_id"] != report["id"]:
            continue
        if _other_confirmed_match(order, excluding=report["id"]):
            continue
        unflag_order(order)
        recompute_provisional_accruals(
            order["formulation_id"], order["converter_id"], order["distributor_id"])


def _other_confirmed_match(order, excluding):
    if order["lot_code"] is None:
        return False
    for other in STORE["reports"].values():
        if other["id"] == excluding:
            continue
        if other["status"] != "CONFIRMED_COUNTERFEIT":
            continue
        if (other["formulation_id"] == order["formulation_id"]
                and other["lot_code"] == order["lot_code"]):
            return True
    return False


# ---------------------------------------------------------------------------
# Phase-out enforcement sweep (§3.8, calc phaseout_enforcement_sweep)
# ---------------------------------------------------------------------------

def phaseout_enforcement_sweep(program):
    successor_id = program["successor_formulation_id"]
    affected_ids = set()
    for formulation in STORE["formulations"].values():
        if formulation["id"] == successor_id:
            # The successor is the reformulated replacement; never targeted.
            continue
        if calcs.formulation_is_affected(formulation["id"], program):
            affected_ids.add(formulation["id"])

    targets = []
    for clearance in STORE["clearances"].values():
        if clearance["status"] != "CLEARED":
            continue
        if clearance["formulation_id"] not in affected_ids:
            continue
        jurisdiction = STORE["jurisdictions"].get(clearance["jurisdiction_id"])
        if jurisdiction is None:
            continue
        if jurisdiction["code"] not in program["jurisdiction_codes"]:
            continue
        targets.append(clearance)

    for clearance in _sorted(targets):
        # Cascade link 1: CLEARED -> SUSPENDED, decrement the formulation's
        # active_clearance_count.
        clearance["status"] = "SUSPENDED"
        store.touch(clearance)
        formulation = STORE["formulations"][clearance["formulation_id"]]
        formulation["active_clearance_count"] -= 1
        store.touch(formulation)
        # Cascade link 2: orders on this (formulation, jurisdiction) pair,
        # fulfillment PENDING/ALLOCATED/SHIPPED, compliance CLEAR -> FLAGGED.
        for order in _sorted(STORE["orders"].values()):
            if order["formulation_id"] != clearance["formulation_id"]:
                continue
            if order["ship_to_jurisdiction_id"] != clearance["jurisdiction_id"]:
                continue
            if order["fulfillment_status"] not in ("PENDING", "ALLOCATED", "SHIPPED"):
                continue
            _flag_and_recompute(order, None)
