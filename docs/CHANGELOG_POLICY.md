# Changelog and Release Notes Policy

## Goals
1. Keep release notes deterministic and auditable.
2. Preserve smoke evidence tags used for hardening verification.
3. Make release metadata consumable by humans and automation.

## Tag policy
1. Product releases: `v<major>.<minor>.<patch>`
2. Smoke evidence tags: `smoke/v<YYYYMMDD>-<HHMMSS>-hardening-pass2`

## Notes generation policy
1. Prefer tag-to-tag compare mode.
2. If compare is unavailable, fallback to bounded commit window and mark fallback explicitly.
3. Grouping options:
4. `type` (default)
5. `scope`
6. `author`
7. Optional PR links may be included when commit messages contain PR references.

## Asset policy
1. Asset uploads use local file paths provided by operator.
2. Upload result must include:
3. `uploaded_assets[]`
4. `failed_assets[]`
5. Optional provenance manifest should include `sha256`, size, and filename per validated asset.

## Smoke evidence retention
1. Smoke release/tags/assets are retained by default for auditability.
2. Smoke release notes must start with `SMOKE-EVIDENCE`.
