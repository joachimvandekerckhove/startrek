#!/usr/bin/env bash
set -euo pipefail

STARTREK_REPO="${STARTREK_REPO:-joachimvandekerckhove/startrek}"
STARTREK_VERSION="${STARTREK_VERSION:-v1.1.0}"
STARTREK_INSTALL_DIR="${STARTREK_INSTALL_DIR:-$HOME/bin}"
STARTREK_IMAGE="${STARTREK_IMAGE:-startrek:1.1.0}"
STARTREK_CLONE_DIR="${STARTREK_CLONE_DIR:-$HOME/.local/share/startrek}"

die() {
  echo "startrek install: $*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || die "docker is required"
command -v git >/dev/null 2>&1 || die "git is required"

mkdir -p "$(dirname "$STARTREK_CLONE_DIR")"

if [[ -d "$STARTREK_CLONE_DIR/.git" ]]; then
  git -C "$STARTREK_CLONE_DIR" fetch --depth 1 origin "refs/tags/${STARTREK_VERSION}:refs/tags/${STARTREK_VERSION}" 2>/dev/null || true
  git -C "$STARTREK_CLONE_DIR" checkout -f "$STARTREK_VERSION"
else
  rm -rf "$STARTREK_CLONE_DIR"
  git clone --depth 1 --branch "$STARTREK_VERSION" \
    "https://github.com/${STARTREK_REPO}.git" \
    "$STARTREK_CLONE_DIR"
fi

echo "Building Docker image ${STARTREK_IMAGE} ..."
docker build -t "$STARTREK_IMAGE" "$STARTREK_CLONE_DIR"

mkdir -p "$STARTREK_INSTALL_DIR"
cat >"$STARTREK_INSTALL_DIR/startrek" <<EOF
#!/usr/bin/env bash
set -euo pipefail

IMAGE="\${STARTREK_IMAGE:-${STARTREK_IMAGE}}"

TZ_VALUE="\${TZ:-}"
if [[ -z "\${TZ_VALUE}" && -f /etc/timezone ]]; then
  TZ_VALUE="\$(cat /etc/timezone)"
fi
TZ_VALUE="\${TZ_VALUE:-UTC}"

exec docker run --rm -i \\
  -e "TZ=\${TZ_VALUE}" \\
  "\${IMAGE}" \\
  "\$@"
EOF
chmod +x "$STARTREK_INSTALL_DIR/startrek"

echo
echo "Installed startrek to ${STARTREK_INSTALL_DIR}/startrek"
if ! echo ":$PATH:" | grep -q ":${STARTREK_INSTALL_DIR}:"; then
  echo "Add to PATH:  export PATH=\"${STARTREK_INSTALL_DIR}:\$PATH\""
fi

echo "Verifying ..."
"$STARTREK_INSTALL_DIR/startrek" -V
