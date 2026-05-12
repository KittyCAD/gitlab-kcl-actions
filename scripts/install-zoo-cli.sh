#!/usr/bin/env bash
set -euo pipefail

requested_version="${1:-}"
install_dir="${2:-/usr/local/bin}"

case "$(uname -s)" in
  Linux)
    os="unknown-linux-musl"
    ;;
  *)
    echo "error: this installer currently supports Linux runners only" >&2
    exit 1
    ;;
esac

case "$(uname -m)" in
  x86_64 | amd64)
    arch="x86_64"
    ;;
  aarch64 | arm64)
    arch="aarch64"
    ;;
  *)
    echo "error: unsupported architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

if [[ -z "$requested_version" ]]; then
  release="$(curl -fsSL "https://api.github.com/repos/KittyCAD/cli/releases" | jq -r '.[0].name')"
else
  release="$requested_version"
  if [[ "$release" != v* ]]; then
    release="v$release"
  fi
fi

asset="zoo-${arch}-${os}"
base_url="https://github.com/KittyCAD/cli/releases/download/${release}"
mkdir -p "$install_dir"

echo "Installing Zoo CLI ${release} (${asset})"
expected_sha="$(curl -fsSL "${base_url}/${asset}.sha256" | cut -d ' ' -f 1)"
curl -fsSL "${base_url}/${asset}" -o "${install_dir}/zoo"
echo "${expected_sha}  ${install_dir}/zoo" | sha256sum -c -
chmod a+x "${install_dir}/zoo"

"${install_dir}/zoo" version
