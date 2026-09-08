# Contributing Guide

This guide defines the working agreement for the IFT 401 Team 2 repository.

## Before You Begin

- Confirm Git and Python are installed.
- Clone the repository rather than downloading a ZIP file.
- Configure Git with your own name and email.
- Never share or commit passwords, tokens, API keys, or private course materials.

## Branch Workflow

Do not do project work directly on `main`.

1. Switch to `main`.
2. Pull the latest changes.
3. Create a branch for one card or closely related task.
4. Make and test the change.
5. Commit with a clear message.
6. Push the branch.
7. Open a pull request into `main`.
8. Request review from at least one teammate.
9. Address review comments and merge after approval.

### Branch Names

Use lowercase words separated by hyphens:

- `feature/user-registration`
- `fix/portfolio-validation`
- `docs/database-diagram`
- `test/trading-models`
- `chore/update-dependencies`

### Commit Messages

Use a short type and an action-focused summary:

- `feat: add user registration form`
- `fix: prevent trades with insufficient funds`
- `docs: clarify local setup steps`
- `test: cover portfolio balance calculation`
- `chore: update Django dependency`

Recommended types are `feat`, `fix`, `docs`, `test`, `refactor`, and `chore`.

## Pull Requests

A pull request should:

- Address one Trello card or one coherent change.
- Explain what changed and why.
- Link the relevant Trello card or GitHub issue when available.
- Include screenshots for visible interface changes.
- Describe how the change was tested.
- Avoid unrelated formatting or cleanup changes.
- Receive review from at least one teammate before merging.

The author should not approve their own pull request. Small documentation corrections may use a lighter review process if the team agrees.

## Coding Expectations

- Follow existing Django and project conventions.
- Keep functions, templates, and commits focused.
- Use descriptive names.
- Validate user input.
- Add or update tests for behavior changes.
- Do not disable security protections merely to make a feature work.
- Discuss new frameworks, packages, services, or major architectural changes before adding them.

## Handling Conflicts

Do not force-push shared branches or overwrite another teammate's work. If a merge conflict is unclear, stop and review it with the affected teammate.

## Definition of Done

A task is done when:

- Acceptance criteria are satisfied.
- The change runs locally.
- Relevant tests pass.
- Documentation is updated where needed.
- No secrets or private data are included.
- A teammate has reviewed the pull request.
- The pull request is merged and its Trello card is updated.
