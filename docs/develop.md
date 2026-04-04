# Development

## Setup

Strictly speaking, you only need `uv` and `prek` in your `PATH`. But to make life easier, we use `mise` to manage our development tools and environment across repos.

1. [Install `mise`](https://mise.jdx.dev/getting-started.html#installing-mise-cli) and [integrate it into your shell](https://mise.jdx.dev/getting-started.html#activate-mise).
2. Clone this repo then prepare your clone for development as follows:

    ```bash
    git clone https://github.com/jaysoffian/ha-kc100
    cd ha-kc100
    mise trust             # trust this repo's mise.toml
    mise install           # install prek and uv
    mise x -- uv sync      # setup .venv
    mise x -- prek install # make prek this repo's pre-commit hook
    ```

## Verification

1. Run `prek` before committing. This runs all linters and tests.
2. Run Home Assistant's `hassfest` manifest validator:

    ```bash
    make hassfest
    ```

## Dependencies

- Add: `uv add <package>`
- Remove: `uv remove <package>`

## Type checking

Two type checkers run: `ty` (Astral) and `pyright`. If you hit a type error, fix the underlying design. **Don't** add `# type: ignore` or `# pyright: ignore`. Those comments are disallowed in this repo.

## Running the tools

Add your Kasa username/password to `mise.local.toml`:

```toml
[env]
KASA_USERNAME = "you@example.com"
KASA_PASSWORD = "yourpassword"
```

Alternately, consider using [`fnox`](https://fnox.jdx.dev) for your `KASA_PASSWORD`.

### CLI

```bash
./cli.py <camera-host> dump
./cli.py <camera-host> get led
./cli.py <camera-host> set led on
```

### Web App

```bash
./webapp.py --port 8000
```

Then open `http://127.0.0.1:8000/`. Cameras are read from `webapp.toml` (see `webapp.toml.example`), or pass `?host=<host>` in the URL.
