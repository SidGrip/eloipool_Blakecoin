# Blakestream-Eliopool-15.21 Mainnet Deploy Bundle

This bundle is the live deploy/runtime payload for the public mainnet release
repo `Blakestream-Eliopool-15.21`.

Active operator contract:

- bare `<40hex>[.worker]` is the only mining-key username form
- bare mining keys derive native-bech32 payouts through the configured HRP
- direct payout-address usernames still pass through as compatibility input

## Refreshing The Bundle

After changing the root repo, rebuild the vendored `deploy-bundle/eloipool/`
copy:

```bash
cd /path/to/Blakestream-Eliopool-15.21
bash deploy-bundle/scripts/build-bundle.sh
```

That keeps the shipped `deploy-bundle/eloipool/` tree aligned with the root
runtime/tests.

## Deploying

```bash
cd /path/to/Blakestream-Eliopool-15.21
bash deploy-bundle/deploy.sh <host> [user] [password]
```

## Full Six-Chain Deploy

For the full six-chain deploy entrypoint, use:

```bash
cd /path/to/Blakestream-Eliopool-15.21
bash deploy-bundle/deploy-full-stack.sh -local
```

or:

```bash
cd /path/to/Blakestream-Eliopool-15.21
bash deploy-bundle/deploy-full-stack.sh -pull
```

`deploy-full-stack.sh` supports only 2 daemon modes:

- `-local` builds the six coin daemons from source on the VPS
- `-pull` pulls the published `sidgrip/<coin>:15.21` daemon images on the VPS

By default, the script deploys `mainnet`.

Set one of these only when you want a different network:

- `NETWORK_MODE=testnet`
- `NETWORK_MODE=regtest`

Before deploying, it scans the target for existing BlakeStream systemd units,
daemon processes, and Docker containers and prints a summary of what it found.
That detection is informational only. The selected mode still controls the
deploy.

Important release settings:

- `deploy.sh` supports 3 daemon install modes:
  - `DAEMON_INSTALL_MODE=existing` keeps using daemons already on the host
  - `DAEMON_INSTALL_MODE=container` pulls `sidgrip/<coin>:15.21` images and runs them locally with Docker
  - `DAEMON_INSTALL_MODE=source` clones the upstream coin repos and compiles them on the host
- `deploy.sh` still discovers the 6 RPC conf files + CLI tools automatically after provisioning
- `DAEMON_INSTALL_MODE=container` is the preferred Docker deployment path
- source mode is wired to the upstream repo/branch map from the six coin build scripts:
  - Blakecoin `https://github.com/BlueDragon747/Blakecoin.git` `master`
  - BlakeBitcoin `https://github.com/BlakeBitcoin/BlakeBitcoin.git` `master`
  - Electron `https://github.com/BlueDragon747/Electron-ELT.git` `master`
  - Photon `https://github.com/BlueDragon747/photon.git` `master`
  - Lithium `https://github.com/BlueDragon747/lithium.git` `master`
  - UniversalMolecule `https://github.com/BlueDragon747/universalmol.git` `master`
- `MINING_KEY_SEGWIT_HRP` defaults to `blc`
- `TrackerAddr` is the pool keep / fallback wallet
- the child-chain pool payout addresses are generated automatically unless
  `POOL_AUX_ADDRESS_*` overrides are supplied
- `DASH_MINING_KEY_V2_COIN_HRPS` defaults to the full BlakeStream mainnet HRP set

Container-mode example:

```bash
cd /path/to/Blakestream-Eliopool-15.21
DAEMON_INSTALL_MODE=container \
DAEMON_IMAGE_NAMESPACE=sidgrip \
DAEMON_IMAGE_TAG=15.21 \
bash deploy-bundle/deploy.sh <host> [user] [password]
```

## Redeploy Behavior

The deploy script stops any existing BlakeStream services and containers that
match the managed stack, then redeploys the current bundle.

It does not wipe the host or remove the six coin datadirs.
