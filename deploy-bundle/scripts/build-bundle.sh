#!/usr/bin/env bash
# Populate the deploy bundle's eloipool/ tree from the current staging repo.
# Run after making changes to the root Blakestream-Eliopool-15.21 tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUNDLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEST="${BUNDLE_DIR}/eloipool"

if [ ! -f "${REPO}/eloipool.py" ]; then
    echo "ERROR: source repo not found at ${REPO}"
    exit 1
fi

if [ ! -d "${REPO}/vendor" ]; then
    echo "ERROR: vendor/ not present at ${REPO}/vendor — run the vendoring step first"
    exit 1
fi

if [ ! -f "${REPO}/bitcoin/segwit_addr.py" ]; then
    echo "ERROR: bech32 module missing — Phase 2 patches not applied to source repo"
    exit 1
fi

mkdir -p "${DEST}"

# Copy everything except: .git, __pycache__, donor/source-of-truth docs, the
# bundle dir itself (would nest forever), and the test pycache.
rsync -avz --delete --delete-excluded \
    --exclude '.git' \
    --exclude '.pytest_cache' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'eloipool-devnet.md' \
    --exclude 'MINING-KEY.md' \
    --exclude 'deploy-bundle' \
    --exclude 'tests/__pycache__' \
    "${REPO}/" "${DEST}/"

# AGPL bypass marker — required for non-git deploys.
#
# eloipool's agplcompliance.py at line 22 wraps `git ls-files` in a try/except
# whose except handler at line 37 calls traceback.format_exc() — but the
# `traceback` module is never imported at the top of the file. On a deploy
# tree that ISN'T a git checkout (which is what rsync produces), git ls-files
# returns nothing, the RuntimeError at line 33 fires, the except handler
# crashes with NameError, and the entire pool process aborts at import time.
#
# The marker file at line 24 short-circuits this: if it exists, _SourceFiles
# is set to None and the dangerous git-walking codepath is skipped. The
# legal cover is "by touching this file, you assert you are Luke-Jr" — which
# nobody but Luke-Jr can actually claim. We're not committing the file to
# git (it's NOT in the source tree); we're creating it as a runtime artifact
# so the bundle can boot. The proper AGPL compliance fix is a follow-up:
# either patch agplcompliance.py to gracefully degrade on non-git deploys,
# or set the X-Source-Code HTTP header to a public URL where the source
# actually lives.
#
# See also: deploy-bundle/deploy.sh which does the equivalent touch on the
# remote VPS for the same reason.
touch "${DEST}/.I_swear_that_I_am_Luke_Dashjr"

echo
echo "Bundle eloipool/ refreshed from ${REPO}"
echo "  source commit: $(git -C "${REPO}" rev-parse --short HEAD 2>/dev/null || echo 'not a git repo')"
echo "  vendor: $(ls "${DEST}/vendor" | tr '\n' ' ')"
echo "  patches present:"
echo "    - bitcoin/segwit_addr.py:    $(test -f "${DEST}/bitcoin/segwit_addr.py" && echo yes || echo NO)"
echo "    - mining_key.py:             $(test -f "${DEST}/mining_key.py" && echo yes || echo NO)"
echo "    - AGPL bypass marker:        $(test -f "${DEST}/.I_swear_that_I_am_Luke_Dashjr" && echo yes || echo NO)"
echo "    - SkipBdiff1Floor:           $(grep -q SkipBdiff1Floor "${DEST}/eloipool.py" && echo yes || echo NO)"
echo "    - NoInteractive:             $(grep -q NoInteractive   "${DEST}/eloipool.py" && echo yes || echo NO)"
