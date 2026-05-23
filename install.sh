#!/usr/bin/env bash
# SixPack install script
# Run from the project root: bash install.sh
# Uninstall:                 bash install.sh --uninstall
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="sixpack"
PKG_NAME="sixpack-abs"          # matches pyproject.toml [project] name
BIN_DIR="$HOME/.local/bin"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/sixpack.desktop"

# ── colour helpers ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}▶${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
die()   { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ── system dependency detection ────────────────────────────────────────────────
install_system_deps() {
    if command -v apt-get &>/dev/null; then
        info "Checking system packages (apt)…"

        # ── libmpv: package name changed from libmpv1 → libmpv2 in Ubuntu 23.04+ ──
        # Note: we capture apt-cache/ldconfig output before grepping throughout.
        # grep -q exits on first match → SIGPIPE to the producer → pipefail
        # sees the non-zero exit and treats the condition as false. Capturing
        # into a variable sidesteps this.
        _ldconfig=$(ldconfig -p 2>/dev/null || true)
        if echo "$_ldconfig" | grep -q 'libmpv'; then
            MPV_PKG=""   # already installed
        else
            _pol_mpv2=$(apt-cache policy libmpv2 2>/dev/null || true)
            _pol_mpv1=$(apt-cache policy libmpv1 2>/dev/null || true)
            if echo "$_pol_mpv2" | grep -q 'Candidate: [^(]'; then
                MPV_PKG="libmpv2"
            elif echo "$_pol_mpv1" | grep -q 'Candidate: [^(]'; then
                MPV_PKG="libmpv1"
            else
                die "Cannot find libmpv1 or libmpv2 in apt. Install libmpv manually and retry."
            fi
        fi

        # ── Qt6 XCB platform plugin runtime deps ─────────────────────────────────
        # PyQt6 bundles Qt6 but the XCB plugin still links against these system libs.
        # libxcb-util name changed: libxcb-util0 (older) → libxcb-util1 (Ubuntu 22.04+)
        _pol_xcbutil=$(apt-cache policy libxcb-util1 2>/dev/null || true)
        if echo "$_pol_xcbutil" | grep -q 'Candidate: [^(]'; then
            XCBUTIL="libxcb-util1"
        else
            XCBUTIL="libxcb-util0"
        fi
        XCB_PKGS=(
            libxcb-cursor0
            libxcb-icccm4
            libxcb-image0
            libxcb-keysyms1
            libxcb-randr0
            libxcb-render0
            libxcb-render-util0
            libxcb-shape0
            libxcb-shm0
            libxcb-sync1
            libxcb-xfixes0
            libxcb-xkb1
            "$XCBUTIL"
            libx11-xcb1
            libxkbcommon0
            libxkbcommon-x11-0
            libegl1
            libgl1
        )

        # Collect only the packages that aren't already installed
        MISSING=()
        [[ -n "$MPV_PKG" ]] && MISSING+=("$MPV_PKG")
        for pkg in "${XCB_PKGS[@]}"; do
            dpkg -s "$pkg" &>/dev/null || MISSING+=("$pkg")
        done

        if [[ ${#MISSING[@]} -gt 0 ]]; then
            info "Installing missing packages: ${MISSING[*]}"
            sudo apt-get install -y "${MISSING[@]}"
        else
            info "All system packages already installed."
        fi

    elif command -v dnf &>/dev/null; then
        info "Checking system packages (dnf)…"
        rpm -q mpv-libs &>/dev/null || sudo dnf install -y mpv-libs

    elif command -v pacman &>/dev/null; then
        info "Checking system packages (pacman)…"
        pacman -Q mpv &>/dev/null || sudo pacman -S --noconfirm mpv

    else
        warn "Unknown package manager — ensure libmpv is installed before continuing."
    fi
}

# ── uv ─────────────────────────────────────────────────────────────────────────
ensure_uv() {
    if command -v uv &>/dev/null; then
        return
    fi
    info "uv not found — installing…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # The installer adds ~/.local/bin to PATH in shell init files,
    # but that won't take effect until the next shell session.
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv &>/dev/null || die "uv installation failed. Add $HOME/.local/bin to your PATH and retry."
}

# ── app installation ───────────────────────────────────────────────────────────
install_app() {
    info "Installing SixPack…"
    uv tool install --reinstall "$SCRIPT_DIR"
    info "Installed: $(uv tool list | grep "$APP_NAME" || echo "$APP_NAME")"
}

# ── icon ───────────────────────────────────────────────────────────────────────
install_icon() {
    mkdir -p "$ICON_DIR"
    cp "$SCRIPT_DIR/assets/sixpack.svg" "$ICON_DIR/sixpack.svg"
    # Notify icon cache if gtk-update-icon-cache is available
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    fi
}

# ── .desktop file ──────────────────────────────────────────────────────────────
install_desktop_file() {
    mkdir -p "$DESKTOP_DIR"
    # Use full path in Exec so it works even if ~/.local/bin isn't in the
    # desktop environment's PATH (common on some DEs / display managers).
    EXEC_PATH="$BIN_DIR/$APP_NAME"

    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Name=SixPack
GenericName=Audiobook Player
Comment=10-foot Audiobookshelf client
Exec=$EXEC_PATH
Icon=sixpack
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Player;
Keywords=audiobook;audiobookshelf;player;
StartupNotify=false
EOF

    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi
    info "Desktop entry created: $DESKTOP_FILE"
}

# ── PATH check ─────────────────────────────────────────────────────────────────
check_path() {
    if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
        warn "$BIN_DIR is not in your PATH."
        warn "Add the following to your ~/.bashrc or ~/.profile, then open a new terminal:"
        warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
}

# ── uninstall ──────────────────────────────────────────────────────────────────
uninstall() {
    info "Uninstalling SixPack…"
    uv tool uninstall "$PKG_NAME" 2>/dev/null && info "Package removed." || warn "Package not found (already uninstalled?)."
    rm -f "$DESKTOP_FILE" && info "Desktop entry removed."
    rm -f "$ICON_DIR/sixpack.svg" && info "Icon removed."
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi
    info "Uninstall complete."
}

# ── main ───────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    uninstall
    exit 0
fi

info "SixPack installer"
echo
install_system_deps
ensure_uv
install_app
install_icon
install_desktop_file
check_path
echo
info "Done! You can now:"
info "  • Launch from the terminal:        sixpack"
info "  • Find 'SixPack' in your app menu (you may need to log out and back in)"
info ""
info "To uninstall: bash install.sh --uninstall"
