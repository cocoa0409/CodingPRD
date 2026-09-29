
### Step 2c — SCAFFOLD_CORNER_DESIGN.yaml (§1.9)

Done. `SCAFFOLD_CORNER_DESIGN.yaml` is complete and lint-clean.

- **Sections**: 9 — `entities` 14, `state_machines` 17, `calculations` 14, `validations` 10, `endpoints` 10, `errors` 8, `rbac` 8, `cross_cutting_layers` 9, `consistency_model` 2
- **Non-stub instances**: 92 (zero `excluded_because` stubs), 732 assert lines, 3178 API calls
- **Final line count**: 6284
- Single top-level key `scaffold_corner_design`; parses under `yaml.safe_load`

Coverage: all 59 endpoints, all 96 error ids (partitioned and asserted reachable, with two documented structurally-unreachable corners), all 7x59 = 413 RBAC cells (218 permitted / 195 refused), every enum, and the inclusive/exclusive boundary census.

Verification note — ran the skill's `scaffold_lint.py` on the task dir and it initially reported 55 violations, which exposed that several endpoint paths and payload field names had been assumed rather than read from §1.5. Re-read the real §1.5/§1.2.1 tables and corrected everything:

- Real endpoints substituted for invented ones: `POST /_clock/set_current_utc` (there is **no** clock read endpoint), `GET /transmitters/{id}/notifications`, `GET /playlists/{id}/as-run`, `GET /playlists/{id}/reconciliation`, `GET /qc-reports`, `POST /technical-faults/{id}/state`, `POST /emergency-overrides/{id}/activate`, `POST /spot-orders/{id}/makegoods` (no `/playlist-items/{id}/makegood`, no `/eas-activations`).
- Payload keys corrected (`narrative`, `pin_allocated_kbps`, `full_name`, `broadcast_day`/`schedule_start_utc`/`items`, `replacement_asset_id`, faults' `severity`+`channel_id`/`transmitter_id`).
- **The OCC census was materially wrong and is now rewritten from §1.2.1**: only 6 OCC rules over 3 token fields (`expected_playlist_version` on traffic-revisions + makegoods, `expected_multiplex_version` on channel-create/allocation/rebalance, `expected_asset_version` on qc-reports). There are no operator/override/item tokens, so `cross_cutting_layers` L1–L5 now cover: parent-scoped batch revisions, the makegood whose path/token/response are three different entities, the three-endpoint multiplex counter, the asset token's single reachable call site, and the 20+ token-free last-writer-wins mutators.
- Capture JSONPaths fixed to declared fields (`$.data.verdict`, `$.data.starved_channel_count`), and hardcoded OCC literals replaced with setup-captured stale tokens.

Final lint from the §1.9 agent: **0 violations attributable to §1.9**. One violation remained in the sibling-owned `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 instance `full_power_restore_refused_while_an_escalated_rf_fault_is_open`, `POST /technical-faults` missing required `severity`).

### Step 2 closeout (orchestrator)

The orchestrator fixed that one remaining §1.8 violation directly — added `severity: "MAJOR"` to the `POST /technical-faults` setup call in `full_power_restore_refused_while_an_escalated_rf_fault_is_open` (the instance's own setup prose already specified severity MAJOR, so the payload was simply incomplete). Re-ran `scaffold_lint.py` across all three files:

```
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     92
  Calls scanned (§1.8+§1.9):  3178
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
