# Blakestream-Eliopool-15.21 Deploy Bundle

This bundle is the deploy/runtime payload for the active post-SegWit release
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

## Full Testnet Stack

For the self-contained six-chain testnet stack, use:

```bash
cd /path/to/Blakestream-Eliopool-15.21
bash deploy-bundle/deploy-full-testnet-stack.sh -local
```

or:

```bash
cd /path/to/Blakestream-Eliopool-15.21
bash deploy-bundle/deploy-full-testnet-stack.sh -pull
```

`deploy-full-testnet-stack.sh` supports only 2 daemon modes:

- `-local` builds the six coin daemons from source on the VPS
- `-pull` pulls the published `sidgrip/<coin>:15.21` daemon images on the VPS

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
- `DAEMON_INSTALL_MODE=container` is the preferred testing path right now
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

## Clean-Host Behavior

With `WIPE_REMOTE=1`, the deploy script stops the old services, removes the
old install root under `/opt/blakecoin-pool`, removes old pool logs under
`/var/log/blakecoin-pool`, and deploys the current bundle cleanly.

It does not wipe any of the six coin datadirs.

If you want the daemon installer layer reset as well, set:

- `WIPE_DAEMON_INSTALL=1`

## Archived Pre-SegWit Line

The preserved pre-SegWit tree is intentionally local-only and is not part of
the public release repo.
