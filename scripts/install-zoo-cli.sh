#!/usr/bin/env bash
set -Eeuox pipefail

self="$(basename "$0")"
usage() {
  cat <<-EOUSAGE
		usage: $self [zoo-version] [install-dir]

		Installs the Zoo CLI release binary for this Linux runner.
		If zoo-version is empty, installs the latest release.
	EOUSAGE
}

if [ "$#" -gt 2 ]; then
  usage >&2
  exit 1
fi

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

if [ -z "$requested_version" ]; then
  release="$(
    curl -fsSI --connect-timeout 20 --max-time 120 --retry 3 --retry-delay 2 \
      "https://github.com/KittyCAD/cli/releases/latest" |
      tr -d '\r' |
      sed -n 's|^[Ll]ocation: .*/tag/\([^/?#[:space:]]*\).*|\1|p' |
      head -n 1
  )"
else
  release="$requested_version"
  if [[ "$release" != v* ]]; then
    release="v$release"
  fi
fi
if [ -z "$release" ] || [ "$release" = 'null' ]; then
  echo "error: failed to resolve Zoo CLI release" >&2
  exit 1
fi

asset="zoo-${arch}-${os}"
base_url="https://dl.zoo.dev/releases/cli/${release}"
mkdir -p "$install_dir"

echo "Installing Zoo CLI ${release} (${asset})"
expected_sha="$(
  curl -fsSL --connect-timeout 20 --max-time 120 --retry 3 --retry-delay 2 \
    "${base_url}/${asset}.sha256" |
    cut -d ' ' -f 1
)"
if [ -z "$expected_sha" ]; then
  echo "error: failed to resolve SHA256 for ${asset} in ${release}" >&2
  exit 1
fi

tmp="$(mktemp "${install_dir}/.zoo.XXXXXXXXXX")"
trap 'rm -f "$tmp"' EXIT

curl -fsSL --connect-timeout 20 --max-time 300 --retry 3 --retry-delay 2 \
  "${base_url}/${asset}" \
  -o "$tmp"
echo "${expected_sha}  ${tmp}" | sha256sum -c -
chmod a+x "$tmp"
mv -f "$tmp" "${install_dir}/zoo"
trap - EXIT

"${install_dir}/zoo" version
