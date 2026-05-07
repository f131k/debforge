# debforge

`debforge` rebuilds installed Debian-format binary packages from their exact
source versions in a Debian 12.0 container. The host only needs Docker and
[`uv`](https://docs.astral.sh/uv/); Python packages are installed into the
project-local `.venv`.

## Setup and build

```sh
uv sync --extra dev
dpkg-query -W -f='${Package}\t${Version}\n' > packages.tsv
uv run debforge build --packages-file packages.tsv --rebuild-image
```

Rebuilt packages and `build-manifest.json` are written to `./artifacts`.
Source resolution and build dependencies use an isolated APT configuration;
the host APT configuration is never read. Packages produced by the same source
are grouped so that source is built only once.

Debian 12.0 is fixed as the builder base. Use `debforge.bookworm.yaml` for
Bookworm main, updates, and security repositories. Override `source_repositories`
when the input list comes from another repository.

The signing stage is mandatory and uses `debsigs` to embed an `origin`
signature into every rebuilt `.deb`. Signing runs in a separate container, so
untrusted package build scripts never receive the key. The signer verifies each
signature with `debsig-verify` before an artifact is copied to the output.

Provide an exported OpenPGP private key and its passphrase as Docker-style
secret files:

```text
/run/secrets/debforge-gpg-private-key
/run/secrets/debforge-gpg-passphrase
```

The key file may be binary or ASCII-armored. `gpg_key_id` in the YAML config is
an optional public fingerprint/subkey selector; when empty, the first
signing-capable key from the secret is selected. Secret contents are never
accepted through CLI arguments, YAML, or environment variables. The temporary
GnuPG home and verification policy are destroyed after signing.

Cross compilation is wired through `target_architecture`. For example,
`--architecture arm64` uses APT foreign-architecture build dependencies and
`dpkg-buildpackage --host-arch=arm64`. Package-level cross-build support still
depends on the individual Debian source package. On an ARM Mac, omit this flag
for the requested initial native ARM64 container build.

## Corporate proxy

Corporate APT access uses the same environment variables as `debsec`. Setting
`DEBSEC_PROXY_TOKEN` enables corporate mode; `DEBSEC_PROXY_HOST` is optional and
defaults to `proxy.host`:

```sh
DEBSEC_PROXY_TOKEN='***' uv run --locked debforge \
  -c debforge.bookworm.yaml build --packages-file pkg.tsv
```

The standard Debian main and security repositories are mapped to
`/repo/extras/debian_mirror/debian` and `debian-security` on that host. APT gets
the token through a mode-0600 `auth.conf`; it is not accepted as a CLI/config
value and is removed after the run even with `--keep-artifacts`. It is not
written to the build manifest or logs. Custom repositories already hosted on
`DEBSEC_PROXY_HOST` are left unchanged.
