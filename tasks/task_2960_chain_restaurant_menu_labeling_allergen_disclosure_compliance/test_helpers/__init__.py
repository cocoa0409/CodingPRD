"""Test infrastructure for the chain-restaurant menu labeling compliance API.

Modules:
  constants   - enum symbols, business constants and role names from the PRD
  api_errors  - the error identifier catalogue and its HTTP status mapping
  types       - TypedDict shapes for every persisted entity
  test_users   - the fixed test identities and their auth headers
  api_client  - one method per endpoint of the PRD's endpoint table
  assertions  - domain assertion helpers (envelopes, timestamps, ledgers)
  factories   - request payload builders carrying PRD-valid defaults
  fixtures    - pytest fixtures, including composite multi-step scenarios
"""
