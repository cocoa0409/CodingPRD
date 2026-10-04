# Worklog — task_3256_usage_based_observability_billing_host_attribution_log

## Step 1: Create Task Directory — 2026-09-30T14:54:00.000Z

Task directory `./tasks/task_3256_usage_based_observability_billing_host_attribution_log/` was pre-allocated (with `workspace/` inside) and verified to exist; used as-is per command instructions.

## Step 2: Generate Scaffold — 2026-09-30T15:10:00.000Z

## Scaffold generation complete: task_3256

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3256_usage_based_observability_billing_host_attribution_log/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Validation status** — all three files pass `scaffold_lint.py`:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs
have reverse-reachability in §1.5.
```
Checks (a)–(f) all green: endpoint declared, role allowed, payload shape, capture resolution, OCC version dynamic, FK reverse-reachability. 282 calls scanned across §1.8+§1.9.

**Counts**:
- SCAFFOLD.yaml: 18 entities, 6 state machines, 9 calculations, 13 validations, 84 endpoints, 15 errors, 5 roles, 2 concurrency_rules
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rule_ids × 2 instances each = 18 instances (every §0.5 rule satisfied)
- SCAFFOLD_CORNER_DESIGN.yaml: 9 sections × mixed claim_types = 24 instances, all active (no excluded_because stubs needed)

**Difficulty levers exercised** (per "much harder than expert"):
- Rule 1 dual-variant calc on two distinct entity domains: HWM vs P99 host billing (HostHourRecord), provisional-vs-final log charging (LogEvent).
- Rule 2 combinatorial formulas in two different modes: per-line-then-sum rounding (mode b) on InvoiceLine totals, 3-input min/max commitment overage (mode a).
- Rule 3 non-linear state machines on two entities: CardinalityIncident VERIFIED→OPEN recurrence cycle, Commitment ACTIVE→EXHAUSTED→ACTIVE top-up cycle.
- Rule 4 transitive cascades from different triggers: reindex cascade (depth 4 — LogEvent→MeterAccumulator→Commitment→EXHAUSTED) and remediate cascade (depth 3 — Incident→Series→MeterAccumulator stop).
- Rule 5 priority conflicts across distinct error-category pairs: state vs business_temporal; business_temporal vs business_referential.
- Rule 6 boundary precision on distinct metrics/endpoints: at-cap monitor create (>= semantics) and empty-set HWM/P99.
- Rule 7 cross-entity state dependencies on distinct pairs: Commitment→BillingAccount (standing==GOOD), LogEvent→BillingPeriod (status==OPEN).
- Rule 8 temporal overlap with different interval semantics: closed-interval commitment windows (touching endpoints DO overlap) vs half-open retention-tier windows (touching endpoints do NOT overlap).
- Rule 9 compensating invariants on distinct conserved quantities: LOG_INGEST bytes == INDEXED + EXCLUDED; consumed + expired == committed across top-up.

**Design choices**: api_prefix `/api` (so the lint can derive BillingAccount's collection segment from `GET /api/billing-accounts/{id}`); logical clock endpoint `POST /_clock/set_current_utc` with default `2026-09-01T00:00:00Z`; OCC via `expected_billing_account_version` on Commitment and RetentionTier creates; all FK child entities have both nested and flat filtered-list GETs to satisfy reverse-reachability.

## Step 3: Copy Shared Files — 2026-09-30T15:10:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3256_usage_based_observability_billing_host_attribution_log/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T15:20:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3256_usage_based_observability_billing_host_attribution_log/workspace/PRD.md`. The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

Structure: §1 introduction (3 paragraphs), §2 with 10 subsections (RBAC + identity semantics, verbatim §2.2 envelope, pagination, common resource properties incl. the `InvoiceLine` `common_fields: false` exception, the 13-step priority-ordered validation pipeline, logical clock, money/rounding, OCC, half-open vs closed window arithmetic, hierarchical cascades), §3 with 9 subsections organized by business workflow (accounts/tiers/periods, host attribution + dual billable counts, log ingest/exclusion/reindex, commitments/overage, retention tiers, teams/tag governance/disputes, cardinality incidents, monitors/plan caps, period close/invoicing/settlement/chargeback), §4 four-column endpoint table (83 endpoints), §5 two-column error catalogue (15 errors).

Hard Contract Reports:

Field coverage check: PASS — 61/61 entity fields present, 9/9 additional endpoint identifiers present, all list query params present, 70/70 unique required identifiers in backticks (verified mechanically).
Rule coverage check: PASS — 13/13 prioritized validations, 2/2 OCC concurrency rules, 19/19 state transitions across 6 state machines, 8/8 calculations, 13/13 validation conditions, all endpoint side_effects/applies_to expressed, all entity field defaults + InvoiceLine common_fields=false exception stated, all sibling-branch pairs rendered symmetric.
Path purity check (§3 only): PASS — 282 backtick tokens scanned, 0 path tokens, 0 bare HTTP-method tokens, 0 method+path tokens.

Also verified: §2.2 block is byte-identical to the canonical `section-2.2-response-structure.md`; all enum/state values (`FREE`/`PRO`/`ENTERPRISE`, `OPEN`→`CLOSED`→`SETTLED`, `DRAFT`→`ACTIVE`→`EXHAUSTED`→`SETTLED`, etc.) appear verbatim; all 15 error IDs are present.

## Step 5: Generate Unit Tests — 2026-09-30T15:45:00.000Z

Complete. Test infrastructure and suite generated for task_3256.

**What was produced**

`test_helpers/` (9 files):
- `types.py` — all 17 entity TypedDicts + status/role enums; `InvoiceLine` correctly omits `updated_at`/`version` (PRD §2.4 immutability rule)
- `api_client.py` — one method per PRD §4 endpoint, including all flat `/api/<resource>/{id}` GETs and the out-of-band `/_clock/set_current_utc`
- `api_errors.py` — all 15 error IDs from PRD §5, registered with the framework's status map
- `assertions.py` — per-entity validators + commitment conservation invariant
- `factories.py`, `constants.py` (ENTERPRISE/FREE rate cards, soft cap 10000, period windows), `test_users.py` (5 roles; `make_team_lead_headers` builder for the entity-backed TeamLead), `fixtures.py` (5 tiers: clock/account/period primitives, hierarchy setups, incident lifecycle walkers through VERIFIED, commitment consumption accumulators, settled-period terminal states), `__init__.py` barrel

`test_suite/` — `conftest.py` + 8 test files, **80 test functions**.

**Coverage audit (all green)**
- 18/18 difficulty-design instances with ≥2 tests each, tagged `Design: Difficulty/<rule_id>/<instance.name>`
- 24/24 corner-design instances with ≥1 test each, tagged `Design: Corner/<section>/<instance.name>`
- Every tag verified to resolve to a real instance name in the source YAMLs (rule/section names cross-checked)
- Every quoted PRD citation verified verbatim against PRD.md (0 non-verbatim after markdown/whitespace normalization)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" mentions in generated code
- All files compile; `test_helpers` imports cleanly (138 exports)

**Notable adjudication choices**
- `host_billable_count_hwm_vs_p99_diverge`: PRD doesn't expose HWM/P99 as response fields, so tests assert via the observable surface the PRD pins — the `INFRA_HOST` invoice line's `rated_quantity` equals min(HWM, P99) after close, with the P99 rank-index arithmetic cross-checked independently.
- `commitment_activate_requires_account_good_standing`: the instance's DELINQUENT branch is not reachable via PRD-stated API operations (no endpoint flips standing), so the two tests cover the GOOD-path activation and the DRAFT-state precondition, both of which the PRD uniquely derives.
- Hard-exclusion reindex test asserts rejection + state preservation without pinning a specific error_id (PRD names the rule but not the error code for that branch).
- No test was dropped entirely; every index instance translated.

## Step 6: Generate Implementation — 2026-09-30T15:56:00.000Z

The implementation is complete and verified. All files are in `workspace/implementation/`:

- `start.sh` — foreground launcher, guards pip install on `import flask`, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — all 60+ endpoints from the SCAFFOLD endpoint table, including nested routes, flat single-resource GETs, filtered lists, and `POST /_clock/set_current_utc`
- `helpers.py` — logical clock (fixed default `2026-09-01T00:00:00Z`, never wall clock), payload validation, auth, meter/commitment helpers, filter selection (glob + priority ASC + created_at ASC, id never used as tie-break), deterministic CRC32-based sampling
- `db.py` — empty in-memory store; nothing seeded at boot
- `errors.py`, `response.py` — error catalog and the `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` in meta for lists

Key spec decisions implemented:
- Validation pipeline in PRD §2.5 priority order: auth → RBAC → path existence (left-to-right) → body FKs → period openness → entity state → tier window → commitment window → plan cap → standing → tag policy → OCC → schema. The two OCC endpoints (commitment create, retention-tier create) check `expected_billing_account_version` → `ERR_STALE_VERSION` (412) and bump the account version on success.
- RetentionTier half-open overlap plus the gap rule; Commitment closed-interval overlap including single-endpoint touches.
- Host billing at close: HWM and P99 (`ceil(0.99*n)` rank, 1-based) over `infra+container` footprints, charged count = min; INFRA_HOST accumulator topped up to the charged count so the draft invoice carries one line per non-zero meter.
- Commitment drawdown on every positive meter bump: `min(delta, headroom)` debited to `committed_consumed_quantity`, auto-transition to EXHAUSTED at full consumption; top-up guarded by logical clock vs `window_end_utc` and window overlap; close settles elapsed ACTIVE (`expired = committed - consumed`) and EXHAUSTED (`expired = 0`) commitments.
- Log ingest: `LOG_INGEST` charged on all events, `LOG_INDEX` only when INDEXED; excluded events carry `retention_tier_id: null`; reindex requires an OPEN period, no matching enabled filter with `sample_rate_pct == 0`, and an ACTIVE LOG_INDEX commitment (`ERR_NO_ACTIVE_COMMITMENT` otherwise).
- Cardinality incident machinery: strict `>` against `included_custom_metrics + 10000`; remediate quarantines the series and debits the CUSTOM_METRIC meter; two consecutive below-threshold snapshots move REMEDIATED → VERIFIED; a VERIFIED incident crossing threshold again loops to OPEN and re-quarantines; close restores ACTIVE and re-credits the meter; OPEN incidents block period close with `ERR_OPEN_INCIDENTS_BLOCK_CLOSE`.
- Invoice issue computes per-line amounts (committed qty × committed rate + overage qty × overage rate, round-half-up — all values are integer cents so rounding is exact) and sums the rounded lines.
- Chargeback rollup is computed on demand: compliant, undisputed, team-attributed records rate into per-team buckets; non-compliant or team-less records aggregate into `unattributed_cents`; disputed records sit out entirely.
- InvoiceLine is immutable per PRD §2.4: only `id` + `created_at`, no `updated_at`/`version`.

Verification performed (not the benchmark test suite): syntax-compiled all modules, booted via `start.sh` on a self-allocated port, ran an end-to-end smoke flow (401/403 auth, account/period/hosts/logs, duplicate host hour 409, early close 409, close → invoice lines for LOG_INDEX/LOG_INGEST/INFRA_HOST, issue → pay → settle, period-closed 409), then confirmed a fresh boot returns an empty store. Both test servers it started were killed by exact PID.

## Step 7: Run Tests and Iterate — 2026-09-30T16:15:00.000Z

Done. All 8 parallel rounds pass 80/80 after 3 iterations.

## Summary

**Iterations run:** 3 (sweep 1: 6 failing tests consistently across all 8 rounds; sweep 2: 2 remaining; sweep 3: clean 8×80/80).

**Tests deleted:** none — every failure traced to a fixable test bug or implementation bug, with the PRD rule verbatim-covered in each case.

**Fixes applied to `test_suite/`:**
- `test_06_invoices_and_settlement.py` — module helper `_lines()` referenced undefined `account` instead of its `account_id` parameter (`NameError` in both `TestPerLineRounding` tests). Plain test bug.
- `test_01_accounts_and_access.py::test_team_lead_cannot_close_billing_period` — `validate_success` on `create_team` expected 200; PRD §4 states "Operations that create a new resource return a `201 Created`". Passed `expected_status=201`.
- `test_02_host_hours_and_periods.py::test_hwm_and_p99_diverge_charged_is_min` — the fixture used 5 hour samples, but with n=5 the PRD §3.2 rank formula `ceil(0.99·n)=5` always lands on the max, so P99=HWM=50 and the test's own intermediate assertion (`expected_p99 == 12`) was self-contradictory. Rebuilt with 101 hour buckets (100 at combined 12 + one spike at 50) so rank=100 yields P99=12, HWM=50, and the charged count is verifiably the smaller (12). Test now faithfully expresses the PRD divergence rule.
- `test_03_logs_filters_reindex.py::test_provisional_ingest_leg_only_on_excluded_events` — asserted a zero-quantity LOG_INDEX accumulator exists; PRD §3.3 says only that excluded events do not *increase* the index accumulator, and is silent on eager vs lazy accumulator creation (DEFAULT-VALUE-style silence). Relaxed to: accumulator absent OR quantity 0, keeping the covered "no index bump on excluded events" assertion.
- `test_07_chargeback_and_disputes.py::test_compliant_records_roll_up_per_team_unattributed_bucket_captures_rest` — posted TRACE usage and asserted `unattributed_cents > 0`, but PRD §2/§3.4 gives PlanTierConfig only four rate fields (host, log-ingest, log-index, custom-metric); TRACE has no plan fallback rate, so a PRD-faithful implementation legitimately rates it 0. Switched the records to INFRA_HOST (whose `host_overage_rate_cents` fallback is PRD-specified), keeping the rollup-bucketing assertions intact.

**Fixes applied to `implementation/`:**
- `helpers.py::new_record` — added `immutable` flag (sets `created_at` but not `updated_at`/`version`); `app.py` invoice-line creation now uses it. PRD §2.4: "an `InvoiceLine` ... carries only `id` and `created_at`" — the implementation was omitting `created_at`. This was the root cause of the final 2 failures (`assert_invoice_line` rejecting the missing timestamp).

## Step 8: Finalize PRD — 2026-09-30T16:20:00.000Z

Done. Two minimal in-place edits, no other changes.

## Summary

**Line counts:** PRD.md 356 lines → PRD_FINALIZED.md 356 lines (0% delta; two sentences appended in-place, no lines added/removed).

**Changes (one bullet each):**

- **§3.1 — revise** — appended: `PlanTierConfig` carries no rate fields for `TRACE`/`SYNTHETIC`; with no active commitment their fallback on-demand rate is zero cents per unit, for both invoice lines and chargeback — `implementation/helpers.py:305-316` (`plan_overage_rate_cents` maps `TRACE`/`SYNTHETIC` → 0), `implementation/helpers.py:319-334` (`rate_usage_amount_cents`, chargeback path), `implementation/app.py:301-305` (invoice-line rate selection at close).
- **§3.3 — revise** — appended: the `LOG_INDEX` accumulator is created lazily; an ingest landing `EXCLUDED` does not create it; the first `LOG_INDEX` unit (indexed ingest or successful reindex) creates it — `implementation/app.py:512-514` (`LOG_INDEX` bump only under `INDEXED`), `implementation/helpers.py:247-259` (`get_or_create_accumulator` creates on first bump), `implementation/app.py:551` (reindex bump).

**Step-7 items with no PRD change:** the `test_06` `_lines()` NameError (pure test bug); 201-vs-200 on `create_team` (PRD §4 already pins 201 for creates); the n=5 P99 fixture (PRD §3.2's `ceil(0.99·n)` rank formula already pinned verbatim); the InvoiceLine `created_at` fix (PRD §2.4 already pinned "carries only `id` and `created_at`" — impl was fixed to match the PRD, not vice versa).

**Per-edit pre-edit search log:**

- **Edit 1 (§3.1, TRACE/SYNTHETIC zero fallback):** (a) subject: plan fallback on-demand rate for meters without a PlanTierConfig rate field. (b) paths enumerated: `helpers.py:305-316` `plan_overage_rate_cents` (the mapping); its callsites `helpers.py:333-334` (`rate_usage_amount_cents`, used by chargeback at `app.py:1581`) and `app.py:301-305` (close-time invoice-line rate fallback); also checked the commitment-active path (`helpers.py:326-332`) where commitment rates, not the fallback, apply. (c) wording scoped to "when no active commitment covers one of those meters" and names both invoice-line and chargeback rating, so the commitment-covered path and other meters are not mis-described.
- **Edit 2 (§3.3, lazy LOG_INDEX accumulator):** (a) subject: when the `LOG_INDEX` meter accumulator comes into existence. (b) paths enumerated: every `bump_meter`/`get_or_create_accumulator` callsite — `app.py:512-514` (log ingest: LOG_INGEST always, LOG_INDEX only when INDEXED), `app.py:551` (reindex, delta=1), `app.py:789-791/810-811/903-907/923-927` (CUSTOM_METRIC only), `app.py:1180` (`create_usage_record` — note: delta=0 still creates a zero accumulator here), `app.py:284-287` (INFRA_HOST at close, only when charged>0); `helpers.py:247-259` (create-on-first-bump semantics). (c) wording deliberately scoped to the `LOG_INDEX` leg only — a broader "all accumulators are lazy / created only on non-zero quantity" claim would be false because a zero-quantity usage record does create a zero-quantity accumulator (`app.py:1180` → `helpers.py:289-290`).

Files: `workspace/PRD_FINALIZED.md` (created), source `workspace/PRD.md` (untouched).

## Step 9: Complete PRD — 2026-09-30T16:35:00.000Z

Done. PRD_COMPLETED.md produced and verified: the §4 endpoint table matches the implementation exactly (84/84 routes, methods, and role sets verified programmatically).

## Summary

**Source:** `PRD_FINALIZED.md` (356 lines / 46,761 chars) → `PRD_COMPLETED.md` (356 lines / 52,903 chars; +6,142 chars, 23 in-paragraph edits, no new sections).

**Counts:** 17 ambiguity-pins, 6 mismatch-revisions.

**Changes (section — kind — classification — what — impl ref):**

- §2.1 — revise — mismatch — TeamLead `X-User-ID` is recorded but never compared to any entity FK; TeamLead access is uniform per endpoint — `app.py:187-197` (`check_auth`/`require_roles` only).
- §2.3 — insert — ambiguity — list sort tie-break is `id` ascending; non-integer `limit`/`offset`, out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` — `app.py:70`, `helpers.py:147-169`.
- §2.5 item 13 — insert — ambiguity — unknown payload keys (incl. client-supplied `id`/`version`/`created_at`/`updated_at`) are ignored; system fields server-assigned — `app.py:139-146` (fixed `new_record` fields).
- §2.6 — insert — ambiguity — early close and late top-up both rejected with `ERR_INVALID_STATE`; clock endpoint returns `{current_utc}` — `app.py:243-244`, `app.py:1047-1048`, `app.py:122`.
- §2.7 — insert — ambiguity — every rate and quantity is an integer, so amounts evaluate as exact integer products (round-half-up is the design stance) — `app.py:1494-1496`.
- §2.8 — insert — ambiguity — OCC bump also refreshes the account's `updated_at` — `app.py:995,616` (`touch(account)`).
- §3.1 — revise — mismatch — removed the invoice-aging→`DELINQUENT` transition (nothing in the API mutates `standing`; guard is latent); anchor range enforced via `ERR_INVALID_REQUEST`; `standing` always server-set to `GOOD` — `app.py:129-146`.
- §3.1 — revise — mismatch — `plan_tier` uniqueness not enforced across configs; earliest-created config wins for an account — `app.py:172-187`, `helpers.py:240-244`.
- §3.2 — insert — ambiguity — the three host counts are required integers; recording samples never moves the `INFRA_HOST` accumulator (charged count applied at close) — `app.py:401-403`, `app.py:277-287`.
- §3.3 — insert — ambiguity — glob match is case-sensitive; the sampling hash is pinned as CRC32 of the UTF-8 `service_tag`, unsigned, mod 100; out-of-range `sample_rate_pct` → `ERR_INVALID_REQUEST` — `helpers.py:347` (`fnmatch.fnmatchcase`), `helpers.py:355-359`, `app.py:659-660`.
- §3.3 — insert — ambiguity — ingesting an unknown/cross-account `retention_tier_id` → `ERR_NOT_FOUND`; a tier id supplied on an event landing `EXCLUDED` is discarded and not restored by reindex — `app.py:498-501,502`.
- §3.3 — insert — ambiguity — `ingested_at_utc` is required; transient `PENDING` never observable — `app.py:494-496,503-510`.
- §3.3 — insert — ambiguity — reindex of a non-`EXCLUDED` event → `ERR_INVALID_STATE`; hard-exclusion refusal also `ERR_INVALID_STATE` — `app.py:541-545`.
- §3.4 — insert — ambiguity — new commitments carry `consumed_quantity`/`expired_quantity` initialized to 0 — `app.py:986-987`.
- §3.4 — insert — ambiguity — active-commitment selection: `ACTIVE`, window covers the logical clock, earliest-created on tie — `helpers.py:262-276`.
- §3.4 — insert — ambiguity — settlement eligibility is `window_end_utc <= now`; un-elapsed commitments are left untouched by close — `app.py:324`.
- §3.6 — insert — ambiguity — supplied usage-record `team_id` must resolve to a same-account team or `ERR_NOT_FOUND` — `app.py:1141-1144`.
- §3.6 — revise — mismatch — tag value provenance: `required_tag_key == "team_id"` → the record's `team_id`; any other key → the caller's `X-User-ID`; all policies must pass; any failing BLOCK policy rejects — `app.py:1147-1169`.
- §3.6 — insert — ambiguity — disputes may be opened on records with null `team_id`; `raised_by_team_id` must resolve (else `ERR_NOT_FOUND`); accept on a non-OPEN period → `ERR_PERIOD_CLOSED`; acceptance does not recompute `tag_compliant` — `app.py:1231-1235,1266-1274`.
- §3.7 — insert — ambiguity — series `team_id` is required and must resolve to a same-account team — `app.py:724-727`.
- §3.7 — insert — ambiguity — each snapshot syncs the OPEN period's `CUSTOM_METRIC` accumulator by the billable delta; quota is 0 with no PlanTierConfig; snapshot machinery acts on the latest incident — `app.py:777-791,793-801`.
- §3.7 — revise — mismatch — verification requires two consecutive snapshots **at or below** the threshold (PRD said "below"); the below-count resets on any snapshot ≥ threshold; whitespace-only `remediation_note` → `ERR_INVALID_REQUEST`; recurrence keeps original `opened_at_cardinality`/`threshold_used`; quarantine/restore move the estimate out of/into the accumulator — `app.py:803-821,893-908,911-928`.
- §3.8 — insert — ambiguity — no monitor cap applies when no PlanTierConfig exists for the plan — `app.py:1370-1377`.
- §3.9 — revise — mismatch — early close (and closing a non-OPEN period) is `ERR_INVALID_STATE`; also pins INFRA_HOST accumulator application at close, line fields (`committed_quantity`/`overage_quantity`/rates snapshotted at close, `amount_cents = 0` until issue), and line ordering by accumulator creation — `app.py:239-244,268-316`.
- §3.9 — insert — ambiguity — settle from a wrong period status or non-terminal invoice → `ERR_INVALID_STATE`; chargeback uses split-before-rate with commitment rates, no unit conversion for log meters, zero fallback without a config; `by_team` entries carry `team_id`/`team_name`/`total_cents` sorted by team name — `app.py:351-355,1567-1598`, `helpers.py:319-334`.
