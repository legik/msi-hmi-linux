# bash completion for hmictl (installed to /usr/share/bash-completion/completions/hmictl).
# Layout, theme, setting and effect names come from "hmictl _complete", which needs no service
# or sudo.

_hmictl() {
    local cur words cword opts=""
    if declare -F _get_comp_words_by_ref >/dev/null; then
        _get_comp_words_by_ref -n : cur words cword        # keep layout:gaming as one word
    else
        cur=${COMP_WORDS[COMP_CWORD]}; words=("${COMP_WORDS[@]}"); cword=$COMP_CWORD
    fi
    local cmd=${words[1]}
    if [ "$cword" -eq 1 ]; then
        opts=$(hmictl _complete commands 2>/dev/null | cut -d: -f1)
    else
        case $cmd in
            layout|customize) [ "$cword" -eq 2 ] && opts=$(hmictl _complete layouts 2>/dev/null) ;;
            theme)            [ "$cword" -eq 2 ] && opts="next prev $(hmictl _complete themes 2>/dev/null)" ;;
            hwmon)            [ "$cword" -eq 2 ] && opts="list multi" ;;
            brightness)       [ "$cword" -eq 2 ] && opts="0 25 50 75 100" ;;
            light)            [ "$cword" -eq 2 ] && opts=$(hmictl _complete lights 2>/dev/null | cut -d: -f1) ;;
            get|unset)        [ "$cword" -eq 2 ] && opts=$(hmictl _complete settings 2>/dev/null) ;;
            set)
                if [ "$cword" -eq 2 ]; then
                    opts=$(hmictl _complete settings 2>/dev/null)
                elif [ "$cword" -eq 3 ]; then
                    opts=$(hmictl _complete "values:${words[2]}" 2>/dev/null)
                fi ;;
            picture)
                if [ "${words[2]}" = builtin ]; then
                    [ "$cword" -eq 3 ] && opts="0 1 2 3 4 5"
                else
                    compopt -o filenames 2>/dev/null
                    COMPREPLY=($(compgen -W "fill fit stretch rotate builtin" -- "$cur") $(compgen -f -- "$cur"))
                    return
                fi ;;
            check)
                compopt -o filenames 2>/dev/null
                COMPREPLY=($(compgen -f -- "$cur"))
                return ;;
            preview|preview-themes)
                compopt -o filenames 2>/dev/null
                if [ "$cword" -eq 2 ]; then
                    COMPREPLY=($(compgen -f -- "$cur"))
                elif [ "$cword" -eq 3 ]; then
                    COMPREPLY=($(compgen -W "stats multi $(hmictl _complete layouts 2>/dev/null)" -- "$cur") $(compgen -f -- "$cur"))
                fi
                return ;;
        esac
    fi
    COMPREPLY=($(compgen -W "$opts" -- "$cur"))
    declare -F __ltrim_colon_completions >/dev/null && __ltrim_colon_completions "$cur"
}

complete -F _hmictl hmictl
