# KC100 LAN Protocol

The camera exposes (at least) two independent HTTPS services:

| Service | Port   | Purpose                                  |
| ------- | ------ | ---------------------------------------- |
| Stream  | 19443  | Live audio + video                       |
| Control | 10443  | JSON-RPC (`/data/LINKIE.json`)           |

Each uses HTTP Basic Auth, but with different encodings. See each authentication section below.

## Streaming

### Endpoint

```
GET https://<camera-host>:19443/https/stream/mixed?video=h264&audio=g711&resolution=hd
```

The URL above returns a long-lived HTTPS response whose body is a raw multiplexed H.264 + G.711 byte stream.

The camera only accepts one stream client at a time. A second concurrent connection gets `HTTP 503`.

### Stream authentication

HTTP Basic auth:

```
Authorization: Basic base64(username + ":" + base64(password))
```

`username` and `password` are your kasasmart.com credentials from the
Kasa mobile app.

### Streaming with go2rtc

The easiest way to stream the KC100 is with [`go2rtc`](https://go2rtc.org) using its [`kasa://` support](https://go2rtc.org/internal/kasa/).


1. URL encode your Kasa username. e.g. `user@example.com` -> `user%40example.com`
2. Base64 encode your Kasa password: e.g. `secret1` -> `c2VjcmV0MQ==`
3. Add the camera to go2rtc's config like so:

   ```yaml
   streams:
     kc100:
       - "kasa://user%40example.com:c2VjcmV0MQ==@kc100:19443/https/stream/mixed?video=h264&audio=g711&resolution=hd"
   ```

## Control (JSON-RPC)

### Transport

- **HTTPS** on TCP port **10443**
- Single endpoint: `POST /data/LINKIE.json`
- Content-Type: `application/x-www-form-urlencoded; charset=utf-8`
- Body is a single form field: `content=<value>` (see [Encoding](#encoding))

### TLS quirks

The camera presents a **1024-bit RSA** certificate signed by an internal TP-Link CA. Modern Python/OpenSSL refuses this by default.

To connect you must:
- Set OpenSSL **`SECLEVEL=0`** on the SSL context
- Disable hostname and chain verification (`verify=False` / `check_hostname=False` / `CERT_NONE`)

See `KC100Client._make_ssl_context()` in [`custom_components/kc100/client.py`](../custom_components/kc100/client.py).

### Connection behavior

The camera **resets new TCP connections** if several SSL handshakes arrive concurrently. We avoid this by limiting aiohttp to **one connection per host** (`TCPConnector(limit_per_host=1)`), which serializes requests onto a single keep-alive socket.

The camera also drops idle keep-alive sockets. The client retries once on `ServerDisconnectedError` / `ClientConnectionError`.

## Authentication

HTTP Basic auth:

```
Authorization: Basic base64(username + ":" + md5_hex_lowercase(password))
```

`username` and `password` are your kasasmart.com credentials from the Kasa mobile app.

A wrong credential returns `HTTP 401`.

## Encoding

Request and response bodies are XOR-encrypted, base64-encoded, then URL-encoded (requests only) or base64 (responses).

### Request body

```
content = urlencode(base64(xor_encrypt(utf8(json_command))))
```

### Response body

```
json_response = utf8_decode(xor_decrypt(base64_decode(raw_body)))
```

### XOR cipher

Self-keying XOR:

```python
key = 0xAB
for i, byte in enumerate(plaintext):
    cipher[i] = byte ^ key
    key = cipher[i]           # next key = previous cipher byte
```

Decryption is symmetric with `key = previous ciphertext byte`.

The initial key `0xAB` and this construction are the same as the classic Kasa smart-plug cipher (`IotSwiftSDK` confirms it).

## Command shape

Every command is a single JSON object:

```json
{
  "<module>": {
    "<method>": { ...args... }
  }
}
```

The response mirrors that structure and includes an `err_code`:

```json
{
  "<module>": {
    "<method>": { ...result..., "err_code": 0 }
  }
}
```

- `err_code == 0` → success
- `err_code != 0` → `err_msg` is usually populated with a short string

### Known error codes

| Code    | Meaning                                  | Handling |
| ------- | ---------------------------------------- | -------- |
| `0`     | OK                                       | —        |
| `-1`    | "module not support" (method unknown)    | fatal for that call |
| `-40409`| "The parameter [x] values error"         | coords out of range, malformed args |
| `-40602`| "Other error" (transient)                | retry once — usually works |

Motion-zone coordinates are 0..99 inclusive.

## Modules and methods

Method and module names extracted from the Kasa iPad app binary:

```
/Applications/Kasa.app/Wrapper/Kasa.app/Frameworks/IotSwiftSDK.framework/IotSwiftSDK
```

Strings matching `smartlife.cam.ipcamera.*` and Swift class names like `Camera{Get,Set}…Request` exposed the vocabulary.

| Module                                  | Status    | Covers                                  |
| --------------------------------------- | --------- | --------------------------------------- |
| `smartlife.cam.ipcamera.switch`         | confirmed | power on/off                            |
| `smartlife.cam.ipcamera.led`            | confirmed | status LED                              |
| `smartlife.cam.ipcamera.motionDetect`   | confirmed | motion detection + zones + sensitivity  |
| `smartlife.cam.ipcamera.soundDetect`    | confirmed | sound detection + sensitivity           |
| `smartlife.cam.ipcamera.videoControl`   | confirmed | resolution, quality, rotation, freq     |
| `smartlife.cam.ipcamera.OSD`            | confirmed | on-screen logo / timestamp              |
| `smartlife.cam.ipcamera.dayNight`       | confirmed | night-vision mode (auto/day/night)      |
| `smartlife.cam.ipcamera.cloud`          | confirmed | cloud connection state (read)           |
| `smartlife.cam.ipcamera.dateTime`       | confirmed | camera time (`get_time`)                |
| `smartlife.cam.ipcamera.videoControl.get_preview_snapshot` | not supported | returns `err_code=-1: module not support` |

The SDK lists many other `smartlife.cam.ipcamera.*` modules (`audio`, `battery`, `camSchedule`, `debug`, `delivery`, `dndSchedule`, `intelligence`, `ptz`, `relay`, `sdCard`, `siren`, `system`, `upgrade`, `upnpc`, `vod`, `wireless`). All return `err_code=-1: module not support` on KC100. They belong to newer KC models.

See `client.py` for the exact method names and argument shapes that are
known to work.

## Motion events

The KC100 pushes motion events to the cloud. It has no LAN event API I was able to discover. It's also not possible to MITM the cloud connections short of hacking the device's firmware due to TLS doing its job:

- Persistent TLS connection to a regional push server (observed: `n-use1-devs.tplinkcloud.com:50443`). The server is selected via the `default_svr` (`n-devs-kipc.tplinkcloud.com`) and `sef_domain` (`n-deventry.tplinkcloud.com`) fields returned by `cloud.get_info`. A separate HTTPS upload path (`use1-cipc.tplinkra.com:443`, `prd-use1-ipcr-*.tplinkra-ipc.com:443`) carries clip and snapshot data.

- The push server's cert chains through `CN=TP-LINK CA P1` to a private TP-Link root `CN=tp-link-CA`. That root ships as `tp-link-root-CA.der` inside the Kasa app (SHA-256 `8B:54:F0:36:4E:84:0F:B0:10:D5:17:32:47:25:F0:D3:02:45:D3:5B:45:F9:BE:4B:6E:50:B8:4F:03:FD:EC:19`). The camera validates the chain. A DNS redirect with a self-signed cert on port 50443 returns TLS alert `48 unknown_ca`.

- Newer KC cameras (KC120/200/310/420) expose `get_detect_event_state` on `motionDetect` and `intelligence`. The Kasa iPad app polls those to surface event state. On KC100 they return `err_code=-1: module not support`.

## TBD

- Two-way audio
