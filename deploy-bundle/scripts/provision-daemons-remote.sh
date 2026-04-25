#!/usr/bin/env bash
set -euo pipefail

MODE="${DAEMON_INSTALL_MODE:-existing}"
INSTALL_ROOT="${DAEMON_INSTALL_ROOT:-/opt/blakestream-daemons}"
IMAGE_NAMESPACE="${DAEMON_IMAGE_NAMESPACE:-sidgrip}"
IMAGE_TAG="${DAEMON_IMAGE_TAG:-15.21}"
SOURCE_ROOT="${INSTALL_ROOT}/source"
BUILD_JOBS="${DAEMON_BUILD_JOBS:-$(nproc)}"
DB4_PREFIX="${INSTALL_ROOT}/db4"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: provision-daemons-remote.sh must run as root" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

CHAINS=(
    "blakecoin|Blakecoin|blakecoind|blakecoin-cli|blakecoin-tx|blakecoin.conf|.blakecoin|/var/lib/blakecoin-mainnet|8772|8773|https://github.com/BlueDragon747/Blakecoin.git|master"
    "blakebitcoin|BlakeBitcoin|blakebitcoind|blakebitcoin-cli|blakebitcoin-tx|blakebitcoin.conf|.blakebitcoin|/var/lib/blakebitcoin-mainnet|8243|8356|https://github.com/BlakeBitcoin/BlakeBitcoin.git|master"
    "electron|Electron|electrond|electron-cli|electron-tx|electron.conf|.electron|/var/lib/electron-mainnet|6852|6853|https://github.com/BlueDragon747/Electron-ELT.git|master"
    "lithium|Lithium|lithiumd|lithium-cli|lithium-tx|lithium.conf|.lithium|/var/lib/lithium-mainnet|12000|12007|https://github.com/BlueDragon747/lithium.git|master"
    "photon|Photon|photond|photon-cli|photon-tx|photon.conf|.photon|/var/lib/photon-mainnet|8984|35556|https://github.com/BlueDragon747/photon.git|master"
    "universalmolecule|UniversalMolecule|universalmoleculed|universalmolecule-cli|universalmolecule-tx|universalmolecule.conf|.universalmolecule|/var/lib/universalmolecule-mainnet|5921|24785|https://github.com/BlueDragon747/universalmol.git|master"
)

say() {
    printf '\033[1;35m==>\033[0m %s\n' "$*"
}

ensure_apt() {
    apt-get update -qq >/dev/null
    apt-get install -y -qq --no-install-recommends "$@" >/dev/null
}

random_token() {
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
}

write_managed_conf() {
    local key="$1"
    local conf_name="$2"
    local datadir="$3"
    local rpc_port="$4"
    local p2p_port="$5"
    mkdir -p "$datadir"
    cat > "${datadir}/${conf_name}" <<EOF
server=1
daemon=0
listen=1
txindex=1
upnp=0
discover=1
shrinkdebugfile=0
printtoconsole=1
fallbackfee=0.0001
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=${rpc_port}
port=${p2p_port}
rpcuser=${key}_rpc
rpcpassword=$(random_token)
EOF
    chmod 600 "${datadir}/${conf_name}"
}

write_cli_wrapper() {
    local container_name="$1"
    local cli_name="$2"
    local tx_name="$3"
    local conf_name="$4"
    local container_datadir="$5"

    cat > "/usr/local/bin/${cli_name}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
args=()
have_conf=0
have_datadir=0
for arg in "\$@"; do
    case "\$arg" in
        -conf=*)
            args+=("-conf=${container_datadir}/${conf_name}")
            have_conf=1
            ;;
        -datadir=*)
            args+=("-datadir=${container_datadir}")
            have_datadir=1
            ;;
        *)
            args+=("\$arg")
            ;;
    esac
done
if [ "\$have_conf" -eq 0 ]; then
    args=("-conf=${container_datadir}/${conf_name}" "\${args[@]}")
fi
if [ "\$have_datadir" -eq 0 ]; then
    args=("-datadir=${container_datadir}" "\${args[@]}")
fi
exec docker exec ${container_name} /usr/local/bin/${cli_name} "\${args[@]}"
EOF
    chmod 755 "/usr/local/bin/${cli_name}"

    cat > "/usr/local/bin/${tx_name}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
args=()
have_datadir=0
for arg in "\$@"; do
    case "\$arg" in
        -datadir=*)
            args+=("-datadir=${container_datadir}")
            have_datadir=1
            ;;
        *)
            args+=("\$arg")
            ;;
    esac
done
if [ "\$have_datadir" -eq 0 ]; then
    args=("-datadir=${container_datadir}" "\${args[@]}")
fi
exec docker exec ${container_name} /usr/local/bin/${tx_name} "\${args[@]}"
EOF
    chmod 755 "/usr/local/bin/${tx_name}"
}

write_source_unit() {
    local key="$1"
    local label="$2"
    local daemon_name="$3"
    local conf_name="$4"
    local datadir="$5"
    cat > "/etc/systemd/system/blakestream-mainnet-${key}.service" <<EOF
[Unit]
Description=BlakeStream ${label} mainnet daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${datadir}
ExecStart=/opt/${key}-current/bin/${daemon_name} -conf=${datadir}/${conf_name} -datadir=${datadir}
ExecStop=/opt/${key}-current/bin/${daemon_name} -conf=${datadir}/${conf_name} -datadir=${datadir} stop
Restart=always
RestartSec=5
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF
}

ensure_docker_stack() {
    ensure_apt ca-certificates curl docker.io
    if ! docker compose version >/dev/null 2>&1; then
        if ! apt-get install -y -qq --no-install-recommends docker-compose-v2 >/dev/null 2>&1; then
            ensure_apt docker-compose-plugin
        fi
    fi
    docker compose version >/dev/null 2>&1
    systemctl enable --now docker >/dev/null 2>&1 || true
}

build_db4() {
    if [ -f "${DB4_PREFIX}/lib/libdb_cxx-4.8.a" ] || [ -f "${DB4_PREFIX}/lib/libdb_cxx.a" ]; then
        return 0
    fi
    ensure_apt build-essential autoconf automake libtool pkg-config git ca-certificates wget curl libssl-dev libevent-dev libminiupnpc-dev libboost-all-dev
    mkdir -p "${INSTALL_ROOT}"
    local workdir
    workdir="$(mktemp -d)"
    trap 'rm -rf "${workdir}"' RETURN
    (
        cd "${workdir}"
        wget -q http://download.oracle.com/berkeley-db/db-4.8.30.NC.tar.gz
        echo "12edc0df75bf9abd7f82f821795bcee50f42cb2e5f76a6a281b85732798364ef  db-4.8.30.NC.tar.gz" | sha256sum -c - >/dev/null
        tar xzf db-4.8.30.NC.tar.gz
        sed -i 's/__atomic_compare_exchange/__atomic_compare_exchange_db/g' db-4.8.30.NC/dbinc/atomic.h
        cd db-4.8.30.NC/build_unix
        ../dist/configure --enable-cxx --disable-shared --with-pic --prefix="${DB4_PREFIX}" >/dev/null
        make -j"${BUILD_JOBS}" >/dev/null
        make install >/dev/null
    )
}

provision_container_mode() {
    local compose_file="${INSTALL_ROOT}/docker-compose.yml"
    say "Installing Docker runtime"
    ensure_docker_stack

    mkdir -p "${INSTALL_ROOT}"

    {
        echo "services:"
        for row in "${CHAINS[@]}"; do
            IFS='|' read -r key label daemon_name cli_name tx_name conf_name config_dir datadir rpc_port p2p_port repo_url repo_branch <<< "${row}"
            say "Configuring ${label} container datadir"
            write_managed_conf "${key}" "${conf_name}" "${datadir}" "${rpc_port}" "${p2p_port}"
            echo
            echo "  ${key}:"
            echo "    container_name: blakestream-${key}"
            echo "    image: ${IMAGE_NAMESPACE}/${key}:${IMAGE_TAG}"
            echo "    restart: unless-stopped"
            echo "    network_mode: host"
            echo "    volumes:"
            echo "      - ${datadir}:${config_dir}"
            echo "    command:"
            echo "      - -conf=${config_dir}/${conf_name}"
            echo "      - -datadir=${config_dir}"
            echo "      - -printtoconsole=1"
        done
    } > "${compose_file}"

    for row in "${CHAINS[@]}"; do
        IFS='|' read -r key label daemon_name cli_name tx_name conf_name config_dir datadir rpc_port p2p_port repo_url repo_branch <<< "${row}"
        say "Pulling ${IMAGE_NAMESPACE}/${key}:${IMAGE_TAG}"
        docker pull "${IMAGE_NAMESPACE}/${key}:${IMAGE_TAG}" >/dev/null
    done

    say "Starting daemon containers"
    docker compose -f "${compose_file}" up -d >/dev/null

    for row in "${CHAINS[@]}"; do
        IFS='|' read -r key label daemon_name cli_name tx_name conf_name config_dir datadir rpc_port p2p_port repo_url repo_branch <<< "${row}"
        write_cli_wrapper "blakestream-${key}" "${cli_name}" "${tx_name}" "${conf_name}" "${config_dir}"
    done
}

provision_source_mode() {
    say "Installing source-build dependencies"
    ensure_apt build-essential autoconf automake libtool pkg-config git ca-certificates wget curl libssl-dev libevent-dev libminiupnpc-dev libboost-all-dev
    build_db4

    mkdir -p "${SOURCE_ROOT}"

    for row in "${CHAINS[@]}"; do
        IFS='|' read -r key label daemon_name cli_name tx_name conf_name config_dir datadir rpc_port p2p_port repo_url repo_branch <<< "${row}"
        local_src="${SOURCE_ROOT}/${key}"
        say "Building ${label} from ${repo_url} (${repo_branch})"
        rm -rf "${local_src}"
        git clone --depth 1 -b "${repo_branch}" "${repo_url}" "${local_src}" >/dev/null 2>&1
        (
            cd "${local_src}"
            ./autogen.sh >/dev/null
            ./configure \
                --without-gui \
                --disable-tests \
                --disable-bench \
                --with-incompatible-bdb \
                CPPFLAGS="-I${DB4_PREFIX}/include" \
                LDFLAGS="-L${DB4_PREFIX}/lib" >/dev/null
            make -j"${BUILD_JOBS}" >/dev/null
        )

        install -d "/opt/${key}-current/bin"
        install -m 755 "${local_src}/src/${daemon_name}" "/opt/${key}-current/bin/${daemon_name}"
        install -m 755 "${local_src}/src/${cli_name}" "/opt/${key}-current/bin/${cli_name}"
        install -m 755 "${local_src}/src/${tx_name}" "/opt/${key}-current/bin/${tx_name}"
        ln -sfn "/opt/${key}-current/bin/${cli_name}" "/usr/local/bin/${cli_name}"
        ln -sfn "/opt/${key}-current/bin/${tx_name}" "/usr/local/bin/${tx_name}"

        write_managed_conf "${key}" "${conf_name}" "${datadir}" "${rpc_port}" "${p2p_port}"
        write_source_unit "${key}" "${label}" "${daemon_name}" "${conf_name}" "${datadir}"
    done

    systemctl daemon-reload
    for row in "${CHAINS[@]}"; do
        IFS='|' read -r key label daemon_name cli_name tx_name conf_name config_dir datadir rpc_port p2p_port repo_url repo_branch <<< "${row}"
        say "Starting blakestream-mainnet-${key}"
        systemctl enable --now "blakestream-mainnet-${key}" >/dev/null
    done
}

case "${MODE}" in
    container)
        provision_container_mode
        ;;
    source)
        provision_source_mode
        ;;
    existing)
        say "Daemon install mode is existing; nothing to provision"
        ;;
    *)
        echo "ERROR: unsupported DAEMON_INSTALL_MODE=${MODE}" >&2
        exit 1
        ;;
esac
