# CLAUDE.md

## Project overview

Home Assistant custom integration plus local tooling for the
TP-Link Kasa KC100 camera. See [README.md](README.md) for the
high-level description.

## Where to look

- [docs/technical.md](docs/technical.md) — everything known about the
  KC100 LAN protocol: auth, XOR cipher, TLS quirks, module/method
  names, error codes, connection-handling pitfalls. **Consult this
  before touching `client.py` or debugging camera errors.**
- [docs/develop.md](docs/develop.md) — dev workflow (mise, uv, prek).
- `custom_components/kc100/client.py` — the standalone async client. Do
  not modify it without a good reason; HA integration code and the
  webapp both depend on it.

## Git

- Do NOT include Claude attribution in commit messages.
- Always verify `git status` is clean before making changes.

## Verification

- Run `prek run --all-files` — never invoke ruff/pyright/pytest
  manually. Prek manages its own environments for those.
- Run `make hassfest` when changing integration manifest/platform code
  (requires Podman).

## Python

- Always use `uv` to run Python, pytest, and tools (never bare
  `python`/`python3`).
- Always use `uv add`/`uv remove` to manage dependencies.
- Never add new `pyright: ignore` or `type: ignore` comments — needing
  one means the approach is wrong.
- The Python version is >=3.14.2 as required by HA.

## Gotchas that have bitten us

- **Motion-zone coordinates are 0..99, not 0..100.** Sending 100 yields
  `err_code=-40409 "The parameter [x] values error"`.
- **The camera resets concurrent SSL handshakes.** All client requests
  must share one TCP socket — we set `limit_per_host=1` on the aiohttp
  connector.
- **Idle keep-alive sockets get dropped.** The client auto-retries once
  on `ServerDisconnectedError` / `ClientConnectionError`.
- **`err_code=-40602` ("Other error") is transient** — retry once.
- **TLS needs `SECLEVEL=0` and no verification** (1024-bit RSA cert).
- **`get_preview_snapshot` is not supported on KC100** — snapshots come
  from cloud only.
- **Mac-local tools at repo root** (`cli.py`, `webapp.py`) import from
  `custom_components.kc100.*`. Keep that import path working.
