# Kasa KC100 LAN Integration for Home Assistant

This [integration](https://www.home-assistant.io/getting-started/concepts-terminology/#integrations) connects your [Kasa KC100](https://www.tp-link.com/us/home-networking/cloud-camera/kc100/v1/) Spot Camera to your [Home Assistant](https://www.home-assistant.io) installation.

The integration provides local control of the KC100, but not video streaming. For streaming, [I recommend using gortc](./docs/technical.md#Streaming-with-go2rtc).

## Installation

### HACS

1. Install [HACS](https://hacs.xyz), then either:
   1. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jaysoffian&repository=ha-kc100&category=integration)

   Or:

   1. Open HACS → Integrations
   2. Open triple-dot menu ( ⠇) → Custom repositories
   3. Add this repository's URL (`https://github.com/jaysoffian/ha-kc100`), category "Integration"
2. Install this integration and restart Home Assistant

### Manual

Copy `custom_components/kc100` into your Home Assistant `custom_components` directory and restart.

## Configuration

1. Settings → Devices & Services → Add Integration → TP-Link Kasa KC100
2. Enter the hostname (or IP address) of your camera and the Kasa username/password you used when you configured the camera with the Kasa app.

## Status

Control power, motion detection, motion sensitivity, night vision, power frequency, resolution, sound detection, sound sensitivity, status LED, and video quality. Diagnostic sensors provide cloud status, night vision mode, resolution, and video quality.

This repo also provides a CLI and web app that may be used outside of HA. The web app provides a GUI for setting motion detection zones. To use these you must have `git` and [`uv`](https://docs.astral.sh/uv/#installation) installed first, then:

```bash
git clone https://github.com/jaysoffian/ha-kc100
cd ha-kc100
export KASA_USERNAME="you@example.com"
export KASA_PASSWORD="your-kasa-password"
./cli.py --help
./webapp.py
```

Tips:
- Before running the web app, you may wish to copy `webapp.toml.example` to `webapp.toml` and then add your cameras.
- For setting your username/password, consider installing [`mise`](https://mise.jdx.dev) which you can also use to install `uv` and `fnox`.


## Documentation

- [docs/technical.md](docs/technical.md): reverse engineered information about the
  KC100 LAN protocol.
- [docs/develop.md](docs/develop.md): development workflow.

## LICENSE

See [LICENSE](LICENSE)
