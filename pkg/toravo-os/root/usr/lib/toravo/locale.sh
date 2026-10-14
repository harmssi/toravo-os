# Toravo OS – sourced by the session scripts (14.10.2026: UI language follows the locale).
# toravo_load_locale: like Arch's /etc/profile.d/locale.sh – ~/.config/locale.conf wins over /etc/locale.conf
#   (greetd sessions are no login shells, so nobody else loads it). Exports LANG/LC_* for all Toravo apps.
# toravo_ui: de | en – same rule as toravo.theme.lang(): German only for de_* (and C/POSIX), English otherwise.
toravo_load_locale() {
    local f="${XDG_CONFIG_HOME:-$HOME/.config}/locale.conf"
    [ -r "$f" ] || f=/etc/locale.conf
    if [ -r "$f" ]; then
        unset LANG
        set -a; . "$f"; set +a
    fi
    export LANG="${LANG:-de_DE.UTF-8}"
}
toravo_ui() {
    local v
    for v in "${TORAVO_LANG:-}" "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANG:-}"; do
        [ -n "$v" ] || continue
        case "$v" in de*|DE*|C|C.*|POSIX) echo de ;; *) echo en ;; esac
        return
    done
    echo de
}
