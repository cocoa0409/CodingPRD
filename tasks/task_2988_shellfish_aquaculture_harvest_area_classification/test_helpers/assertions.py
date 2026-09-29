"""Entity assertions and domain invariant checkers for the shellfish API."""
import re

from prd_bench_local_runner.testing import is_valid_uuid

from .types import (
    AreaClassification,
    AreaHarvestStatus,
    AuthorizationStatus,
    CertificationCategory,
    ClearanceState,
    ComplianceStatus,
    ControlMethod,
    EligibleClassification,
    GearType,
    GrowoutUnitStatus,
    HusbandryLogType,
    InvestigationStatus,
    LeaseStatus,
    ListingStatus,
    LotStatus,
    NurserySystem,
    Pathogen,
    PredatorSpecies,
    RefrigerationType,
    SampleStatus,
    ScopeVariant,
    ScreeningResult,
    SeedLotStatus,
    ShipmentStatus,
    Species,
    StatisticsVariant,
    TttBasisVariant,
    VibrioPlanStatus,
)

# An ISO 8601 UTC instant with exactly three fractional-second digits (PRD §2.4).
MILLIS_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
CALENDAR_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# Generic shape helpers
# --------------------------------------------------------------------------
def assert_millis_instant(value, field="timestamp"):
    """PRD §2.4: an ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert MILLIS_INSTANT_RE.match(value), (
        f"{field} must be an ISO 8601 UTC instant with exactly three "
        f"fractional-second digits, got {value!r}"
    )


def assert_calendar_date(value, field="date"):
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert CALENDAR_DATE_RE.match(value), (
        f"{field} must use the YYYY-MM-DD form, got {value!r}"
    )


def assert_full_quartet(data, entity="resource"):
    """Resources that are not append-only carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a bare server-minted UUID, got {data.get('id')!r}"
    )
    assert_millis_instant(data.get("created_at"), f"{entity}.created_at")
    assert_millis_instant(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_append_only_record(data, entity="record"):
    """PRD §2.4: HusbandryLog, WaterSample and RainfallEvent carry neither
    updated_at nor version, and both are absent from the response entirely."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert_millis_instant(data.get("created_at"), f"{entity}.created_at")
    assert "updated_at" not in data, (
        f"{entity} is append-only: updated_at must be absent from the response"
    )
    assert "version" not in data, (
        f"{entity} is append-only: version must be absent from the response"
    )


def assert_present(data, field, entity="resource"):
    """Fields described as null before some event has occurred are present in the
    response object with a JSON null value, not omitted (PRD §2.4)."""
    assert field in data, f"{entity}.{field} must be present in the response object"


def assert_null(data, field, entity="resource"):
    assert_present(data, field, entity)
    assert data[field] is None, f"{entity}.{field} must be null, got {data[field]!r}"


def validate_unpaginated(response, expected_status=200):
    """For 2xx array payloads that are not page windows (no pagination meta)."""
    assert response.status_code == expected_status, (
        f"Expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body.get("data"), list), "data must be an array"
    return body["data"]


def assert_pagination_meta(meta, expected_limit, expected_offset,
                           expected_total, returned_count):
    """PRD §2.3: limit/offset echo what was applied, total_count is the match
    count before the window, has_more is offset + page size < total_count."""
    assert meta["limit"] == expected_limit, (
        f"meta.limit must echo the applied limit {expected_limit}, got {meta['limit']}"
    )
    assert meta["offset"] == expected_offset, (
        f"meta.offset must echo the applied offset {expected_offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == expected_total, (
        f"meta.total_count must be {expected_total}, got {meta['total_count']}"
    )
    expected_has_more = (expected_offset + returned_count) < expected_total
    assert meta["has_more"] is expected_has_more, (
        f"meta.has_more must be {expected_has_more}, got {meta['has_more']}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_growing_area(data):
    assert_full_quartet(data, "growing_area")
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 32, (
        "growing_area.code must be at least 3 and at most 32 characters"
    )
    assert isinstance(data["water_body"], str) and len(data["water_body"]) > 0
    assert data["classification"] in [c.value for c in AreaClassification], (
        f"growing_area.classification must be one of the four sanitary "
        f"classifications, got {data['classification']!r}"
    )
    assert data["harvest_status"] in [s.value for s in AreaHarvestStatus], (
        f"growing_area.harvest_status must be OPEN, CLOSED_RAINFALL or "
        f"CLOSED_SAMPLE_FAILURE, got {data['harvest_status']!r}"
    )
    assert isinstance(data["rainfall_closure_threshold_in"], (int, float))
    assert data["rainfall_closure_threshold_in"] > 0
    assert isinstance(data["rainfall_closure_hours"], int)
    assert data["rainfall_closure_hours"] >= 1
    assert isinstance(data["reopen_sample_count_required"], int)
    assert data["reopen_sample_count_required"] >= 1
    assert isinstance(data["clean_sample_mpn_limit"], (int, float))
    assert isinstance(data["conditional_management_plan_on_file"], bool)
    for field in ("last_closure_started_at", "closure_reopen_eligible_at",
                  "geometric_mean_mpn", "p90_mpn"):
        assert_present(data, field, "growing_area")
    for field in ("consecutive_clean_samples", "accepted_sample_count",
                  "open_authorization_count"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"growing_area.{field} must be a non-negative integer"
        )
    assert data["eligible_classification"] in [e.value for e in EligibleClassification]


def assert_lease(data):
    assert_full_quartet(data, "lease")
    assert is_valid_uuid(data["growing_area_id"])
    assert isinstance(data["operator_user_id"], str) and data["operator_user_id"]
    assert isinstance(data["lease_code"], str) and data["lease_code"]
    assert isinstance(data["requested_acreage"], (int, float))
    assert data["requested_acreage"] > 0
    assert isinstance(data["plot_codes"], list)
    assert 1 <= len(data["plot_codes"]) <= 12
    assert len(set(data["plot_codes"])) == len(data["plot_codes"]), (
        "lease.plot_codes must be unique non-empty strings"
    )
    assert isinstance(data["gear_types_permitted"], list)
    assert len(data["gear_types_permitted"]) >= 1
    for gt in data["gear_types_permitted"]:
        assert gt in [g.value for g in GearType]
    assert isinstance(data["authorized_gear_units"], int)
    assert data["authorized_gear_units"] >= 1
    assert isinstance(data["deployed_gear_units"], int)
    assert data["deployed_gear_units"] >= 0
    assert data["status"] in [s.value for s in LeaseStatus]
    assert data["navigation_clearance"] in [c.value for c in ClearanceState]
    assert data["environmental_clearance"] in [c.value for c in ClearanceState]
    for field in ("navigation_reviewer_user_id", "environmental_reviewer_user_id",
                  "rent_paid_through_date", "decided_at"):
        assert_present(data, field, "lease")
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["royalty_accrued_cents"], int), (
        "lease.royalty_accrued_cents is integer cents"
    )


def assert_hatchery(data):
    assert_full_quartet(data, "hatchery")
    assert isinstance(data["name"], str) and data["name"]
    assert re.match(r"^[A-Z]{2}$", data["state_code"]), (
        "hatchery.state_code must be exactly two uppercase letters"
    )
    assert isinstance(data["ncsp_certificate_no"], str) and data["ncsp_certificate_no"]
    assert_calendar_date(data["certificate_expires_on"], "hatchery.certificate_expires_on")
    assert isinstance(data["pathogen_free_species"], list)
    assert len(data["pathogen_free_species"]) >= 1
    for sp in data["pathogen_free_species"]:
        assert sp in [s.value for s in Species]


def assert_seed_lot(data):
    assert_full_quartet(data, "seed_lot")
    assert is_valid_uuid(data["hatchery_id"])
    assert is_valid_uuid(data["lease_id"])
    assert data["species"] in [s.value for s in Species]
    assert isinstance(data["received_seed_count"], int)
    assert data["received_seed_count"] >= 1
    assert isinstance(data["disease_certificate_no"], str)
    assert_calendar_date(data["disease_cert_issued_on"], "seed_lot.disease_cert_issued_on")
    assert_calendar_date(data["shipped_on"], "seed_lot.shipped_on")
    assert data["status"] in [s.value for s in SeedLotStatus]
    for field in ("screening_result", "screened_on", "nursery_started_on",
                  "nursery_system", "nursery_completed_on", "surviving_seed_count",
                  "survival_rate_pct"):
        assert_present(data, field, "seed_lot")
    if data["screening_result"] is not None:
        assert data["screening_result"] in [r.value for r in ScreeningResult]
    if data["nursery_system"] is not None:
        assert data["nursery_system"] in [n.value for n in NurserySystem]
    assert isinstance(data["allocated_seed_count"], int)
    assert isinstance(data["unallocated_seed_count"], int)


def assert_growout_unit(data):
    assert_full_quartet(data, "growout_unit")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["seed_lot_id"])
    assert isinstance(data["plot_code"], str) and data["plot_code"]
    assert data["gear_type"] in [g.value for g in GearType]
    assert isinstance(data["gear_units"], int) and data["gear_units"] >= 1
    assert isinstance(data["seed_count_planted"], int) and data["seed_count_planted"] >= 1
    assert_calendar_date(data["deployed_on"], "growout_unit.deployed_on")
    assert_calendar_date(data["planned_retrieval_on"], "growout_unit.planned_retrieval_on")
    assert data["status"] in [s.value for s in GrowoutUnitStatus]
    for field in ("retrieved_on", "void_reason", "last_inspection_at",
                  "last_predator_control_at"):
        assert_present(data, field, "growout_unit")
    assert isinstance(data["husbandry_current"], bool)
    assert isinstance(data["mortality_count_total"], int)
    assert data["mortality_count_total"] >= 0


def assert_husbandry_log(data):
    assert_append_only_record(data, "husbandry_log")
    assert is_valid_uuid(data["growout_unit_id"])
    assert data["log_type"] in [t.value for t in HusbandryLogType]
    assert_millis_instant(data["performed_at"], "husbandry_log.performed_at")
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    for field in ("predator_species", "control_method", "notes"):
        assert_present(data, field, "husbandry_log")
    if data["predator_species"] is not None:
        assert data["predator_species"] in [p.value for p in PredatorSpecies]
    if data["control_method"] is not None:
        assert data["control_method"] in [c.value for c in ControlMethod]
    assert isinstance(data["mortality_count"], int) and data["mortality_count"] >= 0


def assert_water_sample(data):
    assert_append_only_record(data, "water_sample")
    assert is_valid_uuid(data["growing_area_id"])
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert_millis_instant(data["collected_at"], "water_sample.collected_at")
    assert isinstance(data["fecal_coliform_mpn"], (int, float))
    assert data["fecal_coliform_mpn"] >= 1
    assert isinstance(data["water_temp_c"], (int, float))
    assert_present(data, "salinity_ppt", "water_sample")
    assert data["sample_status"] in [s.value for s in SampleStatus]
    assert isinstance(data["is_adverse_condition"], bool)
    assert isinstance(data["counted_clean"], bool)


def assert_rainfall_event(data):
    assert_append_only_record(data, "rainfall_event")
    assert is_valid_uuid(data["growing_area_id"])
    assert isinstance(data["gauge_code"], str) and data["gauge_code"]
    assert_millis_instant(data["observed_at"], "rainfall_event.observed_at")
    assert isinstance(data["inches_24h"], (int, float))
    assert data["inches_24h"] >= 0
    assert isinstance(data["triggered_closure"], bool)
    assert isinstance(data["voided_authorization_count"], int)
    assert data["voided_authorization_count"] >= 0


def assert_harvest_vessel(data):
    assert_full_quartet(data, "harvest_vessel")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["registration_no"], str) and data["registration_no"]
    assert data["refrigeration_type"] in [r.value for r in RefrigerationType]
    assert isinstance(data["concurrent_authorization_capacity"], int)
    assert data["concurrent_authorization_capacity"] >= 1
    assert isinstance(data["active_authorization_count"], int)
    assert data["active_authorization_count"] >= 0


def assert_harvest_authorization(data):
    assert_full_quartet(data, "harvest_authorization")
    for field in ("lease_id", "growout_unit_id", "vessel_id", "dealer_id",
                  "growing_area_id"):
        assert is_valid_uuid(data[field]), f"harvest_authorization.{field} must be a UUID"
    assert_millis_instant(data["window_start"], "harvest_authorization.window_start")
    assert_millis_instant(data["window_end"], "harvest_authorization.window_end")
    assert isinstance(data["projected_bushels"], int)
    assert data["projected_bushels"] >= 1
    assert isinstance(data["harvested_bushels"], int)
    assert data["harvested_bushels"] >= 0
    assert data["status"] in [s.value for s in AuthorizationStatus]
    for field in ("harvest_start_at", "harvest_end_at", "void_reason"):
        assert_present(data, field, "harvest_authorization")


def assert_harvest_lot(data):
    assert_full_quartet(data, "harvest_lot")
    assert is_valid_uuid(data["harvest_authorization_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert_present(data, "shipment_id", "harvest_lot")
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["bushels"], int) and data["bushels"] >= 1
    for field in ("first_out_of_water_at", "last_out_of_water_at",
                  "placed_in_temperature_control_at"):
        assert_millis_instant(data[field], f"harvest_lot.{field}")
    assert isinstance(data["water_temp_c"], (int, float))
    for field in ("ttt_minutes_first_basis", "ttt_minutes_last_basis",
                  "governing_ttt_minutes", "allowed_ttt_minutes",
                  "vibrio_plan_month", "season_total_bushels_at_creation",
                  "royalty_rate_cents_per_bushel", "royalty_cents",
                  "inspection_fee_cents", "conservation_surcharge_cents",
                  "lot_settlement_cents"):
        assert isinstance(data[field], int), f"harvest_lot.{field} must be an integer"
    assert data["ttt_basis_variant"] in [v.value for v in TttBasisVariant]
    assert data["compliance_status"] in [c.value for c in ComplianceStatus]
    assert is_valid_uuid(data["vibrio_control_plan_id"])
    assert 1 <= data["vibrio_plan_month"] <= 12
    assert data["status"] in [s.value for s in LotStatus]
    for field in ("tag_harvest_date", "tag_area_code", "tag_lease_code",
                  "tag_dealer_certification_no", "embargo_reason", "void_reason"):
        assert_present(data, field, "harvest_lot")


def assert_dealer(data):
    assert_full_quartet(data, "dealer")
    assert isinstance(data["name"], str) and data["name"]
    assert re.match(r"^[A-Z]{2}$", data["state_code"]), (
        "dealer.state_code must be exactly two uppercase letters"
    )
    assert data["certification_category"] in [c.value for c in CertificationCategory]
    assert isinstance(data["certification_no"], str) and data["certification_no"]
    assert_calendar_date(data["certified_through"], "dealer.certified_through")
    assert_present(data, "icssl_listed_through", "dealer")
    assert data["listing_status"] in [s.value for s in ListingStatus]
    assert isinstance(data["recall_strike_count"], int)
    assert data["recall_strike_count"] >= 0
    assert_present(data, "suspension_reason", "dealer")


def assert_shipment(data):
    assert_full_quartet(data, "shipment")
    assert is_valid_uuid(data["dealer_id"])
    assert re.match(r"^[A-Z]{2}$", data["destination_state"]), (
        "shipment.destination_state must be a two-letter state code"
    )
    assert isinstance(data["carrier"], str) and data["carrier"]
    assert isinstance(data["lot_ids"], list)
    assert 1 <= len(data["lot_ids"]) <= 25
    assert isinstance(data["lot_count"], int)
    assert data["lot_count"] == len(data["lot_ids"]), (
        "shipment.lot_count must equal the number of entries in lot_ids"
    )
    assert isinstance(data["total_bushels"], int)
    assert isinstance(data["is_interstate"], bool)
    assert data["status"] in [s.value for s in ShipmentStatus]
    for field in ("shipped_at", "held_reason", "recall_reason"):
        assert_present(data, field, "shipment")


def assert_illness_investigation(data):
    assert_full_quartet(data, "illness_investigation")
    assert is_valid_uuid(data["source_shipment_id"])
    assert_millis_instant(data["reported_at"], "illness_investigation.reported_at")
    assert isinstance(data["illness_count"], int) and data["illness_count"] >= 1
    assert data["pathogen"] in [p.value for p in Pathogen]
    assert_present(data, "scope_variant", "illness_investigation")
    if data["scope_variant"] is not None:
        assert data["scope_variant"] in [s.value for s in ScopeVariant]
    assert data["status"] in [s.value for s in InvestigationStatus]
    assert isinstance(data["traced_lot_ids"], list)
    assert isinstance(data["traced_lot_count"], int)
    assert data["traced_lot_count"] == len(data["traced_lot_ids"]), (
        "traced_lot_count must be the length of traced_lot_ids"
    )
    assert isinstance(data["recalled_shipment_count"], int)
    assert_present(data, "confirmed_at", "illness_investigation")


def assert_vibrio_control_plan(data):
    assert_full_quartet(data, "vibrio_control_plan")
    assert isinstance(data["season_month"], int)
    assert 1 <= data["season_month"] <= 12
    assert isinstance(data["max_time_to_temperature_minutes"], int)
    assert data["max_time_to_temperature_minutes"] >= 60
    assert isinstance(data["high_water_temp_c"], (int, float))
    assert isinstance(data["high_temp_reduction_minutes"], int)
    assert data["high_temp_reduction_minutes"] >= 0
    assert data["status"] in [s.value for s in VibrioPlanStatus]


def assert_classification_summary(data):
    """PRD §3.2: the computed read carries exactly eight fields."""
    assert data["variant"] in [v.value for v in StatisticsVariant]
    assert isinstance(data["sample_count"], int) and data["sample_count"] >= 0
    for field in ("mean_log10", "geometric_mean_mpn", "p90_mpn",
                  "window_start_at", "window_end_at"):
        assert_present(data, field, "classification_summary")
    assert data["eligible_classification"] in [e.value for e in EligibleClassification]


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_lot_settlement_consistent(lot):
    """PRD §3.8 step 6: lot_settlement_cents is royalty plus inspection fee
    plus conservation surcharge, all in integer cents."""
    expected = (lot["royalty_cents"] + lot["inspection_fee_cents"]
                + lot["conservation_surcharge_cents"])
    assert lot["lot_settlement_cents"] == expected, (
        f"lot_settlement_cents must be {expected} "
        f"(royalty {lot['royalty_cents']} + inspection {lot['inspection_fee_cents']} "
        f"+ surcharge {lot['conservation_surcharge_cents']}), "
        f"got {lot['lot_settlement_cents']}"
    )
    assert lot["royalty_cents"] == (
        lot["royalty_rate_cents_per_bushel"] * lot["bushels"]
    ), "royalty_cents must be the stamped rate multiplied by this lot's bushels"


def assert_governing_basis_consistent(lot):
    """PRD §3.8: governing_ttt_minutes is the first-basis figure under
    FIRST_HARVEST_BASIS and the last-basis figure under LAST_HARVEST_BASIS."""
    if lot["ttt_basis_variant"] == TttBasisVariant.FIRST_HARVEST_BASIS.value:
        assert lot["governing_ttt_minutes"] == lot["ttt_minutes_first_basis"]
    else:
        assert lot["governing_ttt_minutes"] == lot["ttt_minutes_last_basis"]


def assert_compliance_consistent(lot):
    """PRD §3.8: COMPLIANT when governing_ttt_minutes is at or below the allowance."""
    expected = (
        ComplianceStatus.COMPLIANT.value
        if lot["governing_ttt_minutes"] <= lot["allowed_ttt_minutes"]
        else ComplianceStatus.NONCOMPLIANT.value
    )
    assert lot["compliance_status"] == expected, (
        f"compliance_status must be {expected} for governing "
        f"{lot['governing_ttt_minutes']} against allowance "
        f"{lot['allowed_ttt_minutes']}, got {lot['compliance_status']}"
    )
