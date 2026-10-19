#!/bin/sh
# Install hmid from this source folder.
#   sudo ./install.sh              install or update
#   sudo ./install.sh --uninstall  remove (keeps /etc/hmid.json)
#
# This script never installs or upgrades system packages: on Arch/Manjaro installing
# single packages can cause a partial upgrade. It only checks the dependencies and
# tells you what is missing. Arch / Manjaro users can also build packaging/arch/PKGBUILD.
#
# hmid is pure Python, so it is copied to /opt/hmid and run by the system python3.
# No venv and no pip: it keeps working when the distribution upgrades Python.
set -e
PREFIX=/opt/hmid
BIN=/usr/local/bin
UNIT=/etc/systemd/system/hmid.service
HELPER_UNIT=/etc/systemd/system/hmid-helper.service
UDEV_RULE=/usr/lib/udev/rules.d/70-hmid.rules
SYSUSERS=/usr/lib/sysusers.d/hmid.conf
HOOK=/usr/lib/systemd/system-sleep/hmid
ZSH_COMP=/usr/share/zsh/site-functions/_hmictl
BASH_COMP=/usr/share/bash-completion/completions/hmictl
cd "$(dirname "$0")"

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

if [ "$1" = "--uninstall" ]; then
    systemctl disable --now hmid.service hmid-helper.service 2>/dev/null || true
    rm -rf "$PREFIX" "$BIN/hmid" "$BIN/hmictl" "$BIN/hmid-helper" "$UNIT" "$HELPER_UNIT" "$HOOK" \
           "$ZSH_COMP" "$BASH_COMP" "$UDEV_RULE" "$SYSUSERS"
    udevadm control --reload-rules 2>/dev/null || true
    systemctl daemon-reload
    echo "removed (settings kept in /etc/hmid.json)"
    exit 0
fi

# ---- checks (nothing is changed before they pass) ---------------------------------
if ! python3 -c "import math, json, socketserver" 2>/dev/null; then
    echo "python3 does not start correctly:"
    python3 -c "import math" || true
    echo
    echo "This usually means a partial system upgrade. Update the whole system first:"
    echo "    Arch / Manjaro:  sudo pacman -Syu"
    exit 1
fi
python3 -c "import sys; sys.exit(sys.version_info < (3, 10))" || { echo "Python 3.10 or newer is needed"; exit 1; }

missing=""
python3 -c "import usb.core" 2>/dev/null || missing="$missing pyusb"
python3 -c "import PIL.Image" 2>/dev/null || missing="$missing Pillow"
if [ -n "$missing" ]; then
    echo "missing Python modules:$missing"
    echo "install them with your package manager, then run this script again:"
    echo "    Arch / Manjaro:  sudo pacman -Syu python-pyusb python-pillow ttf-dejavu"
    echo "    Debian / Ubuntu: sudo apt install python3-usb python3-pil fonts-dejavu-core"
    echo "    Fedora:          sudo dnf install python3-pyusb python3-pillow dejavu-sans-fonts"
    exit 1
fi
fc-list 2>/dev/null | grep -qi dejavu || echo "note: DejaVu fonts not found - text will use another system font"

# ---- install ------------------------------------------------------------------------
systemctl stop hmid.service hmid-helper.service 2>/dev/null || true
rm -rf "$PREFIX.new"
install -d "$PREFIX.new/lib"
cp -r src/hmid "$PREFIX.new/lib/"
find "$PREFIX.new" -name __pycache__ -prune -exec rm -rf {} +
chown -R root:root "$PREFIX.new"
chmod -R u=rwX,go=rX "$PREFIX.new"          # root-only writable: built-in layouts may run commands
rm -rf "$PREFIX"
mv "$PREFIX.new" "$PREFIX"

install -d "$BIN"
for cmd in hmid:cli:main_daemon hmictl:cli:main_ctl hmid-helper:helper:main; do
    name=${cmd%%:*} rest=${cmd#*:}
    mod=${rest%%:*} fn=${rest#*:}
    rm -f "$BIN/$name"            # may be a dangling link from an earlier (venv) install
    cat > "$BIN/$name" <<EOF
#!/bin/sh
exec /usr/bin/python3 -c 'import sys; sys.path.insert(0, "$PREFIX/lib"); from hmid.$mod import $fn; sys.exit($fn())' "\$@"
EOF
    chmod 755 "$BIN/$name"
done

# ---- its own user ---------------------------------------------------------------------
# hmid runs as the user "hmid" with access to only its two USB devices (udev rule); the few
# things that need root are done by hmid-helper. /etc/hmid.json stays root's: hmid reads it.
install -Dm644 packaging/sysusers/hmid.conf "$SYSUSERS"
systemd-sysusers "$SYSUSERS"
install -Dm644 packaging/udev/70-hmid.rules "$UDEV_RULE"
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=usb --attr-match=idVendor=1462 || true
udevadm trigger --action=add --subsystem-match=hidraw || true
if [ -e /etc/hmid.json ]; then
    chown root:hmid /etc/hmid.json && chmod 640 /etc/hmid.json     # may hold a proxy password
fi
rm -f /run/hmid.sock                                                # the old control socket

# ---- layouts --------------------------------------------------------------------------
# Built-in layouts ship inside hmid and update with it. /etc/hmid/layouts is only for your
# own files; one with the same name as a built-in layout replaces it. Earlier versions of
# this script copied the examples there - unchanged copies are removed now so the updated
# built-in versions are used; copies you edited are kept.
install -d -m 755 /etc/hmid/layouts
# layouts you protected with chmod 600 (API keys): readable by hmid too, still root's
find /etc/hmid/layouts -name '*.json' -user root -perm 600 -exec chgrp hmid {} + -exec chmod 640 {} + 2>/dev/null || true
SHIPPED="
18e12f2334ab156f0a45738e2f30fb403614939e377cabddac93d06d594ffd97
6604664effca4d01804e4fa5e1dc64e33fd6b396d95b2675870e06b848e4c564
f9f64d7f0226495d868e240a0a978dca61ce5f3f3635b17370f706032fae8033
ca995f52e433f561d4d06a052e8604f8f5d268cd04c90214b4cfa349b6c8c8ab
c4441052ca493cbebb40422c01d5e7c2ca2c64b685af92343180f395b12c8989
d514ec1823a666a5df9f02856776d7bdb52b0008336561292fd9b4c519987388
eef54382c7dcc53cdc7e31509d96175645b65af4a943e9e8a149aeaffad78293
703e5acfd9471c660dec5118753d10652a6695f7f7cc458db566e722a4041147
dc6dd6350d3dab39587a7af0dc948c1226a1dbc57db921b00624e27b354b83c2
77c645fe8fdeea0e9975e173934694d8110faeb2bed262f8b8a85da3c25507ee
a01dc21827b08eaa2e3ee7dd5f32da685c1e63c26ac59aa8d83b03b13bfb4cc1
b476e0c0d36caca100339d48a40872181cadb4be71fd7b251f53fbe3b181edd0
"
for f in src/hmid/data/layouts/*.json; do
    mine="/etc/hmid/layouts/$(basename "$f")"
    [ -e "$mine" ] || continue
    h=$(sha256sum "$mine" | cut -c1-64)
    if cmp -s "$f" "$mine" || echo "$SHIPPED" | grep -qx "$h"; then
        rm -f "$mine"
        echo "layouts: removed the old copy of $(basename "$f") - the built-in (updated) version is used now"
    else
        echo "layouts: kept your edited $(basename "$f") - it replaces the built-in one (delete it to use the built-in)"
    fi
done

# tab completion for hmictl (zsh and bash); a new terminal picks it up
install -Dm644 packaging/completions/_hmictl "$ZSH_COMP"
install -Dm644 packaging/completions/hmictl.bash "$BASH_COMP"

sed "s|/usr/bin/hmid|$BIN/hmid|" packaging/systemd/hmid.service > "$UNIT"
sed "s|/usr/bin/hmid-helper|$BIN/hmid-helper|" packaging/systemd/hmid-helper.service > "$HELPER_UNIT"
sed "s|/usr/bin/hmictl|$BIN/hmictl|" packaging/systemd/hmid-sleep > "$HOOK"
chmod 755 "$HOOK"

# earlier script-based version (0.1) lived in /opt/hmi
if [ -d /opt/hmi ]; then
    rm -rf /opt/hmi
    echo "removed the old /opt/hmi install (settings in /etc/hmid.json are kept)"
fi

systemctl daemon-reload
systemctl enable hmid-helper.service hmid.service
systemctl restart hmid-helper.service
systemctl restart hmid.service
sleep 4
systemctl --no-pager status hmid.service | head -8
echo
systemctl --no-pager status hmid-helper.service | head -4
echo
"$BIN/hmictl" status || true
