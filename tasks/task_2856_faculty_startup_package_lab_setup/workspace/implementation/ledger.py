"""The append-only ledger: row writing, derived balances and the waterfall.

Every derived amount in this module is computed from the stored ledger rows on
demand, so a read is always a fully settled picture (PRD 2.8, 2.9, 3.4).
"""

import money
import store
from errors import fail

KIND_ENCUMBRANCE = "ENCUMBRANCE"
KIND_RELEASE = "RELEASE"
KIND_DISBURSEMENT = "DISBURSEMENT"
KIND_EXPIRY = "EXPIRY"
KIND_CARRYFORWARD_OUT = "CARRYFORWARD_OUT"
KIND_CARRYFORWARD_IN = "CARRYFORWARD_IN"
KIND_RECAPTURE = "RECAPTURE"

KINDS = (
    KIND_ENCUMBRANCE,
    KIND_RELEASE,
    KIND_DISBURSEMENT,
    KIND_EXPIRY,
    KIND_CARRYFORWARD_OUT,
    KIND_CARRYFORWARD_IN,
    KIND_RECAPTURE,
)

SOURCE_EQUIPMENT_ORDER = "EQUIPMENT_ORDER"
SOURCE_STAFF_APPOINTMENT = "STAFF_APPOINTMENT"
SOURCE_RENOVATION_PROJECT = "RENOVATION_PROJECT"
SOURCE_ROLLOVER = "ROLLOVER"
SOURCE_SETTLEMENT = "SETTLEMENT"

SOURCE_KINDS = (
    SOURCE_EQUIPMENT_ORDER,
    SOURCE_STAFF_APPOINTMENT,
    SOURCE_RENOVATION_PROJECT,
    SOURCE_ROLLOVER,
    SOURCE_SETTLEMENT,
)

TRANCHE_CATEGORIES = ("EQUIPMENT", "PERSONNEL", "RENOVATION", "DISCRETIONARY")
TRANCHE_STATUSES = ("SCHEDULED", "OPEN", "OBLIGATED", "CARRIED_FORWARD", "EXPIRED", "RECAPTURED")

RESERVING_STATUSES = ("APPROVED", "ACTIVE", "CLOSED_OUT")


# ---------------------------------------------------------------------------
# Row lookup helpers
# ---------------------------------------------------------------------------


def all_rows():
    return [store.db.spend_transactions[i] for i in store.db.txn_order]


def rows_for_package(package_id):
    return [r for r in all_rows() if r["package_id"] == package_id]


def rows_for_tranche(tranche_id):
    return [r for r in all_rows() if r["tranche_id"] == tranche_id]


def tranches_of_package(package_id):
    return store.by_created(
        [t for t in store.db.tranches.values() if t["package_id"] == package_id]
    )


def sum_kind(rows, kind):
    return sum(r["amount_cents"] for r in rows if r["kind"] == kind)


# ---------------------------------------------------------------------------
# Tranche balances (PRD 2.9): the identity holds by construction
# ---------------------------------------------------------------------------


def tranche_balances(tranche):
    rows = rows_for_tranche(tranche["id"])
    carried_in = sum_kind(rows, KIND_CARRYFORWARD_IN)
    carried_out = sum_kind(rows, KIND_CARRYFORWARD_OUT)
    disbursed = sum_kind(rows, KIND_DISBURSEMENT)
    encumbered = sum_kind(rows, KIND_ENCUMBRANCE) - sum_kind(rows, KIND_RELEASE) - disbursed
    expired = sum_kind(rows, KIND_EXPIRY)
    recaptured = sum_kind(rows, KIND_RECAPTURE)
    amount = int(tranche["amount_cents"])
    available = (
        amount + carried_in - encumbered - disbursed - carried_out - expired - recaptured
    )
    return {
        "carried_in_cents": carried_in,
        "carried_out_cents": carried_out,
        "encumbered_cents": encumbered,
        "disbursed_cents": disbursed,
        "expired_cents": expired,
        "recaptured_cents": recaptured,
        "available_balance_cents": available,
    }


def available_balance(tranche):
    return tranche_balances(tranche)["available_balance_cents"]


def encumbered_balance(tranche):
    return tranche_balances(tranche)["encumbered_cents"]


# ---------------------------------------------------------------------------
# Package rollups (PRD 3.4)
# ---------------------------------------------------------------------------


def package_rollup(package):
    tranches = tranches_of_package(package["id"])
    total_committed = sum(int(t["amount_cents"]) for t in tranches)
    total_encumbered = 0
    total_disbursed = 0
    total_available = 0
    total_expired = 0
    total_recaptured = 0
    total_carried_out = 0
    total_carried_in = 0
    for tranche in tranches:
        balances = tranche_balances(tranche)
        total_encumbered += balances["encumbered_cents"]
        total_disbursed += balances["disbursed_cents"]
        total_expired += balances["expired_cents"]
        total_recaptured += balances["recaptured_cents"]
        total_carried_out += balances["carried_out_cents"]
        total_carried_in += balances["carried_in_cents"]
        if tranche["status"] in ("SCHEDULED", "OPEN"):
            total_available += balances["available_balance_cents"]
    ratio = money.ratio4(total_disbursed + total_encumbered, total_committed)
    return {
        "total_committed_cents": total_committed,
        "total_encumbered_cents": total_encumbered,
        "total_disbursed_cents": total_disbursed,
        "total_available_cents": total_available,
        "total_expired_cents": total_expired,
        "total_recaptured_cents": total_recaptured,
        "total_carried_out_cents": total_carried_out,
        "total_carried_in_cents": total_carried_in,
        "spend_down_ratio": ratio,
    }


# ---------------------------------------------------------------------------
# Funding unit pool accounting (PRD 2.8)
# ---------------------------------------------------------------------------

SHARE_FIELD = {
    "dept": "dept_share_cents",
    "college": "college_share_cents",
    "dean": "dean_share_cents",
}


def unit_slot(package, unit_id):
    """Which of the three funder slots this unit occupies on the package."""
    if package.get("department_unit_id") == unit_id:
        return "dept"
    if package.get("college_unit_id") == unit_id:
        return "college"
    if package.get("dean_unit_id") == unit_id:
        return "dean"
    return None


def package_split(package, amount_cents):
    """cost_share_split of an amount under the package's three percentages."""
    dept, college, dean = money.cost_share_split(
        amount_cents,
        package["dept_share_pct"],
        package["college_share_pct"],
        package["dean_share_pct"],
    )
    return {"dept": dept, "college": college, "dean": dean}


def unit_amounts(unit):
    unit_id = unit["id"]
    reserved = 0
    committed = 0
    disbursed = 0
    refunded = 0
    for package in store.db.packages.values():
        slot = unit_slot(package, unit_id)
        if slot is None:
            continue
        field = SHARE_FIELD[slot]
        rows = rows_for_package(package["id"])
        reserving = package["negotiation_status"] in RESERVING_STATUSES
        if reserving:
            rollup = package_rollup(package)
            reserved += package_split(package, rollup["total_committed_cents"])[slot]
        for row in rows:
            share = int(row[field])
            kind = row["kind"]
            if kind == KIND_ENCUMBRANCE:
                committed += share
            elif kind in (KIND_RELEASE, KIND_DISBURSEMENT):
                committed -= share
                if kind == KIND_DISBURSEMENT:
                    disbursed += share
            elif kind in (KIND_EXPIRY, KIND_RECAPTURE):
                refunded += share
                # Expired and recaptured money returns to the pool automatically.
                if reserving:
                    reserved -= share
    pool = int(unit["cost_share_pool_cents"])
    return {
        "reserved_cents": reserved,
        "committed_cents": committed,
        "disbursed_cents": disbursed,
        "refunded_cents": refunded,
        "available_pool_cents": pool - reserved,
    }


def funder_units(package):
    return [
        store.db.funding_units.get(package.get("department_unit_id")),
        store.db.funding_units.get(package.get("college_unit_id")),
        store.db.funding_units.get(package.get("dean_unit_id")),
    ]


# ---------------------------------------------------------------------------
# Writing rows
# ---------------------------------------------------------------------------


def touch_ledger_targets(package, tranche):
    """Every resource whose derived fields moved gets its own version bump."""
    if tranche is not None:
        store.touch(tranche)
    if package is not None:
        store.touch(package)
        for unit in funder_units(package):
            if unit is not None:
                store.touch(unit)


def write_row(
    package,
    tranche,
    kind,
    amount_cents,
    source_kind,
    source_id=None,
    memo="",
    shares=None,
    reverses_transaction_id=None,
):
    """Append one immutable ledger row.  amount_cents is a positive magnitude."""
    amount = int(amount_cents)
    if amount <= 0:
        return None
    if shares is None:
        shares = package_split(package, amount)
    row = {
        "id": store.new_id(),
        "created_at": store.iso(store.now()),
        "package_id": package["id"],
        "tranche_id": tranche["id"],
        "kind": kind,
        "amount_cents": amount,
        "source_kind": source_kind,
        "source_id": source_id,
        "reverses_transaction_id": reverses_transaction_id,
        "dept_share_cents": int(shares["dept"]),
        "college_share_cents": int(shares["college"]),
        "dean_share_cents": int(shares["dean"]),
        "memo": memo,
        "_seq": store.db.next_seq(),
    }
    store.db.spend_transactions[row["id"]] = row
    store.db.txn_order.append(row["id"])
    touch_ledger_targets(package, tranche)
    return row


def row_shares(row):
    return {
        "dept": int(row["dept_share_cents"]),
        "college": int(row["college_share_cents"]),
        "dean": int(row["dean_share_cents"]),
    }


# ---------------------------------------------------------------------------
# The encumbrance waterfall (PRD 3.4)
# ---------------------------------------------------------------------------


def clock_iso():
    return store.iso(store.now())


def in_window(tranche, instant_iso=None):
    """Half-open availability window: available_on <= clock < expires_on."""
    moment = instant_iso or clock_iso()
    return tranche["available_on"] <= moment < tranche["expires_on"]


def waterfall_candidates(package, category):
    moment = clock_iso()
    candidates = [
        t
        for t in tranches_of_package(package["id"])
        if t["category"] == category and t["status"] == "OPEN" and in_window(t, moment)
    ]
    candidates.sort(
        key=lambda t: (t["expires_on"], int(t["fiscal_year"]), t["created_at"], t["_seq"])
    )
    return candidates


def check_waterfall(package, category, amount_cents):
    """Priority 42 then 43 of the ladder; no partial encumbrance is ever written."""
    candidates = waterfall_candidates(package, category)
    if not candidates:
        fail(
            "ERR_NO_OPEN_TRANCHE",
            "no OPEN %s tranche of this package is inside its availability window" % category,
        )
    capacity = sum(available_balance(t) for t in candidates)
    if capacity < int(amount_cents):
        fail(
            "ERR_INSUFFICIENT_TRANCHE_BALANCE",
            "the eligible %s tranches hold %d cents but %d are required"
            % (category, capacity, int(amount_cents)),
        )
    return candidates


def run_waterfall(package, category, amount_cents, source_kind, source_id, memo):
    """Check, then walk the ordered candidates writing one ENCUMBRANCE row each."""
    candidates = check_waterfall(package, category, amount_cents)
    outstanding = int(amount_cents)
    rows = []
    for tranche in candidates:
        if outstanding <= 0:
            break
        take = min(outstanding, available_balance(tranche))
        if take <= 0:
            continue
        rows.append(
            write_row(
                package,
                tranche,
                KIND_ENCUMBRANCE,
                take,
                source_kind,
                source_id,
                memo,
            )
        )
        outstanding -= take
    return rows


# ---------------------------------------------------------------------------
# Settling open encumbrances (PRD 2.7 settlement rule)
# ---------------------------------------------------------------------------


def settled_amount(encumbrance_row):
    total = 0
    for row in all_rows():
        if row.get("reverses_transaction_id") == encumbrance_row["id"]:
            total += int(row["amount_cents"])
    return total


def open_amount(encumbrance_row):
    return int(encumbrance_row["amount_cents"]) - settled_amount(encumbrance_row)


def open_encumbrances(package_id, source_kind, source_id):
    rows = []
    for row in rows_for_package(package_id):
        if row["kind"] != KIND_ENCUMBRANCE:
            continue
        if row["source_kind"] != source_kind or row["source_id"] != source_id:
            continue
        if open_amount(row) > 0:
            rows.append(row)
    return rows


def expire_residual(package, tranche, memo):
    """Expire whatever available balance the tranche still holds."""
    amount = available_balance(tranche)
    if amount <= 0:
        return None
    return write_row(
        package,
        tranche,
        KIND_EXPIRY,
        amount,
        SOURCE_SETTLEMENT,
        None,
        memo,
    )


def finalize_obligated(package, tranches):
    """An OBLIGATED tranche whose encumbered_cents reaches 0 becomes EXPIRED."""
    for tranche in tranches:
        if tranche["status"] != "OBLIGATED":
            continue
        if encumbered_balance(tranche) != 0:
            continue
        expire_residual(package, tranche, "residual balance expired on obligated tranche")
        tranche["status"] = "EXPIRED"
        store.touch(tranche)
        store.touch(package)


def _write_release(package, tranche, amount, shares, source_kind, source_id, memo, reverses):
    row = write_row(
        package,
        tranche,
        KIND_RELEASE,
        amount,
        source_kind,
        source_id,
        memo,
        shares=shares,
        reverses_transaction_id=reverses,
    )
    if row is not None and tranche["status"] == "OBLIGATED":
        # Cents released back onto an obligated tranche can never be re-spent.
        write_row(
            package,
            tranche,
            KIND_EXPIRY,
            amount,
            SOURCE_SETTLEMENT,
            None,
            "released cents expired on obligated tranche",
            shares=dict(shares),
        )
    return row


def settle_source(package, source_kind, source_id, disburse_total, memo):
    """Settle every open ENCUMBRANCE row of one source.

    ``disburse_total`` is the number of cents to disburse; the remainder of each
    settled row is released.  A row settled in whole copies its stored split
    verbatim; a partial settlement splits the disbursed part on its own amount
    and derives the paired release share as the per-funder remainder.
    """
    rows = open_encumbrances(package["id"], source_kind, source_id)
    remaining = int(disburse_total)
    affected = []
    for row in rows:
        tranche = store.db.tranches.get(row["tranche_id"])
        if tranche is None:
            continue
        affected.append(tranche)
        open_cents = open_amount(row)
        disbursed = min(remaining, open_cents)
        remaining -= disbursed
        released = open_cents - disbursed
        stored = row_shares(row)
        whole = open_cents == int(row["amount_cents"])
        if disbursed > 0:
            if released == 0 and whole:
                shares = dict(stored)
            else:
                shares = package_split(package, disbursed)
            write_row(
                package,
                tranche,
                KIND_DISBURSEMENT,
                disbursed,
                source_kind,
                source_id,
                memo,
                shares=shares,
                reverses_transaction_id=row["id"],
            )
        else:
            shares = {"dept": 0, "college": 0, "dean": 0}
        if released > 0:
            if disbursed == 0 and whole:
                release_shares = dict(stored)
            else:
                release_shares = {
                    key: stored[key] - shares[key] for key in ("dept", "college", "dean")
                }
            _write_release(
                package,
                tranche,
                released,
                release_shares,
                source_kind,
                source_id,
                memo,
                row["id"],
            )
    finalize_obligated(package, affected)
    return affected
