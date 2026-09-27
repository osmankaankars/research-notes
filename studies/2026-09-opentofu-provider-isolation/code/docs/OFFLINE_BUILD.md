# Optional offline build inputs

The standard reproduction uses the online build in the study README. The original
input preparation and offline consumer are retained in `tools/`. They require
a complete, verified input bundle prepared on a networked Linux machine first.
They do not contain third-party sources or a Podman installation.

```sh
python3 tools/prepare_offline_inputs.py --help
python3 tools/build.py --help
```

Never lower the pinned upstream compiler requirement or disable checksum checks
to use an incomplete bundle. A successful local component check is not a full
OpenTofu build. The recorded end-to-end run used the online path.
