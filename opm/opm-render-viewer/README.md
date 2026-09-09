# opm_render_summary.py

A small utility script that parses the JSON output of `opm render` (File-Based
Catalog format) and prints a concise, human-readable summary of the packages,
channels, and operator versions contained in an OLM catalog index — without
having to manually dig through the raw `olm.package` / `olm.channel` /
`olm.bundle` objects.

It is particularly useful when working in **disconnected / air-gapped
OpenShift environments**, to quickly verify what an index image actually
contains after a mirroring operation (e.g. with `oc-mirror`), and to spot
issues in the channel's upgrade graph (broken `replaces` chains, missing
versions, etc.).

## Requirements

- Python 3.7+
- No third-party dependencies (standard library only)
- The [`opm`](https://github.com/operator-framework/operator-registry) CLI,
  to generate the input this script consumes

## Input format

`opm render` outputs the catalog content as **JSON Lines** (one JSON object
per line) by default, but the script also accepts a single JSON array.
Supported object schemas:

- `olm.package` — package name and default channel
- `olm.channel` — channel name, package, and its entries (bundle references,
  `replaces`, `skipRange`)
- `olm.bundle` — bundle name, package, and properties (used to extract the
  version)

## Usage

### Piped directly from `opm render`

```bash
opm render registry.example.com/redhat/redhat-operator-index:v4.16 | python3 opm_render_summary.py
```

### From a previously saved file

```bash
opm render registry.example.com/redhat/redhat-operator-index:v4.16 > catalog.json
python3 opm_render_summary.py catalog.json
```

### Filter on a single package

```bash
python3 opm_render_summary.py catalog.json --package my-operator
```

### JSON output (for scripting / further processing)

```bash
python3 opm_render_summary.py catalog.json --json
```

## Example output

Text mode (default):

```
=== Package: my-operator ===
  Default channel: stable
  - Channel: stable (default)
      my-operator.v1.0.0 (v1.0.0)
      my-operator.v1.1.0 (v1.1.0)
      my-operator.v1.2.0 (v1.2.0)  <- head
```

The `<- head` marker identifies the bundle that is not referenced by any
other entry's `replaces` field in that channel — i.e. the latest version
reachable via the upgrade graph. If this doesn't match the version you
expect to be the latest, it usually means the `replaces`/`skipRange` chain
is broken (a common symptom when only partially mirroring a channel), or
that the expected bundle was never included in the mirrored index in the
first place.

JSON mode:

```json
{
  "my-operator": {
    "defaultChannel": "stable",
    "channels": {
      "stable": {
        "head": "my-operator.v1.2.0",
        "versions": [
          {
            "name": "my-operator.v1.0.0",
            "version": "1.0.0",
            "replaces": null,
            "skipRange": null
          },
          {
            "name": "my-operator.v1.1.0",
            "version": "1.1.0",
            "replaces": "my-operator.v1.0.0",
            "skipRange": null
          },
          {
            "name": "my-operator.v1.2.0",
            "version": "1.2.0",
            "replaces": "my-operator.v1.1.0",
            "skipRange": null
          }
        ]
      }
    }
  }
}
```

## Options

| Flag | Description |
|---|---|
| `file` (positional) | Path to a JSON/JSONL file produced by `opm render`. Defaults to stdin. |
| `--package NAME` | Only display the given package. |
| `--json` | Output structured JSON instead of the formatted text summary. |

## Limitations

- Version extraction falls back to parsing the bundle name (`operator.vX.Y.Z`)
  when no `olm.package` property is present. Bundles that don't follow this
  naming convention and lack the property may show `v?` as their version.
- The "head" detection assumes a single linear `replaces` chain per channel.
  If a channel's graph is a DAG with multiple heads, all of them will be
  listed but only one will be labeled as head.
