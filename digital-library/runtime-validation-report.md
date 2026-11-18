# Runtime Validation Report

**Generated**: 2026-11-18T18:14:49+05:30
**Target**: digital-library

## Summary

| Step | Status | Exit Code | Details |
|---|---|---:|---|
| Docker Compose startup | PASS | 0 | 10 application/dependency containers started |
| API health/readiness | PASS | 0 | All seven APIs returned healthy and ready |
| Member tests | PASS | 0 | 22 passed |
| Catalog tests | PASS | 0 | 33 passed |
| Lending tests | PASS | 0 | 6 passed after UUID/string assertion correction |
| Availability tests | PASS | 0 | 5 passed |
| Fine tests | PASS | 0 | 5 passed |
| Notification tests | PASS | 0 | 1 passed |
| Reservation tests | PASS | 0 | 2 passed |
| Usage Analytics tests | PASS | 0 | 2 passed |
| Member/Catalog integration | PASS | 0 | Full create, upload, download, and metrics workflow passed |
| Restart persistence verification | PASS | 0 | Saved member, book, copy, and cover verified after restart |
| Offline Terraform tests | PASS | 0 | 5 passed |
| Kubernetes manifest validation | PASS | 0 | 23 resources validated against Kubernetes 1.35.0 |

**Overall**: PASS

## Environment

- Docker: AVAILABLE
- Docker Compose: AVAILABLE, v5.1.1
- Node.js: AVAILABLE, v24.13.1
- Python: Conda `deeplearning` environment
- Java: 21.0.5
- Maven: 3.9.11
- Browser/Playwright: NOT REQUIRED for this API-only validation
- Cloud resources: NOT provisioned

## Test Evidence

- Docker Compose: all seven service APIs and four infrastructure/emulator containers reported healthy or running.
- API probes: ports 8001-8007 all returned `health=ok` and `ready=ready`.
- Integration: full local workflow passed, and the saved records passed verification after API restart.
- Python: 74 service tests passed, zero skipped.
- Usage Analytics: 2 Maven tests passed.
- Terraform: 5 offline mock-provider tests passed.
- Kubernetes: 23 resources passed strict schema validation; no cluster was contacted.

## Issues Found

| Severity | Description | Resolution |
|---|---|---|
| Low | Lending test compared UUID objects with reservation ID strings | Updated the test assertion to compare normalized strings |
| Informational | Conda dependency set reported package conflicts from existing environment packages | Test dependencies ran successfully; no repository dependency manifest was changed |
