# Slurm integration

## Why there are no site-specific `#SBATCH` directives here

Account, partition, QoS, wall time, node count and GPU count differ at every
site. Baking them into a committed script makes the repository unusable
elsewhere and risks committing a private allocation name. They therefore live in
`configs/cluster.yaml` (gitignored; copy from `configs/cluster.example.yaml`) and
are passed to `sbatch` on the command line by `scripts/run_phase1.sh`.

Validate your cluster config first — it refuses to launch while any placeholder
is unresolved:

```bash
python -m biomni_uncertainty.cli check-cluster --cluster-config configs/cluster.yaml
```

## Scripts

| file | purpose |
| --- | --- |
| `phase1_two_nodes.sbatch` | Full pilot. Starts replicas on every allocated node, waits for health, dispatches, aggregates. |
| `smoke.sbatch` | Same job body with `configs/smoke.yaml`; 6 runs on one node. |

Both take two positional arguments: the cluster config and the experiment config.

## Serving layout

`scripts/launch_node_servers.sh --layout auto` inspects `nvidia-smi` and picks:

| min GPU memory | layout | replicas per 4-GPU node | GPUs per replica |
| --- | --- | --- | --- |
| ≥ 70 GB | `tp2` | 2 | 2 (`0,1` and `2,3`) |
| < 70 GB | `tp4` | 1 | 4 |

Override with `--layout tp2` or `--layout tp4`. Each replica is bound to explicit
`CUDA_VISIBLE_DEVICES` and gets a distinct port (`base_port + replica_index`).

Two nodes at `tp2` therefore give **four independent serving replicas**, which is
the Phase-1 target layout.

## Endpoint publication without races

Each node writes `endpoints/node_<hostname>.json` via a temp file plus atomic
`mv`, so a reader never observes a partial file. The coordinator
(`scripts/wait_for_server.py --aggregate`) waits until every expected node has
published, merges the files into `endpoints.json`, then polls every replica's
`/v1/models` until all are healthy.

If any replica never becomes ready the coordinator exits non-zero and **the
dispatcher is not started**. Server logs are written under
`<output_root>/_job_<jobid>/server_logs/` and are preserved after the job ends.

## Shutdown

`launch_node_servers.sh` installs an `EXIT`/`INT`/`TERM` trap that sends `TERM`
then `KILL` to every replica and removes its endpoint file. The job script traps
in turn and stops the `srun` that owns the launchers, so a cancelled or
timed-out allocation still tears the servers down.

## Resumption

The dispatcher skips runs with a *valid* `COMPLETE` marker (marker plus the
required artifacts plus `completed: true` in `metadata.json`). Re-submitting the
same job continues where the previous one stopped:

```bash
sbatch ... slurm/phase1_two_nodes.sbatch configs/cluster.yaml configs/phase1.yaml
```

Only failure classes listed in `execution.retry_policy.retryable_failure_classes`
are re-queued. Substantive agent failures are preserved and never silently retried.

## Single-node use

Nothing requires two nodes. With `--nodes=1` on a 4×80GB (or larger) node the
launcher starts two `tp2` replicas and the dispatcher uses both; the pilot simply
takes about twice as long.

## Throughput note

Biomni trajectories are not purely model-bound — they also wait on generated code
execution, file I/O and external biomedical databases. `dispatch.max_concurrency`
may therefore exceed the replica count. The conservative default is one active
trajectory per replica; raise it only after observing replica utilisation.
