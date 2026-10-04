"""drive_dues_deduction, audience-report-backed drives and settlement (§3.7)."""
from core import config as C
from core.base import touch

DUES_ROUNDING_HEADROOM_CENTS = 500000
RATIO_SCALE_BPS = 10000
SETTLE_COLLECTION_FLOOR_BPS = 6000


def collection_ratio_bps(drive):
    """collected / pledged in basis points, capped at 10000; 0 when none."""
    pledged = int(drive.get("pledged_cents") or 0)
    collected = int(drive.get("collected_cents") or 0)
    if pledged <= 0:
        return 0
    ratio = C.floor_div(C.d(collected) * C.d(RATIO_SCALE_BPS), C.d(pledged))
    return min(RATIO_SCALE_BPS, ratio)


def drive_dues_deduction_cents(drive, station, schedule=None):
    """Pledge basis, ratio floor-divided to a whole percent, then bounded by
    the station's matured dues (provisional fee less the rounding headroom)."""
    pledged = int(drive.get("pledged_cents") or 0)
    collected = int(drive.get("collected_cents") or 0)
    basis = C.r2c(C.d(pledged))
    if pledged > 0:
        ratio_percent = min(100, C.floor_div(C.d(collected) * C.d(100), C.d(pledged)))
    else:
        ratio_percent = 0
    raw_deduction = C.r2c(C.d(basis) * C.d(ratio_percent) / C.d(100))
    provisional = int(drive.get("_provisional_fee_cents") or 0)
    if provisional <= 0 and schedule is not None and station is not None:
        from services import fees
        provisional = fees.provisional_fee_cents(station, schedule)
    matured_dues = provisional - DUES_ROUNDING_HEADROOM_CENTS
    return int(min(int(raw_deduction), int(matured_dues)))


def recompute_drive(store, drive):
    station = store.member_stations.get(drive.get("station_id"))
    schedule = None
    if station is not None:
        from services import fees
        schedule = fees.resolve_schedule(store, station, drive.get("fiscal_year"))
        if schedule is not None:
            drive["_provisional_fee_cents"] = fees.provisional_fee_cents(station, schedule)
    drive["collection_ratio_bps"] = collection_ratio_bps(drive)
    cancelled = drive.get("drive_status") == "CANCELLED"
    if cancelled:
        drive["drive_deduction_cents"] = 0
    else:
        drive["drive_deduction_cents"] = drive_dues_deduction_cents(drive, station, schedule)
    return drive


def drive_has_audience_report(store, station_id, fiscal_year):
    for report in store.audience_reports.values():
        if report.get("station_id") == station_id and report.get("fiscal_year") == fiscal_year:
            return True
    return False


def settle_drive(store, drive):
    """Settlement charges the enacted flat base fee for the drive's fiscal year."""
    from services import fees
    station = store.member_stations.get(drive.get("station_id"))
    schedule = fees.resolve_schedule(store, station, drive.get("fiscal_year"))
    base_fee = int(schedule.get("base_fee_cents") or 0) if schedule else 0
    if station is not None:
        station["dues_arrears_cents"] = int(station.get("dues_arrears_cents") or 0) + base_fee
        touch(station)
        from services import governance
        governance.upsert_projection(store, station)
    return base_fee