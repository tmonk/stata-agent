# CHANGELOG

<!-- version list -->

## v0.1.1 (2026-05-16)

### Bug Fixes

- Add allow_zero_version=true to prevent accidental v1.0.0 bumps
  ([`3a856eb`](https://github.com/tmonk/stata-agent/commit/3a856eb33a5bedf6ac197cb615adf6720191a49f))

- Fix Windows unlink, skip symlink tests
  ([`219f904`](https://github.com/tmonk/stata-agent/commit/219f9040bb62edad3e10f37383af412d19c0e93a))

- Mark semantic-release versioning tests as optional
  ([`210ca77`](https://github.com/tmonk/stata-agent/commit/210ca77b3dac38109fc8068c6ae06c9edf336ae3))

- Publish.yml checkout ref from workflow_dispatch input
  ([`3ecbf88`](https://github.com/tmonk/stata-agent/commit/3ecbf88ba90e23267a03430b4f7f14d33c55cd8d))

- Re-enable publish workflow triggers (versioning is now fixed)
  ([`4ddf755`](https://github.com/tmonk/stata-agent/commit/4ddf755490983721157f175c5e14d9d77a170315))

### Build System

- **deps**: Add pytest-cov to dev dependencies
  ([`ab28cb0`](https://github.com/tmonk/stata-agent/commit/ab28cb053a2f6fa734a042359aae5e32a85b76db))

### Continuous Integration

- Cache .venv directory with actions/cache
  ([`869cb76`](https://github.com/tmonk/stata-agent/commit/869cb76b0f5b45c0624024e998eb43be7ff2516b))

- Mark symlink tests as not required on Win as we have Windows fallback
  ([`4cdb317`](https://github.com/tmonk/stata-agent/commit/4cdb317191da6b50edc4c82737f5cd80ec529a23))

- Remove benchmarks job and decouple slow tests
  ([`cc2527f`](https://github.com/tmonk/stata-agent/commit/cc2527f1a79f96dd825f0f5d79a75c6846a4b7c0))

- Run only fast tests in CI, remove slow and benchmark jobs
  ([`9e02534`](https://github.com/tmonk/stata-agent/commit/9e02534c836f10da13e2cb3aaa6b6b80e9d2884a))

- Speed up dependency install
  ([`4b154b8`](https://github.com/tmonk/stata-agent/commit/4b154b8e4d48435b4b2a756f75af09b2607ca61b))

- Trigger release on successful Build & Test workflow
  ([`21cc42a`](https://github.com/tmonk/stata-agent/commit/21cc42ac8e9f6416fc53173211069b826199a940))

- **build-test**: Consolidate fast and slow test jobs into single test job
  ([`034f6e6`](https://github.com/tmonk/stata-agent/commit/034f6e6f55a63791001b847d8ac6963402f4a6d8))


## v0.1.0 (2026-05-15)

### Features

- Initial release of stata-agent: CLI-native Stata integration for AI agents.
- Run Stata code, inspect data, retrieve results, export graphs, and test do-files.
- Daemon mode for persistent Stata sessions.
- Mock backend for testing without a Stata license.
- Statest: Stata-native test runner with JUnit output.
- Plugin system with skills for AI agent integration (Claude Code, Codex, Gemini).
- Cross-platform installer scripts (macOS, Linux, Windows).
