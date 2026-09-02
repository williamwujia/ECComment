<!--
Sync Impact Report
- Version change: unversioned template -> 1.0.0
- Modified principles: template placeholders -> five project principles
- Added sections: Data, Security, and Operational Constraints; Delivery Workflow
- Removed sections: none
- Follow-up TODOs: none
-->

# ECComment Constitution

## Core Principles

### I. Evidence-Based, Reversible Data Operations

All data imports, updates, deletion, and rollback operations MUST preserve auditability.
Destructive changes require a preview, explicit confirmation, and a recoverable backup or
snapshot. Sales and other derived metrics MUST state their data source, assumptions, and known
limits; estimates MUST never be presented as platform-observed facts.

### II. Security and Data Minimization

Secrets, tokens, and private identifiers MUST be supplied only through protected deployment
configuration and MUST NOT enter source control, user-visible errors, or application logs.
Public entry points MUST authenticate or verify their upstream messages, apply abuse controls,
and store only the data required for their stated purpose. Retention, deletion, and irreversible
anonymization rules MUST be implemented and tested when the feature stores user-linked data.

### III. Testable Contracts Before Implementation

Every new behavior MUST have focused automated coverage, and every external integration MUST
have a documented contract plus deterministic fake-client tests. A defect fix SHOULD add a
regression test. Acceptance criteria must be measurable; a feature is not complete until its
focused tests and the relevant repository regression suite pass.

### IV. Explicit Boundaries and Operational Isolation

Components MUST have one clear responsibility and avoid silently expanding their boundaries.
User-facing Streamlit flows, batch workbook processing, browser collection, and public webhook
services MUST remain isolated unless an approved decision explains the coupling. Production
services MUST be independently observable, restartable, minimally exposed, and verified through
their actual public route after deployment.

### V. Records Are Part of the Change

Code, tests, current status, and user-facing change records are one delivery unit. Changes that
affect product definitions, data contracts, security, compatibility, or architecture MUST add a
decision record explaining the choice and rejected alternatives. `PROJECT_STATUS.md` MUST reflect
current truth, while `CHANGELOG.md` MUST record externally meaningful history.

## Data, Security, and Operational Constraints

- Existing sales estimates use the adopted 5% review-rate assumption unless a newer decision
  explicitly replaces it; the interface must show the assumption and date coverage.
- Production credentials and databases are never overwritten, reset, or published as part of a
  normal code update. Deployment must validate a backup, service health, logs, public route, and
  relevant asset consistency.
- Public services must reject invalid requests safely, bound retries, preserve idempotency, and
  avoid blocking an ingress acknowledgement on slow external work.

## Delivery Workflow

1. Before changes, read `PROJECT_STATUS.md`, the unreleased `CHANGELOG.md`, relevant decisions,
   and the working-tree status.
2. Define or update a Spec Kit specification when behavior, contracts, or scope change; resolve
   material ambiguity before implementation.
3. Implement in small, independently testable increments, maintaining the documented contracts.
4. Before delivery, run focused tests, required regression checks, `git diff --check`, and inspect
   the intended diff and working-tree status.
5. Update current status, changelog, and decisions in the same change; record any remaining
   deployment validation or external dependency as an explicit next step.

## Governance

This constitution supersedes informal project conventions when they conflict. Amendments require
an explicit user or maintainer decision, a rationale recorded in the change, and a semantic
version bump: MAJOR for incompatible principle changes, MINOR for new or materially expanded
principles, and PATCH for clarifications. Every feature review and release review MUST verify
compliance with the relevant principles; exceptions require an explicit decision record and a
recovery or migration plan.

**Version**: 1.0.0 | **Ratified**: 2026-08-30 | **Last Amended**: 2026-08-30
