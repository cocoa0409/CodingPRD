"""Entity assertions, envelope helpers and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Field sets the PRD grants to every entity except the biological opinion.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_FIELDS = ("id", "created_at")


def assert_instant(value, field="instant"):
    """A server-produced instant: ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 UTC, got {value!r}"
    assert len(value) == 24 and value.endswith("Z") and value[19] == ".", (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


def assert_date(value, field="date"):
    """A date-only value of the form YYYY-MM-DD."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a plain YYYY-MM-DD date, got {value!r}"
    )


def normalize_instant(value):
    """Collapse the two accepted client instant spellings onto one comparable form.

    The PRD accepts whole seconds and exactly three fractional digits as the same
    instant, so comparisons against a client-supplied literal normalise both sides.
    """
    if not isinstance(value, str):
        return value
    text = value
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
        if frac == "000":
            text = head
        else:
            text = f"{head}.{frac}"
    return text + "Z"


def assert_same_instant(actual, expected, field="instant"):
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{field}: expected instant {expected!r}, got {actual!r}"
    )


def assert_common_fields(data, entity="entity"):
    """Every entity but the biological opinion carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert_instant(data.get("created_at"), f"{entity}.created_at")
    assert_instant(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and not isinstance(
        data.get("version"), bool
    ), f"{entity}.version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_two_decimals(value, field="quantity"):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must carry at most two decimal places, got {value!r}"
    )


def assert_cents(value, field="amount_cents"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )
    assert value >= 0, f"{field} must be non-negative, got {value!r}"


def assert_unpaginated_list(response, expected_status=200):
    """A sub-resource list: an array body whose pagination block is null.

    Returns the list of rows.
    """
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    for key in ("limit", "offset", "total_count", "has_more"):
        assert meta.get(key, None) is None, (
            f"an unpaginated list must leave meta.{key} null, got {meta.get(key)!r}"
        )
    data = body.get("data")
    assert isinstance(data, list), f"expected a list body, got {data!r}"
    return data


def assert_error_envelope(response, expected_error_id, expected_status):
    """An error body carrying exactly error_id and message, with the pinned status."""
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data")
    assert isinstance(data, dict), f"error data must be an object, got {data!r}"
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data must carry exactly error_id and message, got {sorted(data.keys())}"
    )
    assert data["error_id"] == expected_error_id, (
        f"expected {expected_error_id}, got {data['error_id']}"
    )
    assert isinstance(data["message"], str) and data["message"].strip(), (
        "error message must be a non-empty string"
    )
    assert data["message"] != data["error_id"], (
        "error message must be human readable, not a repeat of the error_id"
    )
    meta = body.get("meta") or {}
    assert "api_request_id" in meta and "api_request_timestamp" in meta, (
        f"error meta must keep api_request_id and api_request_timestamp, got {meta}"
    )
    return data


def assert_species(data):
    assert_common_fields(data, "species")
    assert 1 <= len(data["scientific_name"]) <= 120
    assert 1 <= len(data["common_name"]) <= 120
    assert data["listing_status"] in (
        "CANDIDATE",
        "PROPOSED",
        "THREATENED",
        "ENDANGERED",
    )
    assert isinstance(data["critical_habitat_designated"], bool)
    assert data["take_authorization_unit"] in ("INDIVIDUALS", "ACRES", "NESTS")
    assert_two_decimals(data["take_density_per_acre"], "species.take_density_per_acre")
    assert data["take_density_per_acre"] >= 0
    assert isinstance(data["recovery_unit_population"], int)
    assert data["recovery_unit_population"] >= 1
    assert 1 <= data["survey_season_start_month"] <= 12
    assert 1 <= data["survey_season_end_month"] <= 12
    assert isinstance(data["listing_change_count"], int)
    assert data["listing_change_count"] >= 0
    if data["last_listing_change_at"] is not None:
        assert_instant(data["last_listing_change_at"], "species.last_listing_change_at")


def assert_critical_habitat_unit(data):
    assert_common_fields(data, "critical_habitat_unit")
    assert is_valid_uuid(data["species_id"])
    assert 3 <= len(data["unit_code"]) <= 24
    assert_two_decimals(data["acres"], "critical_habitat_unit.acres")
    assert data["acres"] > 0
    assert len(data["county_code"]) == 5 and data["county_code"].isdigit()
    assert data["designation_status"] in ("PROPOSED", "FINAL")
    elements = data["primary_constituent_elements"]
    assert isinstance(elements, list) and 1 <= len(elements) <= 8
    for element in elements:
        assert isinstance(element, str) and 1 <= len(element) <= 80


def assert_proponent(data):
    assert_common_fields(data, "proponent")
    assert 1 <= len(data["org_name"]) <= 160
    assert 5 <= len(data["contact_email"]) <= 160
    assert data["contact_email"].count("@") == 1
    assert isinstance(data["is_federal_agency"], bool)
    assert_two_decimals(
        data["compliance_standing_score"], "proponent.compliance_standing_score"
    )
    assert 0 <= data["compliance_standing_score"] <= 100
    assert data["compliance_variant_applied"] in ("LIFETIME", "ROLLING_12_MONTH")
    assert isinstance(data["open_reinitiation_count"], int)
    assert data["open_reinitiation_count"] >= 0


def assert_project_action(data):
    assert_common_fields(data, "project_action")
    assert is_valid_uuid(data["proponent_id"])
    assert 1 <= len(data["action_name"]) <= 160
    assert data["action_type"] in ("FEDERAL_FUNDED", "FEDERAL_PERMITTED", "NON_FEDERAL")
    assert_two_decimals(data["footprint_acres"], "project_action.footprint_acres")
    assert data["footprint_acres"] > 0
    assert len(data["county_code"]) == 5 and data["county_code"].isdigit()
    assert_date(data["construction_start_date"], "project_action.construction_start_date")
    assert_date(data["construction_end_date"], "project_action.construction_end_date")
    assert data["construction_start_date"] <= data["construction_end_date"]
    assert data["status"] in (
        "SCREENING",
        "CLEARED_NO_EFFECT",
        "INFORMAL_CONSULTATION",
        "FORMAL_CONSULTATION",
        "CONSULTATION_CONCLUDED",
        "HCP_DEVELOPMENT",
        "PERMITTED",
        "REINITIATION_PENDING",
    )
    assert data["effect_determination"] in ("PENDING", "NO_EFFECT", "NLAA", "LAA")
    assert_two_decimals(data["total_overlap_acres"], "project_action.total_overlap_acres")
    assert_two_decimals(data["overlap_pct"], "project_action.overlap_pct")
    assert data["reinitiation_reason"] in (
        "NONE",
        "SPECIES_UPLISTED",
        "TAKE_EXCEEDANCE",
    )


def assert_presence_determination(data):
    assert_common_fields(data, "presence_determination")
    assert is_valid_uuid(data["project_action_id"])
    assert is_valid_uuid(data["species_id"])
    assert data["method"] in ("DATABASE_QUERY", "FIELD_SURVEY")
    assert data["detection_result"] in ("DETECTED", "NOT_DETECTED", "INCONCLUSIVE")
    assert_two_decimals(
        data["habitat_overlap_acres"], "presence_determination.habitat_overlap_acres"
    )
    assert data["habitat_overlap_acres"] >= 0
    assert data["presence_status"] in (
        "PRESENT",
        "PRESUMED_PRESENT",
        "PRESUMED_ABSENT",
        "ABSENT",
    )
    assert isinstance(data["survey_in_season"], bool)
    assert isinstance(data["requires_reevaluation"], bool)
    if data["method"] == "DATABASE_QUERY":
        assert data["survey_window_start"] is None
        assert data["survey_window_end"] is None
        assert data["survey_in_season"] is False
    else:
        assert_date(
            data["survey_window_start"], "presence_determination.survey_window_start"
        )
        assert_date(data["survey_window_end"], "presence_determination.survey_window_end")
        assert data["survey_window_start"] <= data["survey_window_end"]


def assert_consultation(data):
    assert_common_fields(data, "consultation")
    assert is_valid_uuid(data["project_action_id"])
    assert data["consultation_type"] in ("INFORMAL", "FORMAL")
    assert data["status"] in (
        "DRAFT_BA",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "CONCLUDED_CONCURRENCE",
        "OPINION_ISSUED",
        "REINITIATION_REQUIRED",
    )
    assert isinstance(data["ba_revision_number"], int)
    assert data["statutory_days"] in (60, 135)
    assert isinstance(data["tolled_days"], int) and data["tolled_days"] >= 0
    assert_instant(data["clock_started_at"], "consultation.clock_started_at")
    assert_instant(data["deadline_at"], "consultation.deadline_at")
    assert isinstance(data["info_request_count"], int)
    assert 0 <= data["info_request_count"] <= 2
    assert isinstance(data["reinitiation_count"], int)


def assert_biological_opinion(data):
    """The opinion is append-only: it carries id and created_at but no version."""
    assert is_valid_uuid(data.get("id", "")), "biological_opinion.id must be a UUID"
    assert_instant(data.get("created_at"), "biological_opinion.created_at")
    assert "updated_at" not in data, "an append-only opinion carries no updated_at"
    assert "version" not in data, "an append-only opinion carries no version"
    assert is_valid_uuid(data["consultation_id"])
    assert data["take_unit"] in ("INDIVIDUALS", "ACRES", "NESTS")
    assert_two_decimals(data["exposed_acres"], "biological_opinion.exposed_acres")
    assert_two_decimals(
        data["authorized_take_units"], "biological_opinion.authorized_take_units"
    )
    assert_two_decimals(
        data["reinitiation_trigger_units"],
        "biological_opinion.reinitiation_trigger_units",
    )
    fraction = data["jeopardy_fraction"]
    assert isinstance(fraction, (int, float)) and not isinstance(fraction, bool)
    assert round(float(fraction), 4) == float(fraction), (
        f"jeopardy_fraction must carry at most four decimals, got {fraction!r}"
    )
    assert isinstance(data["rpa_required"], bool)
    assert data["conclusion"] in ("NO_JEOPARDY", "JEOPARDY", "JEOPARDY_WITH_RPA")
    assert isinstance(data["issued_late"], bool)
    assert_instant(data["issued_at"], "biological_opinion.issued_at")
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]


def assert_conservation_bank(data):
    assert_common_fields(data, "conservation_bank")
    assert 1 <= len(data["bank_name"]) <= 160
    assert is_valid_uuid(data["covered_species_id"])
    codes = data["service_area_county_codes"]
    assert isinstance(codes, list) and 1 <= len(codes) <= 12
    for code in codes:
        assert isinstance(code, str) and len(code) == 5 and code.isdigit()
    assert_cents(data["credit_price_cents"], "conservation_bank.credit_price_cents")
    assert data["credit_price_cents"] > 0
    for field in (
        "credits_total_minted",
        "credits_available",
        "credits_reserved",
        "credits_transferred",
    ):
        assert_two_decimals(data[field], f"conservation_bank.{field}")
        assert data[field] >= 0
    assert_bank_ledger_identity(data)


def assert_bank_ledger_identity(bank):
    """credits_available + credits_reserved + credits_transferred == credits_total_minted."""
    total = round(
        bank["credits_available"] + bank["credits_reserved"] + bank["credits_transferred"],
        2,
    )
    assert total == round(bank["credits_total_minted"], 2), (
        "bank credit ledger identity broken: "
        f"{bank['credits_available']} + {bank['credits_reserved']} + "
        f"{bank['credits_transferred']} != {bank['credits_total_minted']}"
    )


def assert_take_ledger_identity(permit):
    """authorized_take_units == take_consumed_units + take_remaining_units."""
    total = round(permit["take_consumed_units"] + permit["take_remaining_units"], 2)
    assert total == round(permit["authorized_take_units"], 2), (
        "permit take ledger identity broken: "
        f"{permit['take_consumed_units']} + {permit['take_remaining_units']} != "
        f"{permit['authorized_take_units']}"
    )


def assert_response_cost_identity(event):
    """permittee_borne_cents + agency_borne_cents == response_cost_cents."""
    assert (
        event["permittee_borne_cents"] + event["agency_borne_cents"]
        == event["response_cost_cents"]
    ), (
        "circumstance cost allocation identity broken: "
        f"{event['permittee_borne_cents']} + {event['agency_borne_cents']} != "
        f"{event['response_cost_cents']}"
    )


def assert_habitat_conservation_plan(data):
    assert_common_fields(data, "habitat_conservation_plan")
    assert 1 <= len(data["plan_name"]) <= 160
    assert_two_decimals(data["covered_acres"], "habitat_conservation_plan.covered_acres")
    assert data["covered_acres"] > 0
    assert isinstance(data["permit_term_years"], int)
    assert 1 <= data["permit_term_years"] <= 50
    assert data["plan_status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "IMPLEMENTING",
        "SUSPENDED_IMPLEMENTATION",
        "CLOSED",
    )
    assert data["funding_status"] in ("UNFUNDED", "PARTIALLY_ASSURED", "FULLY_ASSURED")
    assert_two_decimals(
        data["preliminary_mitigation_units"],
        "habitat_conservation_plan.preliminary_mitigation_units",
    )
    for field in ("final_mitigation_units", "mitigation_delta_units"):
        if data[field] is not None:
            assert_two_decimals(data[field], f"habitat_conservation_plan.{field}")
    assert_two_decimals(
        data["secured_mitigation_units"],
        "habitat_conservation_plan.secured_mitigation_units",
    )
    for field in (
        "endowment_base_cents",
        "changed_circumstance_reserve_cents",
        "endowment_required_cents",
        "endowment_secured_cents",
        "reserve_drawn_cents",
        "reserve_remaining_cents",
    ):
        assert_cents(data[field], f"habitat_conservation_plan.{field}")
    ratio = data["funded_ratio"]
    assert isinstance(ratio, (int, float)) and not isinstance(ratio, bool)
    assert round(float(ratio), 4) == float(ratio), (
        f"funded_ratio must carry at most four decimals, got {ratio!r}"
    )
    assert isinstance(data["assurance_review_required"], bool)


def assert_mitigation_commitment(data):
    assert_common_fields(data, "mitigation_commitment")
    assert data["mechanism"] in (
        "CONSERVATION_BANK_CREDIT",
        "IN_LIEU_FEE",
        "PERMITTEE_RESPONSIBLE",
    )
    assert_two_decimals(data["units"], "mitigation_commitment.units")
    assert data["units"] > 0
    assert data["status"] in ("RESERVED", "SECURED", "RELEASED")
    for field in (
        "base_fee_cents",
        "admin_fee_cents",
        "total_cost_cents",
        "endowment_contribution_cents",
    ):
        assert_cents(data[field], f"mitigation_commitment.{field}")
    pct = data["admin_fee_pct_applied"]
    assert isinstance(pct, (int, float)) and not isinstance(pct, bool)
    assert round(float(pct), 3) == float(pct), (
        f"admin_fee_pct_applied must carry at most three decimals, got {pct!r}"
    )
    assert data["total_cost_cents"] == data["base_fee_cents"] + data["admin_fee_cents"], (
        "total_cost_cents must be the sum of base_fee_cents and admin_fee_cents"
    )


def assert_incidental_take_permit(data):
    assert_common_fields(data, "incidental_take_permit")
    assert is_valid_uuid(data["hcp_id"])
    number = data["permit_number"]
    assert number.startswith("ITP-") and len(number) == 10 and number[4:].isdigit(), (
        f"permit_number must be ITP- followed by six digits, got {number!r}"
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert_date(data["term_start"], "incidental_take_permit.term_start")
    assert_date(data["term_end"], "incidental_take_permit.term_end")
    assert 6 <= len(data["implementing_agreement_reference"]) <= 64
    assert data["take_unit"] in ("INDIVIDUALS", "ACRES", "NESTS")
    for field in (
        "authorized_take_units",
        "reinitiation_trigger_units",
        "take_consumed_units",
        "take_remaining_units",
    ):
        assert_two_decimals(data[field], f"incidental_take_permit.{field}")
    assert isinstance(data["suspension_count"], int)
    assert data["suspension_count"] >= 0
    assert_take_ledger_identity(data)


def assert_monitoring_report(data):
    assert_common_fields(data, "monitoring_report")
    assert is_valid_uuid(data["permit_id"])
    assert_date(data["period_start"], "monitoring_report.period_start")
    assert_date(data["period_end"], "monitoring_report.period_end")
    assert data["period_start"] < data["period_end"]
    assert_two_decimals(
        data["take_units_reported"], "monitoring_report.take_units_reported"
    )
    assert data["take_units_reported"] >= 0
    assert_two_decimals(
        data["mitigation_units_verified"], "monitoring_report.mitigation_units_verified"
    )
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert_instant(data["submitted_at"], "monitoring_report.submitted_at")
    assert_date(data["due_at"], "monitoring_report.due_at")
    assert isinstance(data["is_late"], bool)
    if data["status"] == "SUBMITTED":
        assert data.get("adjudicated_at") is None
        assert data.get("adjudicated_by_user_id") is None
    else:
        assert_instant(data["adjudicated_at"], "monitoring_report.adjudicated_at")
        assert data["adjudicated_by_user_id"]


def assert_changed_circumstance_event(data):
    assert_common_fields(data, "changed_circumstance_event")
    assert is_valid_uuid(data["hcp_id"])
    assert data["circumstance_type"] in ("CHANGED", "UNFORESEEN")
    assert 1 <= len(data["description"]) <= 400
    assert_cents(data["response_cost_cents"], "changed_circumstance_event.response_cost_cents")
    assert data["response_cost_cents"] > 0
    assert data["status"] in (
        "RESPONSE_REQUIRED",
        "RESPONDED",
        "ASSURANCES_INVOKED",
    ), f"a circumstance event is never returned in REPORTED, got {data['status']!r}"
    assert_instant(data["reported_at"], "changed_circumstance_event.reported_at")
    for field in (
        "reserve_draw_cents",
        "required_additional_cents",
        "permittee_borne_cents",
        "agency_borne_cents",
    ):
        assert_cents(data[field], f"changed_circumstance_event.{field}")
    assert isinstance(data["assurances_invoked"], bool)
    assert_response_cost_identity(data)
