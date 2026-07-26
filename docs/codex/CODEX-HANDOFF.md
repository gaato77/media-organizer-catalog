# Codex handoff — Stable Catalog Phase A1

## Single source of truth

Read and execute only:

`docs/codex/PHASE-A1-MASTER-PLAN.md`

That file is self-contained and is the authoritative plan for this Codex task.
It supersedes conflicting instructions in earlier prompts, cross-repository plans, and handoffs.

## Repository and branch

- Repository: `gaato77/media-organizer-catalog`
- Working branch: `codex/stable-channel-backfill`
- Pull-request base: `main`

Never commit directly to `main` and never merge the pull request.

## Current scope

Execute Phase A1 only:

- implement strict component and stable-channel contracts;
- implement verified component-pointer generation;
- implement stable-channel assembly;
- prepare the base, 2016–2025, and current-year publication workflows;
- add offline/default and opt-in/network distribution tests;
- document the distribution lifecycle;
- run complete local verification;
- open a green pull request.

Do not publish real assets during A1.
The new historical workflow cannot be dispatched until it exists on the default branch. Real publication is Phase A2, after a human reviews and merges the A1 pull request.

## Execution method

Use the subagent-driven-development workflow described by the installed Superpowers skills:

- isolated worktree;
- persistent ledger naming `docs/codex/PHASE-A1-MASTER-PLAN.md`;
- fresh implementer per task;
- separate spec-compliance and code-quality review per task;
- focused commit after each approved task;
- whole-branch final review;
- no confirmation prompts between tasks.

Stop only for a genuine new blocker not resolved by the master plan. Include exact evidence in any blocker report.
