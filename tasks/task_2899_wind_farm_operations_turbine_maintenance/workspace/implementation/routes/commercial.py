"""Blade findings, availability guarantees, curtailment and landowner money."""

from decimal import Decimal
from fractions import Fraction

from flask import Blueprint, request

import calc
import enums
import svc
from auth import ALL_ROLES, COMMERCIAL_READ_ROLES, authenticate
from envelope import created, listing, ok
from errors import ApiError
from ladder import check_version, find, gate, invalid_state, path_row, ref_row
from store import DB
from validate import F, parse, require_interval

bp = Blueprint("commercial", __name__)


# ----------------------------------------------------------------- blade damages
@bp.post("/turbines/<turbine_id>/blade-damages")
def record_blade_damage(turbine_id):
    user_id, _role = authenticate(["ReliabilityEngineer", "CrewLead"])
    vals = parse(
        [
            F("inspection_method", "enum", members=enums.INSPECTION_METHODS),
            F("blade_position", "enum", members=enums.BLADE_POSITIONS),
            F("inspected_at", "datetime"),
            F("damage_category", "integer", minv=1, maxv=5),
            F("damage_type", "enum", members=enums.DAMAGE_TYPES),
            F("chord_position_pct", "number", minv=0, maxv=100),
            F("damage_length_mm", "number", minv=0),
            F("exposed_area_cm2", "number", minv=0),
        ]
    )
    turbine = path_row("turbines", turbine_id)
    gate(
        turbine["availability_state"] == "DECOMMISSIONED",
        "ERR_TURBINE_DECOMMISSIONED",
        "The turbine has been decommissioned.",
    )
    score, band, due_days = calc.blade_severity(
        vals["damage_category"],
        vals["damage_type"],
        vals["damage_length_mm"],
        vals["exposed_area_cm2"],
    )
    row = DB.new_row(
        turbine_id=turbine["id"],
        inspection_method=vals["inspection_method"],
        blade_position=vals["blade_position"],
        inspected_at=vals["inspected_at"],
        recorded_by_user_id=user_id,
        damage_category=vals["damage_category"],
        damage_type=vals["damage_type"],
        chord_position_pct=vals["chord_position_pct"],
        damage_length_mm=vals["damage_length_mm"],
        exposed_area_cm2=vals["exposed_area_cm2"],
        severity_score=score,
        repair_priority_band=band,
        repair_due_days=due_days,
        state="OPEN",
        waiver_rationale=None,
    )
    DB.insert("blade_damages", row)
    return created(row)


@bp.get("/blade-damages/<row_id>")
def get_blade_damage(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("blade_damages", row_id))


@bp.get("/blade-damages")
def list_blade_damages():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("blade_damages"),
        request.args,
        [
            ("turbine_id", "turbine_id", "string", None),
            ("repair_priority_band", "repair_priority_band", "enum", enums.REPAIR_BANDS),
            ("state", "state", "enum", enums.BLADE_STATES),
            ("inspection_method", "inspection_method", "enum", enums.INSPECTION_METHODS),
        ],
    )


@bp.post("/blade-damages/<row_id>/prioritize")
def prioritize_blade_damage(row_id):
    user_id, _role = authenticate(["ReliabilityEngineer", "CrewLead"])
    candidate = find("blade_damages", row_id)
    if candidate is not None and candidate["recorded_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The inspector who recorded the finding may not prioritize it.",
        )
    parse([])
    damage = path_row("blade_damages", row_id)
    if damage["state"] != "OPEN":
        invalid_state(
            "Only an OPEN finding may be prioritized; it is %s." % damage["state"]
        )
    damage["state"] = "PRIORITIZED"
    DB.touch(damage)
    return ok(damage)


@bp.post("/blade-damages/<row_id>/waive")
def waive_blade_damage(row_id):
    authenticate(["ReliabilityEngineer"])
    vals = parse([F("waiver_rationale", "string", minlen=1, nonblank=True)])
    damage = path_row("blade_damages", row_id)
    if damage["state"] != "OPEN":
        invalid_state("Only an OPEN finding may be waived; it is %s." % damage["state"])
    if damage["repair_priority_band"] in ("CRITICAL", "HIGH"):
        invalid_state(
            "A %s finding may not be waived." % damage["repair_priority_band"]
        )
    damage["state"] = "WAIVED"
    damage["waiver_rationale"] = vals["waiver_rationale"]
    DB.touch(damage)
    return ok(damage)


# ------------------------------------------------------------- service agreements
@bp.post("/service-agreements")
def create_agreement():
    authenticate(["CommercialManager"])
    vals = parse(
        [
            F("wind_farm_id", "string"),
            F("guaranteed_availability_pct", "number", gt=0, maxv=100),
            F("availability_basis", "enum", members=enums.AVAILABILITY_BASES),
            F("lda_rate_cents_per_pct_point", "integer", minv=0),
            F("lda_cap_cents", "integer", minv=0),
            F("period_start_utc", "datetime"),
            F("period_end_utc", "datetime"),
        ]
    )
    require_interval(vals, "period_start_utc", "period_end_utc")
    farm = ref_row("farms", vals["wind_farm_id"])
    row = DB.new_row(
        wind_farm_id=farm["id"],
        guaranteed_availability_pct=vals["guaranteed_availability_pct"],
        availability_basis=vals["availability_basis"],
        lda_rate_cents_per_pct_point=vals["lda_rate_cents_per_pct_point"],
        lda_cap_cents=vals["lda_cap_cents"],
        period_start_utc=vals["period_start_utc"],
        period_end_utc=vals["period_end_utc"],
        time_based_availability_pct=Decimal("0"),
        energy_based_availability_pct=Decimal("0"),
        assessed_lda_cents=0,
        projected_shortfall_pct=Decimal("0"),
        at_risk_flag=False,
        state="ACTIVE",
    )
    DB.insert("service_agreements", row)
    return created(row)


@bp.get("/service-agreements/<row_id>")
def get_agreement(row_id):
    authenticate(COMMERCIAL_READ_ROLES)
    return ok(path_row("service_agreements", row_id))


@bp.get("/service-agreements")
def list_agreements():
    authenticate(COMMERCIAL_READ_ROLES)
    return listing(
        DB.all("service_agreements"),
        request.args,
        [
            ("wind_farm_id", "wind_farm_id", "string", None),
            ("state", "state", "enum", enums.AGREEMENT_STATES),
            ("availability_basis", "availability_basis", "enum", enums.AVAILABILITY_BASES),
        ],
    )


@bp.post("/service-agreements/<row_id>/settle")
def settle_agreement(row_id):
    authenticate(["CommercialManager"])
    parse([])
    agreement = path_row("service_agreements", row_id)
    if agreement["state"] != "ACTIVE":
        invalid_state(
            "Only an ACTIVE agreement may be settled; it is %s." % agreement["state"]
        )
    if DB.now() < agreement["period_end_utc"]:
        invalid_state("The measurement period has not yet ended.")
    turbine_set = svc.turbines_of_farm(agreement["wind_farm_id"], in_service_only=True)
    gate(
        not turbine_set,
        "ERR_NO_TURBINES_IN_SERVICE",
        "The farm has no turbine in service, so availability is undefined.",
    )
    time_based, energy_based, _shortfall, lda = svc.settle_figures(agreement, turbine_set)
    agreement["state"] = "IN_SETTLEMENT"
    agreement["time_based_availability_pct"] = time_based
    agreement["energy_based_availability_pct"] = energy_based
    agreement["assessed_lda_cents"] = lda
    DB.touch(agreement)
    return ok(agreement)


@bp.post("/service-agreements/<row_id>/finalize")
def finalize_agreement(row_id):
    authenticate(["CommercialManager"])
    parse([])
    agreement = path_row("service_agreements", row_id)
    if agreement["state"] != "IN_SETTLEMENT":
        invalid_state(
            "Only an IN_SETTLEMENT agreement may be finalized; it is %s."
            % agreement["state"]
        )
    agreement["state"] = "SETTLED"
    agreement["at_risk_flag"] = False
    DB.touch(agreement)
    return ok(agreement)


# ------------------------------------------------------------ curtailment orders
@bp.post("/turbines/<turbine_id>/curtailment-orders")
def issue_curtailment(turbine_id):
    authenticate(["ControlRoomOperator"])
    vals = parse(
        [
            F("reason", "enum", members=enums.CURTAILMENT_REASONS),
            F("start_utc", "datetime"),
            F("end_utc", "datetime"),
            F("power_limit_kw", "number", minv=0),
            F("deemed_kwh_per_hour", "number", minv=0),
            F("expected_turbine_version", "integer", minv=0),
        ]
    )
    require_interval(vals, "start_utc", "end_utc")
    turbine = path_row("turbines", turbine_id)
    check_version(turbine, vals["expected_turbine_version"], "ERR_STALE_TURBINE_VERSION")
    gate(
        turbine["availability_state"] == "DECOMMISSIONED",
        "ERR_TURBINE_DECOMMISSIONED",
        "The turbine has been decommissioned.",
    )
    row = DB.new_row(
        turbine_id=turbine["id"],
        reason=vals["reason"],
        compensable=vals["reason"] == "GRID",
        start_utc=vals["start_utc"],
        end_utc=vals["end_utc"],
        power_limit_kw=vals["power_limit_kw"],
        deemed_kwh_per_hour=vals["deemed_kwh_per_hour"],
        state="PENDING",
        curtailed_hours=Decimal("0"),
        lost_energy_kwh=Decimal("0"),
    )
    DB.insert("curtailment_orders", row)
    DB.touch(turbine)
    return created(row)


@bp.get("/curtailment-orders/<row_id>")
def get_curtailment(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("curtailment_orders", row_id))


@bp.get("/curtailment-orders")
def list_curtailments():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("curtailment_orders"),
        request.args,
        [
            ("turbine_id", "turbine_id", "string", None),
            ("reason", "reason", "enum", enums.CURTAILMENT_REASONS),
            ("state", "state", "enum", enums.CURTAILMENT_ORDER_STATES),
            ("compensable", "compensable", "bool", None),
        ],
    )


@bp.post("/curtailment-orders/<row_id>/activate")
def activate_curtailment(row_id):
    authenticate(["ControlRoomOperator"])
    parse([])
    order = path_row("curtailment_orders", row_id)
    if order["state"] != "PENDING":
        invalid_state(
            "Only a PENDING curtailment order may be activated; it is %s."
            % order["state"]
        )
    turbine = DB.get("turbines", order["turbine_id"])
    gate(
        turbine["availability_state"] == "DECOMMISSIONED",
        "ERR_TURBINE_DECOMMISSIONED",
        "The turbine has been decommissioned.",
    )
    active = [
        c
        for c in DB.all("curtailment_orders")
        if c["turbine_id"] == turbine["id"] and c["state"] == "ACTIVE"
    ]
    gate(
        len(active) >= calc.MAX_ACTIVE_CURTAILMENTS,
        "ERR_CURTAILMENT_STACK_LIMIT",
        "The turbine already holds %d active curtailment orders."
        % calc.MAX_ACTIVE_CURTAILMENTS,
    )
    order["state"] = "ACTIVE"
    DB.touch(order)
    svc.recompute_curtailment_dimension(turbine)
    DB.touch(turbine)
    return ok(order)


@bp.post("/curtailment-orders/<row_id>/release")
def release_curtailment(row_id):
    authenticate(["ControlRoomOperator"])
    vals = parse([F("released_at", "datetime")])
    order = path_row("curtailment_orders", row_id)
    if order["state"] != "ACTIVE":
        invalid_state(
            "Only an ACTIVE curtailment order may be released; it is %s." % order["state"]
        )
    hours = calc.hours_between(order["start_utc"], vals["released_at"])
    lost = calc.rhu(
        Fraction(Decimal(hours)) * Fraction(Decimal(order["deemed_kwh_per_hour"])), 2
    )
    order["state"] = "RELEASED"
    order["curtailed_hours"] = hours
    order["lost_energy_kwh"] = lost
    DB.touch(order)

    turbine = DB.get("turbines", order["turbine_id"])
    svc.recompute_curtailment_dimension(turbine)
    if not order["compensable"]:
        turbine["counted_downtime_hours_period"] = (
            Decimal(turbine["counted_downtime_hours_period"]) + Decimal(hours)
        )
    DB.touch(turbine)
    svc.downtime_changed(turbine["wind_farm_id"])
    return ok(order)


# --------------------------------------------------------- landowner settlements
@bp.post("/farms/<farm_id>/landowner-settlements")
def draft_settlement(farm_id):
    authenticate(["CommercialManager"])
    vals = parse(
        [
            F("parcel_code", "string", minlen=1, maxlen=40, nonblank=True),
            F("royalty_basis", "enum", members=enums.ROYALTY_BASES),
            F("period_start_utc", "datetime"),
            F("period_end_utc", "datetime"),
            F("royalty_pct", "number", gt=0, maxv=100),
            F("minimum_payment_cents", "integer", minv=0),
            F("energy_price_cents_per_kwh", "number", gt=0),
            F("road_damage_assessment_cents", "integer", minv=0),
            F("expected_wind_farm_version", "integer", minv=0),
        ]
    )
    require_interval(vals, "period_start_utc", "period_end_utc")
    farm = path_row("farms", farm_id)
    check_version(farm, vals["expected_wind_farm_version"], "ERR_STALE_FARM_VERSION")
    gate(
        svc.farm_in_settlement(farm["id"]),
        "ERR_AGREEMENT_IN_SETTLEMENT",
        "A service agreement on this farm is in settlement; the period is frozen.",
    )
    for other in DB.all("landowner_settlements"):
        if other["wind_farm_id"] != farm["id"]:
            continue
        if other["parcel_code"] != vals["parcel_code"] or other["state"] == "VOID":
            continue
        if calc.overlaps(
            vals["period_start_utc"],
            vals["period_end_utc"],
            other["period_start_utc"],
            other["period_end_utc"],
        ):
            raise ApiError(
                "ERR_SETTLEMENT_PERIOD_OVERLAP",
                "The period overlaps an existing settlement for this parcel.",
            )
    headroom = int(farm["landowner_budget_cap_cents"]) - int(
        farm["landowner_payable_cents"]
    )
    gate(
        vals["minimum_payment_cents"] > headroom,
        "ERR_MINIMUM_PAYMENT_ABOVE_CAP",
        "The minimum payment exceeds the farm's remaining landowner budget headroom.",
    )

    metered, deemed, royalty, payment, road_levy, community_levy = svc.royalty_figures(
        farm,
        vals["royalty_basis"],
        vals["period_start_utc"],
        vals["period_end_utc"],
        vals["royalty_pct"],
        vals["minimum_payment_cents"],
        vals["energy_price_cents_per_kwh"],
    )
    row = DB.new_row(
        wind_farm_id=farm["id"],
        parcel_code=vals["parcel_code"],
        royalty_basis=vals["royalty_basis"],
        period_start_utc=vals["period_start_utc"],
        period_end_utc=vals["period_end_utc"],
        royalty_pct=vals["royalty_pct"],
        minimum_payment_cents=vals["minimum_payment_cents"],
        energy_price_cents_per_kwh=vals["energy_price_cents_per_kwh"],
        road_damage_assessment_cents=vals["road_damage_assessment_cents"],
        metered_kwh=metered,
        deemed_kwh=deemed,
        royalty_cents=royalty,
        payment_cents=payment,
        road_levy_cents=road_levy,
        community_levy_cents=community_levy,
        state="DRAFT",
        void_reason=None,
    )
    DB.insert("landowner_settlements", row)
    DB.touch(farm)
    return created(row)


@bp.get("/landowner-settlements/<row_id>")
def get_settlement(row_id):
    authenticate(COMMERCIAL_READ_ROLES)
    return ok(path_row("landowner_settlements", row_id))


@bp.get("/landowner-settlements")
def list_settlements():
    authenticate(COMMERCIAL_READ_ROLES)
    return listing(
        DB.all("landowner_settlements"),
        request.args,
        [
            ("wind_farm_id", "wind_farm_id", "string", None),
            ("parcel_code", "parcel_code", "string", None),
            ("state", "state", "enum", enums.SETTLEMENT_STATES),
            ("royalty_basis", "royalty_basis", "enum", enums.ROYALTY_BASES),
        ],
    )


@bp.post("/landowner-settlements/<row_id>/approve")
def approve_settlement(row_id):
    authenticate(["CommercialManager"])
    parse([])
    settlement = path_row("landowner_settlements", row_id)
    if settlement["state"] != "DRAFT":
        invalid_state(
            "Only a DRAFT settlement may be approved; it is %s." % settlement["state"]
        )
    gate(
        svc.farm_in_settlement(settlement["wind_farm_id"]),
        "ERR_AGREEMENT_IN_SETTLEMENT",
        "A service agreement on this farm is in settlement; approval is blocked.",
    )
    settlement["state"] = "APPROVED"
    DB.touch(settlement)
    svc.post_settlement(DB.get("farms", settlement["wind_farm_id"]), settlement, 1)
    return ok(settlement)


@bp.post("/landowner-settlements/<row_id>/void")
def void_settlement(row_id):
    authenticate(["CommercialManager"])
    vals = parse([F("void_reason", "string", minlen=1, nonblank=True)])
    settlement = path_row("landowner_settlements", row_id)
    if settlement["state"] != "APPROVED":
        invalid_state(
            "Only an APPROVED settlement may be voided; it is %s." % settlement["state"]
        )
    settlement["state"] = "VOID"
    settlement["void_reason"] = vals["void_reason"]
    DB.touch(settlement)
    svc.post_settlement(DB.get("farms", settlement["wind_farm_id"]), settlement, -1)
    return ok(settlement)
