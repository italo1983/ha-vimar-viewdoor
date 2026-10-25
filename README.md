# Vimar View Door — Home Assistant (experimental)

Custom integration for local camera images from a Vimar K42955 using View Door.
This is an unofficial prototype, not a Vimar product. Only one physical K42955,
firmware V401R001B030, has been tested. Other models/firmwares are unverified.

## Version 0.4.1 scope

- UI configuration with private LAN IP, device UID, 32-byte stream key and
  64-character `out-auth-code` acquired separately.
- Two camera entities: physical input **1** (door station) and **3** (auxiliary camera).
- On-demand JPEG images (roughly 8–12 seconds per request, including camera warm-up) through Home Assistant's authenticated camera API.
- On-demand H.264 video through Home Assistant stream/HLS, using loopback-only RTSP relays.
- A camera connection starts only when a local reader connects and closes 5 seconds after the last local reader leaves. Home Assistant Core 2026.10.3 retains the HLS reader for around 30 seconds, so a normal viewer close releases the intercom after roughly 35 seconds; do not enable camera stream preloading or an always-live dashboard if you want viewing only on request.
- Both physical inputs were tested concurrently with distinct recordings.
- Stalled producers reconnect only while readers remain. No continuous recording.
- English/Italian configuration forms; pinned MIT-licensed `quii-helper==0.2.0` dependency.

**This release does not provide automatic MyVimar login/key renewal, bell events, audio or native WebRTC. Gate commands require active video on the tested unit. Output 1 (pedestrian) and output 2 (driveway) were physically confirmed in separate supervised tests, with the owner confirming release of the intercom after closure. The owner has also confirmed that both automatic Home Assistant buttons work on this unit.** Opening a camera starts on-demand HLS video; dashboard still previews remain snapshots. An authenticated Home Assistant installation and both camera previews have been tested; this remains experimental pending longer-term and lifecycle testing.

The local protocol and physical input selector have been tested on hardware.
Installed and configured on Home Assistant OS 18.3 / Core 2026.10.3. Both camera entities displayed the correct images in the authenticated HA UI. Version 0.2 HLS playback was verified on both entities with advancing playback time (352×288 H.264). Two simultaneous RTSP captures on the physical unit produced approximately 20 fps each; idle producer shutdown was verified. Restart-to-discovery and config flow passed. Unload/cancellation edge cases still need full Home Assistant integration tests.

## Installation and setup

1. Copy `custom_components/vimar_viewdoor` to `/config/custom_components/`.
2. Restart Home Assistant. Go to Settings → Devices & services → Add integration
   → **Vimar View Door (experimental)**.
3. Enter the LAN IP, UID, stream key and out-auth-code. The stream key/auth code
   are **not** your MyVimar password or door PIN. They are currently acquired
   in a separate, assisted bootstrap process; this is not yet a self-service setup.
4. Open either camera entity to request an image. FFmpeg must be available in
   the Home Assistant runtime (normally present in HA OS).

The form validates syntax, not reachability. The first image request checks
actual connectivity. Close View Door live viewing if the device rejects a session.
Expired keys require removing/re-adding the integration with freshly acquired keys
in this initial version. Removing it does not alter the intercom.

The repository is laid out for a future HACS custom repository. HACS publication,
hassfest validation and a tagged release are still pending.

## Security and privacy

- The integration does not expose its own network listener or a public video URL.
- Video transport uses the device's AES-256/SHA256 protocol over the local network.
- Credentials reside in HA config entries, **not encrypted by this integration**.
  Protect Home Assistant, its backups and file access accordingly.
- Images and short warm-up clips are created in private temporary directories and deleted after each capture.
- Exceptions from the library are not logged, because they may contain sensitive values.
- The repository contains no real UID, credentials, images, APK, native libraries,
  extracted vendor certificates or bundled vendor private keys.
- No cloud connections are made. Opening commands run only after an explicit button press; setup, startup, options and updates never actuate gates.
- Upstream private adapter attributes are confined to `protocol.py`; the dependency
  is pinned, and protocol tests must pass before any version upgrade.

## Development

Python 3.13+:

```sh
python -m venv .venv
. .venv/bin/activate
pip install 'quii-helper==0.2.0' pytest ruff
ruff check .
python -m compileall -q custom_components
pytest -q
```

These tests cover input selection, encryption, instance isolation and validation.
They also cover lazy relay creation, concurrent setup, last-viewer teardown, reopening, unload and cancellation. They do not substitute for full Home Assistant lifecycle integration tests.

## Gate buttons

**Apri cancelletto** selects output 1; **Apri cancello carrabile** selects output 2
on the verified K42955. Configurable mapping and optional separate opening
password are available under Configure. Other installations must verify mapping.

Each explicit press serializes access to the device, pauses existing video relay
producers, opens input 1, waits up to eight seconds for three assembled H.264
access units starting from a keyframe, and only then sends one local CGI opening
command. It keeps reading for three seconds and closes the owned session in a
finally block. Active viewers resume afterward and may continue to occupy the
intercom until they are closed. The local RTSP URLs remain stable.

If video readiness fails, no opening command is sent. Simultaneous button requests
are rejected, not queued. Both outputs share a ten-second actuator cooldown.
Opening is never automatically retried, including after a timeout or unknown
outcome. Cancelling a request before readiness suppresses the impulse; after
sending, cancellation cannot reverse physical movement. Cancellation and unload
wait for the worker's cleanup before releasing device ownership.

The adapter first blocks new receives and keepalives, waits for the bounded
in-flight receive, sends native video teardown (type 7, empty body, SHA256/AES),
and closes the socket. No audio conversation, global hang-up or device reset is
invented. There is no physical open/closed sensor: acceptance is not proof of
movement. This remains experimental. HACS default-store submission is not provided.

## Validation

38 local tests cover protocol selection/encryption, shutdown ordering, concurrent
close, readiness failures, single-attempt commands, cancellation, viewer pause /
resume and unload serialization. pytest, ruff check and compileall passed.
The component-level video-plus-CGI sequence was physically verified separately
for each output, followed by the owner's confirmation that the intercom was free.
The owner subsequently confirmed both automatic HA buttons work. No actuation
is performed by CI or installation. Full HA lifecycle tests and long-term
reliability remain outstanding.

## Attribution

Uses [quii-helper](https://github.com/xaer981/quii-helper), MIT; see NOTICE.
No vendor APK, native library, certificate or real credential is redistributed.


## Automations, Android Auto and voice

Both buttons can be used with the standard `button.press` action in scripts and
automations. The same video readiness and ordered cleanup workflow applies.
See [automation examples and a geofencing blueprint](docs/AUTOMATIONS.md).
Examples are templates only: installation does not create or enable automations.

Android Auto supports Home Assistant buttons through the Companion app. Google
Assistant supports buttons/scripts as scenes, but voice access requires its own
Home Assistant connection; it is not configured by this integration. No remote
access, Google account authorization or automatic gate opening is enabled here.
