# Capacium organization SkillWeave helper

Durable planning for every repository in the Forgejo `capacium` organization is centralized in the private `capacium/capacium-planning` repository.

- Canonical repository: `https://git.langevc.com/capacium/capacium-planning`
- Local clone: `/Users/andrelange/Documents/repositories/forgejo/capacium/capacium-planning`
- Board: `.skillweave/planning/BOARD.md`
- Execution playbook: `.skillweave/planning/PLAYBOOK.md`
- Ticket schema: `.skillweave/planning/TICKET-SCHEMA.md`

## When SkillWeave starts in this repository

1. Read this repository's root agent instructions and inspect the current branch, worktree, tests, and linked Forgejo issue or pull request.
2. Read the central board and playbook. Reuse the existing central ticket that owns the outcome; create a central ticket only when no ticket exists.
3. Do not create a durable repository-local `.skillweave/planning` tree. Repository-local SkillWeave files are ephemeral execution state and remain ignored.
4. Keep planning fields, status, dependencies, acceptance criteria, evidence, and handoffs in the central ticket. Keep human discussion in the owning Forgejo issue.
5. Before handing work to another agent or operator, record the ticket ID, repository and branch, commits/PRs, tests, remaining work, blockers, and the next binary gate.
6. Let `capacium-ops` mirror Forgejo comments and open/closed state. Bot markers and sync-state files are machine-managed and must not be edited manually.

If the planning repository or synchronizer is temporarily unavailable, do not fork the backlog. Preserve a temporary local handoff note, avoid destructive cleanup, and reconcile it into the central ticket as soon as service returns.

