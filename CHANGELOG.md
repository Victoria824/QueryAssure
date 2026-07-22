# Changelog

All notable changes to QueryAssure are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [0.3.1] - 2026-07-22

### Added

- free GitHub Pages playground at `victoria824.github.io/QueryAssure`
- automated release workflow producing wheel, source distribution, checksums, and GHCR images
- `queryassure --version` and API/package version consistency coverage
- issue forms for bugs, proposals, and community benchmark submissions
- pull-request template, sitemap, robots policy, citation metadata, and security policy

### Changed

- removed build-time Google Fonts downloads so static and offline builds are reproducible
- updated documentation and repository metadata around the QueryAssure SQL Agent identity
- made GitHub Pages paths, canonical metadata, social images, and favicon subpath-safe

### Verified

- deterministic SQL Agent and evaluation suite
- Python tests and Ruff checks
- static Next.js export and interactive hosted playground
- Docker Compose API, web, schema endpoint, and release-container builds in GitHub Actions

## [0.3.0] - 2026-07-22

### Added

- QueryAssure name and public product identity
- reference SQL Agent and inspectable chat/evaluation playground
- framework-independent Python and HTTP agent adapters
- PostgreSQL and dbt metadata ingestion
- correctness-first benchmark generation and reusable GitHub Action
- deterministic Northstar Retail data and quality contracts

## [0.2.0] - 2026-07-22

### Added

- first public evaluation contracts, validators, benchmark tools, and Docker workflow

[0.3.1]: https://github.com/Victoria824/QueryAssure/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Victoria824/QueryAssure/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Victoria824/QueryAssure/releases/tag/v0.2.0
