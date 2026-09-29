"""Test helpers for the Pressure Vessel Fabrication API.

Re-exports the pieces test modules use most often. The framework primitives
(``validate_success``, ``validate_error``, ``validate_paginated``,
``get_success_data``, ``run_race`` and friends) are imported from
``prd_bench_local_runner.testing`` directly by the test modules.
"""

from . import assertions, constants, factories, types  # noqa: F401
from .api_client import ApiClient, canonical_instant, same_instant  # noqa: F401
from .api_errors import (  # noqa: F401
    ERROR_HTTP_STATUS,
    NOT_FOUND_BY_RESOURCE,
    expected_status,
    register_error_status_map,
)
from .assertions import (  # noqa: F401
    assert_append_only_audit_fields,
    assert_created_at_unchanged,
    assert_envelope_meta,
    assert_error_envelope,
    assert_full_audit_fields,
    assert_number_equals,
    assert_pagination_meta,
    assert_response_type,
    assert_scale,
    assert_sorted_by_created_at,
    assert_three_fractional_digits,
    assert_updated_at_advanced,
    assert_version_advanced,
    expected_category_b_coverage,
    expected_completeness_score,
    expected_governing_variant,
    expected_min_medium_temp,
    expected_missing_items,
    expected_required_soak_minutes,
    expected_required_thickness,
    expected_section_points,
    expected_test_pressure,
    expected_thickness_pair,
    expected_volumetric_method,
    expected_weld_completion_pct,
    round_half_up,
)
from .fixtures import ShopWorkflow  # noqa: F401
from .test_users import (  # noqa: F401
    SHOP_ADMIN_OPERATOR_ID,
    UNDECLARED_ROLE,
    headers_blank_role,
    headers_blank_user_id,
    headers_for_person,
    headers_for_role_code,
    headers_missing_role,
    headers_missing_user_id,
    headers_no_authentication,
    headers_undeclared_role,
    make_authorized_inspector_headers,
    make_design_engineer_headers,
    make_headers,
    make_qc_inspector_headers,
    make_welding_engineer_headers,
    shop_admin_headers,
)
