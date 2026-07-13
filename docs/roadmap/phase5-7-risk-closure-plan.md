# Phase 5 to 7 Risk Closure Implementation Plan

Goal: close the remaining local/runtime risks except the LLM endpoint transport choice, then finish frontend, infra, CI, and documentation phases.

Architecture: keep backend behavior additive. Use local `.env` only for ignored secret material. Frontend talks to the existing backend routes through `/api` in nginx and `http://localhost:8000` in direct local development.

Verification baseline: `conda run -n ml_env python -m pytest tests -q --tb=short`, `bru run --env Local`, and Docker Compose config parse.

## Tasks

1. Backend runtime hygiene
   - Add tests proving backend imports work without a manually supplied services path.
   - Add tests proving Google inline service-account fields are not required when `GOOGLE_APPLICATION_CREDENTIALS` exists.
   - Implement a safe local credential materialization script that writes ignored JSON from `.env` without printing secrets.

2. Frontend alignment
   - Add static tests for local API fallback, `AbortController` timeout, demo handoff copy, OCR upload, and `textContent` rendering.
   - Implement frontend code in `src/frontend/app.js`, `index.html`, `chat.html`, and `styles.css`.
   - Harden `src/frontend/nginx.conf` and slim `src/frontend/Dockerfile`.

3. Infra and CI
   - Add tests for production backend binding, nginx rate limiting, no tracked env files, env-example alignment, and CD health gate.
   - Implement compose, nginx, CI, and deploy workflow changes.
   - Do not run production deploy.

4. Documentation and verification
   - Update docs with local run, env matrix, dense model warning, OCR limits, and graph data caveats.
   - Run targeted tests, full suite, Bruno CLI, and local HTTP smoke if code changes affect runtime.
