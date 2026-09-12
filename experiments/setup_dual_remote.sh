#!/usr/bin/env bash
# Make `git push` reach BOTH of this project's remotes.
#
# The repo lives on two independent hosts:
#
#   github.com/brunopostle/homemaker-layout   -- what agent containers clone
#   hub.postle.net:bruno/homemaker-layout.git -- the owner's own server
#
# They drifted apart in September 2026: the cold-start runner pushed results to
# `hub` for a week while an agent polled `github` and reported, truthfully from
# where it stood, that nothing had arrived. Neither side was broken; they were
# different hosts wearing the same name `origin`. A push has to go to both or
# the two records of an experiment diverge again.
#
# The mechanism is git's own: a remote may carry several `pushurl` entries, and
# `git push origin` then pushes to every one. No hook, no wrapper -- so a plain
# `git push`, this script's runner, and anything else that pushes all get the
# fan-out for free.
#
# NOTE the sharp edge this script exists to handle: as soon as ONE pushurl is
# set, the fetch URL stops being a push target. Adding `hub` by hand with a
# single `set-url --add --push` therefore does not add a second remote, it
# silently REPLACES github as the only one. Both must always be listed.
#
# `.git/config` is not tracked, so this has to be re-run per clone. It is
# idempotent: it rewrites the pushurl list from scratch every time.
#
# Usage:
#   experiments/setup_dual_remote.sh          # configure, skipping unreachable
#   experiments/setup_dual_remote.sh --force  # configure even if unreachable
#   experiments/setup_dual_remote.sh --check  # report only, change nothing

set -uo pipefail

GITHUB_URL="https://github.com/brunopostle/homemaker-layout"
HUB_URL="hub.postle.net:bruno/homemaker-layout.git"
URLS=("$GITHUB_URL" "$HUB_URL")

FORCE=0
CHECK=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --check) CHECK=1 ;;
        -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.." || exit 1

echo "current push targets for origin:"
git remote get-url --push --all origin | sed 's/^/  /'

if [ "$CHECK" = 1 ]; then
    for url in "${URLS[@]}"; do
        if git ls-remote --exit-code "$url" HEAD >/dev/null 2>&1; then
            echo "  reachable:   $url"
        else
            echo "  UNREACHABLE: $url"
        fi
    done
    exit 0
fi

# Which of the two can this machine actually talk to? A container with no ssh
# binary can never reach `hub`, and configuring it there would turn every push
# into a half-failure that masks the half that worked. Check before writing.
keep=()
for url in "${URLS[@]}"; do
    if [ "$FORCE" = 1 ] || git ls-remote --exit-code "$url" HEAD >/dev/null 2>&1; then
        keep+=("$url")
    else
        echo "skipping unreachable remote: $url" >&2
        echo "  (re-run with --force if you want it configured anyway)" >&2
    fi
done

if [ "${#keep[@]}" -eq 0 ]; then
    echo "no reachable remote; leaving origin as it is" >&2
    exit 1
fi

git config --unset-all remote.origin.pushurl 2>/dev/null
for url in "${keep[@]}"; do
    git remote set-url --add --push origin "$url"
done

echo "origin now pushes to:"
git remote get-url --push --all origin | sed 's/^/  /'

if [ "${#keep[@]}" -lt "${#URLS[@]}" ]; then
    echo
    echo "WARNING: only ${#keep[@]} of ${#URLS[@]} remotes configured on this machine."
    echo "Pushes from here will NOT reach the others. Run this script on a machine"
    echo "that can see them, or push there by hand."
fi
