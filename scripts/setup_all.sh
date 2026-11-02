#!/bin/bash
set -euo pipefail

ok() { printf '\033[32m[v]\033[0m %s\n' "$1"; }
busy() { printf '[ ] %s\n' "$1"; }
fail() { printf '\033[31m[x]\033[0m %s\n' "$1" >&2; exit 1; }

find_python() {
  local probe='import sys,tkinter,venv;assert sys.version_info>=(3,10);print(sys.executable)'
  local candidate output
  for candidate in \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3; do
    [ -x "$candidate" ] || continue
    if output=$("$candidate" -c "$probe" 2>/dev/null) && [ -n "$output" ]; then
      printf '%s' "$output"
      return 0
    fi
  done
  return 1
}

install_pkg() {
  local name="$1" url="$2" file
  file="$(mktemp -t amv-cp-bridge).pkg"
  busy "Downloading $name"
  curl -fsSL "$url" -o "$file" || fail "Could not download $name from $url"
  busy "Installing $name (administrator password may be required)"
  sudo installer -pkg "$file" -target / >>"$LOG" 2>&1 || fail "$name installer failed. See $LOG"
  rm -f "$file"
}

main() {
  [ "$(uname -s)" = "Darwin" ] || fail "This script supports macOS only"

  local repo="uno-km/amv-cp-bridge"
  local py_version="${AMV_PY_VERSION:-3.12.10}"
  local root="$HOME/.amv_cp_bridge"
  local app="$root/app"
  local venv="$root/venv"
  LOG="$root/setup.log"

  echo "================================================"
  echo " amv-cp-bridge setup (macOS)"
  echo "================================================"
  mkdir -p "$root"
  : >"$LOG"

  if [ -n "${AMV_WAIT_PID:-}" ]; then
    busy "Waiting for running amv-cp-bridge to exit"
    local waited=0
    while kill -0 "$AMV_WAIT_PID" 2>/dev/null && [ "$waited" -lt 30 ]; do
      sleep 1
      waited=$((waited + 1))
    done
    ok "Previous process closed"
  fi

  local release tag
  release=$(curl -fsSL -H "User-Agent: amv-cp-bridge-setup" "https://api.github.com/repos/$repo/releases/latest") \
    || fail "Could not read the latest release from GitHub"
  tag=$(printf '%s' "$release" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
  [ -n "$tag" ] || fail "Latest release response has no tag_name"
  ok "Latest release: $tag"

  local python
  if ! python=$(find_python); then
    install_pkg "Python $py_version" "https://www.python.org/ftp/python/$py_version/python-$py_version-macos11.pkg"
    python=$(find_python) || fail "Python $py_version was installed but could not be executed"
  fi
  ok "Python: $("$python" --version) ($python)"

  local edge="/Applications/Microsoft Edge.app"
  if [ ! -d "$edge" ]; then
    install_pkg "Microsoft Edge" "https://go.microsoft.com/fwlink/?linkid=2069148"
    [ -d "$edge" ] || fail "Microsoft Edge installation finished but $edge was not found"
  fi
  ok "Microsoft Edge: $edge"

  busy "Downloading source $tag"
  local extract="$root/source.tmp"
  rm -rf "$extract"
  mkdir -p "$extract"
  curl -fsSL "https://github.com/$repo/archive/refs/tags/$tag.tar.gz" | tar -xz -C "$extract" --strip-components=1 \
    || fail "Could not download source $tag"
  rm -rf "$app"
  mv "$extract" "$app"
  ok "Source: $app"
  ok "Browser extension folder: $app/extension"

  if [ ! -x "$venv/bin/python" ]; then
    busy "Creating virtual environment"
    "$python" -m venv "$venv" >>"$LOG" 2>&1 || fail "Could not create virtual environment. See $LOG"
  fi
  ok "Virtual environment: $venv"

  busy "Installing Python packages"
  "$venv/bin/python" -m pip install --upgrade --disable-pip-version-check --quiet pip setuptools wheel >>"$LOG" 2>&1 \
    || fail "pip upgrade failed. See $LOG"
  "$venv/bin/python" -m pip install --upgrade --disable-pip-version-check --quiet -r "$app/requirements.txt" >>"$LOG" 2>&1 \
    || fail "Dependency installation failed. See $LOG"
  ok "Python packages"

  "$venv/bin/python" -m pip install --upgrade --force-reinstall --no-deps --disable-pip-version-check --quiet "$app" >>"$LOG" 2>&1 \
    || fail "amv-cp-bridge installation failed. See $LOG"
  local installed
  installed=$("$venv/bin/python" -I -c 'import amv_cp_bridge; print(amv_cp_bridge.__version__)') \
    || fail "Could not import amv-cp-bridge. See $LOG"
  [ "v$installed" = "$tag" ] || fail "Installed package version $installed does not match release $tag"
  ok "amv-cp-bridge package: $installed"

  "$venv/bin/python" -I -c 'from amv_cp_bridge.engine import CopilotEngine; from amv_cp_bridge.telemetry_db import telemetry_db; CopilotEngine()' >>"$LOG" 2>&1 \
    || fail "Configuration initialization failed. See $LOG"
  ok "Configuration: $root"

  local launcher="$root/start.sh"
  cat >"$launcher" <<EOF
#!/bin/bash
exec "$venv/bin/python" -m amv_cp_bridge.cli "\$@"
EOF
  chmod +x "$launcher"
  ok "Launcher: $launcher"

  if [ -z "${AMV_NO_INTEGRATION:-}" ]; then
    local shortcut="$HOME/Desktop/amv-cp-bridge.command"
    cat >"$shortcut" <<EOF
#!/bin/bash
exec "$launcher"
EOF
    chmod +x "$shortcut"
    ok "Desktop shortcut: $shortcut"
  fi

  echo "================================================"
  ok "Setup complete: amv-cp-bridge $tag"
  echo "================================================"
  nohup "$launcher" >/dev/null 2>&1 &
  ok "Application started"
}

main "$@"
