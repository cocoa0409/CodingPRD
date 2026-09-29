"""Test infrastructure for the Biosolids Management & Land Application API.

Layers:
  constants   - PRD-declared literals, enum vocabularies, endpoint roots
  types       - payload TypedDicts
  api_errors  - error id catalogue + error_id -> HTTP status registration
  api_client   - one method per declared endpoint
  factories   - valid-by-default request payload builders
  assertions  - domain assertion helpers
  test_users  - identity headers per role
  fixtures    - composite state builders driving the declared API only
"""
