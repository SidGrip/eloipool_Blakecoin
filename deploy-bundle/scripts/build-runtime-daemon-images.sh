#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALLER_REPOS="${INSTALLER_REPOS:-${REPO_ROOT}/../Blakestream-Installer/repos}"
NAMESPACE="sidgrip"
PRIMARY_TAG="15.21"
PUSH=0
TAGS=()

usage() {
    cat <<'EOF'
Usage: bash deploy-bundle/scripts/build-runtime-daemon-images.sh [options]

Options:
  --push                    Push built tags to Docker Hub
  --namespace <name>        Docker namespace/user (default: sidgrip)
  --tag <tag>               Primary version tag (default: 15.21)
  --also-tag <tag>          Extra tag to apply; repeatable
  --help                    Show this help

Default extra tags:
  latest
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --push)
            PUSH=1
            shift
            ;;
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --tag)
            PRIMARY_TAG="$2"
            shift 2
            ;;
        --also-tag)
            TAGS+=("$2")
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown option $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [ "${#TAGS[@]}" -eq 0 ]; then
    TAGS=(latest)
fi

say() {
    printf '\033[1;34m==>\033[0m %s\n' "$*"
}

build_coin() {
    local image_name="$1"
    local repo_dir="$2"
    local daemon_name="$3"
    local cli_name="$4"
    local tx_name="$5"
    local config_dir="$6"
    local workdir artifact_dir

    artifact_dir="${INSTALLER_REPOS}/${repo_dir}/outputs/Ubuntu-24"
    for file in "${daemon_name}" "${cli_name}" "${tx_name}"; do
        if [ ! -f "${artifact_dir}/${file}" ]; then
            echo "ERROR: missing ${artifact_dir}/${file}" >&2
            exit 1
        fi
    done

    workdir="$(mktemp -d)"
    trap 'rm -rf "${workdir}"' RETURN
    cp "${artifact_dir}/${daemon_name}" "${workdir}/${daemon_name}"
    cp "${artifact_dir}/${cli_name}" "${workdir}/${cli_name}"
    cp "${artifact_dir}/${tx_name}" "${workdir}/${tx_name}"

    cat > "${workdir}/Dockerfile" <<EOF
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq \\
    && apt-get install -y -qq --no-install-recommends \\
        ca-certificates \\
        tini \\
        libboost-filesystem1.83.0 \\
        libboost-program-options1.83.0 \\
        libboost-thread1.83.0 \\
        libboost-chrono1.83.0t64 \\
        libevent-2.1-7t64 \\
        libevent-pthreads-2.1-7t64 \\
        libminiupnpc17 \\
        libssl3t64 \\
    && rm -rf /var/lib/apt/lists/*

COPY ${daemon_name} /usr/local/bin/${daemon_name}
COPY ${cli_name} /usr/local/bin/${cli_name}
COPY ${tx_name} /usr/local/bin/${tx_name}

RUN chmod 755 /usr/local/bin/${daemon_name} /usr/local/bin/${cli_name} /usr/local/bin/${tx_name} \\
    && mkdir -p /root/${config_dir}

LABEL org.opencontainers.image.title="${image_name} 0.15.21 daemon" \\
      org.opencontainers.image.version="${PRIMARY_TAG}" \\
      org.opencontainers.image.source="${REPO_ROOT}"

ENTRYPOINT ["/usr/bin/tini","--","/usr/local/bin/${daemon_name}"]
CMD ["-datadir=/root/${config_dir}"]
EOF

    say "Building ${NAMESPACE}/${image_name}:${PRIMARY_TAG}"
    docker build --pull -t "${NAMESPACE}/${image_name}:${PRIMARY_TAG}" "${workdir}" >/dev/null

    for tag in "${TAGS[@]}"; do
        say "Tagging ${NAMESPACE}/${image_name}:${tag}"
        docker tag "${NAMESPACE}/${image_name}:${PRIMARY_TAG}" "${NAMESPACE}/${image_name}:${tag}"
    done

    say "Verifying ${NAMESPACE}/${image_name}:${PRIMARY_TAG}"
    docker run --rm --entrypoint "/usr/local/bin/${cli_name}" "${NAMESPACE}/${image_name}:${PRIMARY_TAG}" -version >/dev/null

    if [ "${PUSH}" = "1" ]; then
        say "Pushing ${NAMESPACE}/${image_name}:${PRIMARY_TAG}"
        docker push "${NAMESPACE}/${image_name}:${PRIMARY_TAG}"
        for tag in "${TAGS[@]}"; do
            say "Pushing ${NAMESPACE}/${image_name}:${tag}"
            docker push "${NAMESPACE}/${image_name}:${tag}"
        done
    fi

    rm -rf "${workdir}"
    trap - RETURN
}

build_coin blakecoin Blakecoin-0.15.21 blakecoind blakecoin-cli blakecoin-tx .blakecoin
build_coin blakebitcoin BlakeBitcoin-0.15.21 blakebitcoind blakebitcoin-cli blakebitcoin-tx .blakebitcoin
build_coin electron Electron-ELT-0.15.21 electrond electron-cli electron-tx .electron
build_coin lithium lithium-0.15.21 lithiumd lithium-cli lithium-tx .lithium
build_coin photon Photon-0.15.21 photond photon-cli photon-tx .photon
build_coin universalmolecule universalmol-0.15.21 universalmoleculed universalmolecule-cli universalmolecule-tx .universalmolecule
