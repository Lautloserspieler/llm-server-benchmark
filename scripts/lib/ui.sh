#!/usr/bin/env bash
# shellcheck shell=bash
# Gemeinsame Terminal-Oberflaeche und Sprachsystem fuer setup.sh,
# START_BENCHMARK.sh und scripts/docker_common.sh.
#
# Texte stehen in scripts/locales/<lang>.sh und werden ueber ihren Schluessel
# ausgegeben, z. B. `ui_step docker.gpu_check` oder `ui_t setup.mode "$MODE"`
# (Platzhalter im printf-Stil: %s). Die Sprache wird einmal gewaehlt
# (ui_select_language), in .runtime/language gespeichert und als LLMBENCH_LANG
# an Python und Docker weitergereicht.
#
# Bewusst ohne assoziative Arrays: macOS liefert Bash 3.2 aus. Jeder Text
# landet in einer eigenen Variable LLMBENCH_T_<schluessel mit _ statt .>.

LLMBENCH_UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLMBENCH_UI_ROOT="$(cd "$LLMBENCH_UI_DIR/../.." && pwd)"
LLMBENCH_UI_LANG="de"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    _UI_C_CYAN=$'\033[36m'; _UI_C_GREEN=$'\033[32m'; _UI_C_YELLOW=$'\033[33m'
    _UI_C_RED=$'\033[31m'; _UI_C_MAGENTA=$'\033[35m'; _UI_C_DIM=$'\033[90m'
    _UI_C_BOLD=$'\033[1m'; _UI_C_RESET=$'\033[0m'
else
    _UI_C_CYAN=""; _UI_C_GREEN=""; _UI_C_YELLOW=""; _UI_C_RED=""
    _UI_C_MAGENTA=""; _UI_C_DIM=""; _UI_C_BOLD=""; _UI_C_RESET=""
fi

_ui_normalize_lang() {
    local v="${1:-}"
    v="$(printf '%s' "$v" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    v="${v:0:2}"
    case "$v" in de|en) printf '%s' "$v" ;; *) return 1 ;; esac
}

ui_detect_language() {
    local lang
    if lang=$(_ui_normalize_lang "${LLMBENCH_LANG:-}"); then printf '%s' "$lang"; return 0; fi
    if [ -f "$LLMBENCH_UI_ROOT/.runtime/language" ] \
        && lang=$(_ui_normalize_lang "$(cat "$LLMBENCH_UI_ROOT/.runtime/language")"); then
        printf '%s' "$lang"; return 0
    fi
    return 1
}

_ui_load_texts() {
    # Zeilen der Form [schluessel]="Text" einlesen (\" steht fuer ein Anfuehrungszeichen).
    local file="$1" line key value
    local pattern='^[[:space:]]*\[([A-Za-z0-9_.]+)\]="(.*)"[[:space:]]*$'
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ $pattern ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            value="${value//\\\"/\"}"
            printf -v "LLMBENCH_T_${key//./_}" '%s' "$value"
        fi
    done < "$file"
}

ui_set_language() {
    LLMBENCH_UI_LANG="$1"
    # Deutsch ist die Referenz; eine andere Sprache ueberschreibt nur ihre Keys.
    _ui_load_texts "$LLMBENCH_UI_ROOT/scripts/locales/de.sh"
    if [ "$LLMBENCH_UI_LANG" != "de" ]; then
        _ui_load_texts "$LLMBENCH_UI_ROOT/scripts/locales/$LLMBENCH_UI_LANG.sh"
    fi
}

ui_init() {
    local lang
    if lang=$(ui_detect_language); then
        ui_set_language "$lang"
        export LLMBENCH_LANG="$lang"
    else
        ui_set_language de
    fi
}

ui_select_language() {
    local lang answer=""
    if ! lang=$(ui_detect_language); then
        printf '\n  %sSprache / Language%s\n' "$_UI_C_CYAN" "$_UI_C_RESET"
        printf '    1) Deutsch\n    2) English\n'
        if [ -t 0 ]; then read -r -p "  Auswahl / Choice [1]: " answer || true; fi
        case "$answer" in 2*|en*|EN*) lang="en" ;; *) lang="de" ;; esac
        mkdir -p "$LLMBENCH_UI_ROOT/.runtime"
        printf '%s\n' "$lang" > "$LLMBENCH_UI_ROOT/.runtime/language"
    fi
    ui_set_language "$lang"
    export LLMBENCH_LANG="$lang"
}

# Text zu einem Schluessel, Platzhalter %s werden mit den weiteren Argumenten gefuellt.
ui_t() {
    local key="$1"; shift
    local var="LLMBENCH_T_${key//./_}"
    local fmt="${!var-<$key>}"
    # shellcheck disable=SC2059
    printf "$fmt" "$@"
}

# ------------------------------------------------------------------ Ausgabe

_ui_repeat() { local i; for ((i = 0; i < $2; i++)); do printf '%s' "$1"; done; }

ui_header_raw() {
    # Rechts offen: Bash-printf zaehlt bei Umlauten Bytes statt Zeichen, ein
    # rechter Rahmen waere dann verrutscht.
    local title="$1" subtitle="${2:-}" line
    line="$(_ui_repeat '─' 52)"
    printf '\n  %s┌%s%s\n' "$_UI_C_CYAN" "$line" "$_UI_C_RESET"
    printf '  %s│%s  %s%s%s\n' "$_UI_C_CYAN" "$_UI_C_BOLD" "$title" "$_UI_C_RESET" ""
    if [ -n "$subtitle" ]; then
        printf '  %s│%s  %s%s%s\n' "$_UI_C_CYAN" "$_UI_C_RESET$_UI_C_DIM" "$subtitle" "$_UI_C_RESET" ""
    fi
    printf '  %s└%s%s\n' "$_UI_C_CYAN" "$line" "$_UI_C_RESET"
}

ui_section_raw() {
    local title="$1" rest=$((50 - ${#1}))
    [ "$rest" -lt 4 ] && rest=4
    printf '\n  %s── %s %s%s\n' "$_UI_C_CYAN" "$title" "$(_ui_repeat '─' "$rest")" "$_UI_C_RESET"
}

_ui_badge() { printf '  %s%-4s%s %s\n' "$1" "$2" "$_UI_C_RESET" "$3"; }

# Rohtext-Varianten (fuer Pfade, Image-Namen usw.)
ui_step_raw() { _ui_badge "$_UI_C_CYAN" "[+]" "$1"; }
ui_ok_raw() { _ui_badge "$_UI_C_GREEN" "[OK]" "$1"; }
ui_warn_raw() { _ui_badge "$_UI_C_YELLOW" "[!]" "$1" >&2; }
ui_fail_raw() { _ui_badge "$_UI_C_RED" "[X]" "$1" >&2; }
ui_info_raw() { printf '       %s%s%s\n' "$_UI_C_DIM" "$1" "$_UI_C_RESET"; }

# Varianten mit Uebersetzungsschluessel: ui_step <key> [args...]
ui_header() { local k="$1"; shift; ui_header_raw "$(ui_t "$k")" "${1:-}"; }
ui_section() { ui_section_raw "$(ui_t "$@")"; }
ui_step() { ui_step_raw "$(ui_t "$@")"; }
ui_ok() { ui_ok_raw "$(ui_t "$@")"; }
ui_warn() { ui_warn_raw "$(ui_t "$@")"; }
ui_fail() { ui_fail_raw "$(ui_t "$@")"; }
ui_info() { ui_info_raw "$(ui_t "$@")"; }

ui_done() {
    local title="$1"; shift
    printf '\n  %s√ %s%s\n' "$_UI_C_GREEN" "$(ui_t "$title")" "$_UI_C_RESET"
    local key
    for key in "$@"; do printf '    %s\n' "$(ui_t "$key")"; done
    printf '\n'
}

# ------------------------------------------------------------------ Eingabe

# ui_confirm <key> [args...]  -> 0 = ja. Standard ist Nein.
# UI_DEFAULT_YES=1 davor setzen, um Ja zum Standard zu machen.
ui_confirm() {
    local question yes hint answer=""
    question="$(ui_t "$@")"
    yes="$(ui_t ui.yes_key)"
    if [ "${UI_DEFAULT_YES:-0}" = "1" ]; then
        hint="[$(printf '%s' "$yes" | tr '[:lower:]' '[:upper:]')/n]"
    else
        hint="[$yes/N]"
    fi
    if [ ! -t 0 ]; then [ "${UI_DEFAULT_YES:-0}" = "1" ]; return; fi
    read -r -p "  ${_UI_C_MAGENTA}[?]${_UI_C_RESET}  $question $hint " answer || true
    if [ -z "$answer" ]; then [ "${UI_DEFAULT_YES:-0}" = "1" ]; return; fi
    [[ "$answer" =~ ^[[:space:]]*[jJyY] ]]
}

# ui_confirm_install <Name>: fragt vor jeder Installation (Standard Ja).
# LLMBENCH_AUTO_INSTALL=1 beantwortet mit Ja, =0 mit Nein.
ui_confirm_install() {
    case "${LLMBENCH_AUTO_INSTALL:-}" in
        1) ui_step ui.auto_install "$1"; return 0 ;;
        0) return 1 ;;
    esac
    [ -t 0 ] || return 1
    UI_DEFAULT_YES=1 ui_confirm ui.install_question "$1"
}

# ui_choice <frage-key> <default> <option-key>...  -> Ergebnis in UI_CHOICE (1-basiert)
ui_choice() {
    local question="$1" default="$2"; shift 2
    local i=1 key answer=""
    printf '\n  %s%s%s\n' "$_UI_C_BOLD" "$(ui_t "$question")" "$_UI_C_RESET"
    for key in "$@"; do
        if [ "$i" = "$default" ]; then
            printf '   %s> %s) %s%s\n' "$_UI_C_CYAN" "$i" "$(ui_t "$key")" "$_UI_C_RESET"
        else
            printf '     %s) %s\n' "$i" "$(ui_t "$key")"
        fi
        i=$((i + 1))
    done
    UI_CHOICE="$default"
    if [ -t 0 ]; then
        read -r -p "  $(ui_t ui.choice_prompt "$#" "$default") " answer || true
        if [[ "$answer" =~ ^[0-9]+$ ]] && [ "$answer" -ge 1 ] && [ "$answer" -le "$#" ]; then
            UI_CHOICE="$answer"
        fi
    fi
}

# Gemeinsames Startmenue fuer nativen und Docker-Lauf.
# Ergebnis: UI_DURATION, UI_HARDWARE, UI_STRESS (0/1)
ui_benchmark_options() {
    ui_section run.title
    ui_choice run.duration_question 2 run.duration_short run.duration_medium run.duration_long
    case "$UI_CHOICE" in 1) UI_DURATION=short ;; 3) UI_DURATION=long ;; *) UI_DURATION=medium ;; esac
    ui_choice run.hardware_question 3 run.hardware_cpu run.hardware_gpu run.hardware_both
    case "$UI_CHOICE" in 1) UI_HARDWARE=cpu ;; 2) UI_HARDWARE=gpu ;; *) UI_HARDWARE=both ;; esac
    printf '\n'
    UI_STRESS=0
    if ui_confirm run.stress_question; then UI_STRESS=1; fi
    local stress_label
    if [ "$UI_STRESS" = "1" ]; then stress_label="$(ui_t ui.yes)"; else stress_label="$(ui_t ui.no)"; fi
    printf '\n'
    ui_info run.selection "$UI_DURATION" "$UI_HARDWARE" "$stress_label"
}

ui_init
