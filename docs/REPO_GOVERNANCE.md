# Repository Governance

## Branch and merge policy

- Default branch: `main`
- Merge path: pull request only
- History policy: linear history required
- Force pushes: disabled on `main`
- Merge strategy: squash merge preferred for feature branches

## Required checks

Minimum required status checks for `main`:

- `ci`
- `lint`
- `tests`

Recommended additional required check once stabilized:

- `codeql`

## Review policy

- At least one approving review is required before merge.
- Self-approval does not satisfy review requirements.
- PRs must be up to date with `main` before merge.

## Release ownership

- Smoke evidence releases: repository maintainers
- Versioned product releases (`v*`): repository owner or delegated release maintainers
- Release note conventions and smoke tag policy: `docs/CHANGELOG_POLICY.md`

## Security automation baseline

- Dependency update automation: `.github/dependabot.yml`
- Static analysis: `.github/workflows/codeql.yml`
- Dependency audit workflow: `.github/workflows/security-audit.yml`
- Disclosure policy: `SECURITY.md` and `docs/SECURITY.md`
