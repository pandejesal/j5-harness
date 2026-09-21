---
name: _template
description: TEMPLATE — Copy this file, rename, and customize for new subagents
model: opencode/mimo-v2.5-free
tools:
  - read
  - write
  - edit
  - bash
  - glob
  - grep
  - search
  - symbols
  - imports
  - batch_symbols
  - ast_grep
  - test_runner
  - test_impact
  - build_check
  - lint
  - syntax_check
  - quality_budget
  - pre_check_batch
  - secretscan
  - osv_scan
  - pkg_audit
  - schema_drift
  - diff
  - diff_summary
  - repo_map
  - knowledge_recall
  - knowledge_add
  - knowledge_query
  - doc_extract
  - doc_scan
  - web_fetch
  - web_search
  - google_ai_search_plus
  - crawlberg_scrape
  - crawlberg_crawl
  - crawlberg_map
  - html_to_markdown_fetch_url
  - html_to_markdown_convert
  - html_to_markdown_extract
  - xberg_extract
  - xberg_detect
  - xberg_formats
  - tspack_parse
  - tspack_process
  - tspack_info
  - morph_edit
  - suggest_patch
  - swarm_apply_patch
  - extract_code_blocks
  - summarize_work
  - phase_complete
  - update_task_status
  - declare_scope
  - declare_council_criteria
  - record_directive_override
  - record_implementation_review
  - record_issue_reproduction
  - record_issue_publication
  - record_recurrence_sweep
  - complete_pr_workflow
  - prepare_pr_workflow_checkout
  - prepare_pr_feedback_scope
  - rebind_pr_feedback_head
  - run_pr_feedback_stage_a
  - write_pr_review_artifact
  - write_pr_review_trigger_eval
  - write_drift_evidence
  - write_hallucination_evidence
  - write_mutation_evidence
  - write_retro
  - write_final_council_evidence
  - write_architecture_supervisor_evidence
  - submit_council_verdicts
  - submit_phase_council_verdicts
  - convene_general_council
  - consensus_mine
  - curator_analyze
  - evidence_check
  - req_coverage
  - run_phase_review
  - check_gate_status
  - get_qa_gate_profile
  - set_qa_gates
  - get_approved_plan
  - approve_plan_critic
  - save_plan
  - spec_write
  - lint_spec
  - swarm_command
  - swarm_memory_recall
  - swarm_memory_propose
  - swarm_memory_outcome
  - skill
  - skill_apply
  - skill_generate
  - skill_improve
  - skill_inspect
  - skill_list
  - skill_regenerate
  - skill_retire
  - external_skill_discover
  - external_skill_inspect
  - external_skill_list
  - external_skill_promote
  - external_skill_reject
  - external_skill_revoke
  - task
  - supervisor_launch
  - dispatch_lanes
  - dispatch_lanes_async
  - collect_lane_results
  - parse_lane_candidates
  - retrieve_lane_output
  - retrieve_summary
  - context_status
  - set_reasoning_effort
  - zen_usage
  - zen_usage_clear
  - actionlint_scan
  - co_change_analyzer
  - complexity_hotspots
  - git_blame
  - gitingest
  - placeholder_scan
  - todo_extract
  - todowrite
  - question
  - jules_create
  - jules_status
  - jules_message
  - jules_approve
  - jules_delete
  - jules_list
  - jules_list_sources
  - jules_get_source
  - jules_activity
  - generate_mutants
  - mutation_test
  - lean_turbo_plan_lanes
  - lean_turbo_acquire_locks
  - lean_turbo_run_phase
  - lean_turbo_review
  - lean_turbo_status
  - lean_turbo_runner_status
  - epic_decide_phase
  - epic_plan_waves
  - epic_record_divergence
  - repair_gate_evidence
  - repair_knowledge_receipt_ledger
  - sbom_generate
---

# <Domain> Subagent Template

**Instructions**: Copy this file to `<name>.md`, replace all `<PLACEHOLDERS>`, and customize.

## Domain Configuration

From `domains/domains.config.json` under the `<domain>` domain:

- **Primary Models**: `<model-1>`, `<model-2>`
- **Fallback Models**: `<fallback-1>`, `<fallback-2>`
- **Skills**: `<skill-1>`, `<skill-2>`, `<skill-3>`
- **Tools**: `<tool-1>`, `<tool-2>`, `<tool-3>`
- **Data Sources**: `<source-1>`, `<source-2>`
- **Constraints**: `<constraint-1>`, `<constraint-2>`

## Fallback Ladders

| Role | Ladder |
|------|--------|
| research | `<model-a>` → `<model-b>` |
| coder | `<model-c>` → `<model-d>` |
| planner | `<model-e>` → `<model-f>` |
| bulk | `<model-g>` → `<model-h>` |

## Operating Principles

1. **<Principle 1>**: <Description>
2. **<Principle 2>**: <Description>
3. **<Principle 3>**: <Description>
4. **<Principle 4>**: <Description>
5. **Token Efficiency**: Use skills and MCP servers for domain knowledge.

## Delegation Patterns

- **Simple tasks** (<criteria>): `opencode` with `<model>`
- **Complex <work-type>`: `hermes` with `<model>` for multi-model consensus
- **<Parallel work>`: `kilocode` parallel agents (`-p N`) for <use-case>
- **<Specialized work>`: `prime-agent` via WSL for <reason>
- **<Visual/IDE work>`: `antigravity` bridge for <use-case>

## Skill Usage

Check `tools/skills/ecosystem/` for `<domain>` skills:
- `<domain>/<skill-1>` — <description>
- `<domain>/<skill-2>` — <description>
- `<domain>/<skill-3>` — <description>

## Verification Gates

Standard framework: trust-but-verify, multi-model cross-check, skill pack, scoreboard.
<Domain-specific additions if any>

---

**Remember**: <Domain-specific motto>