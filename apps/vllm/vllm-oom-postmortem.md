# Post-Mortem: vLLM Mistral-7B Pod CrashLoopBackOff (OOMKilled)

| Field | Value |
|---|---|
| **Incident ID** | INC-2026-0624-vllm-oom |
| **Status** | Resolved (one follow-up pending) |
| **Severity** | SEV-2 (single service down, no user-facing prod impact — test environment) |
| **Date** | 2026-06-23 → 2026-06-24 |
| **Affected service** | `vllm` (Mistral-7B inference engine), namespace `vllm` |
| **Affected node** | `node-gpu` (192.168.2.163) |
| **Author** | Emmanuel Catin |
| **Deployment model** | GitOps via Argo CD (`mirecloud/home_lab`, path `apps/vllm`) |

---

## 1. Summary

The vLLM serving pod for `RedHatAI/Mistral-7B-Instruct-v0.3-FP8` was stuck in a
`CrashLoopBackOff`, restarting 44+ times over several hours. Each container was
terminated by the kernel OOM killer (`OOMKilled`, exit code 137) and never opened
its HTTP port, so the Kubernetes startup probe reported `connection refused`.

The investigation uncovered **three independent, stacked root causes**, each of
which had to be fixed in turn before the pod could start. The final and least
obvious cause was **runtime JIT compilation of CUDA kernels** for a GPU
(NVIDIA RTX 5060 Ti, Blackwell `sm_120`) too new to have pre-compiled kernels
shipped in the vLLM image — the compiler spawned a swarm of parallel processes
that exhausted host RAM.

After applying all three fixes, the pod starts cleanly, serves inference, and
peaks at ~10.8 GiB host RAM (well under its 20 GiB limit).

---

## 2. Impact

- The Mistral-7B inference endpoint was **completely unavailable** for the
  duration of the incident (~5 hours of crash-looping).
- No data loss. No impact to other workloads on the cluster.
- Environment was labelled `environment=test`, so there was no external user impact.

---

## 3. Environment

| Component | Detail |
|---|---|
| GPU | NVIDIA **RTX 5060 Ti**, 16 GiB VRAM, **Blackwell architecture (compute capability 12.0 / `sm_120`)** |
| GPU driver / CUDA | 595.71.05 / CUDA 13.2 |
| Node RAM | ~24 GB total (~22.8 GiB allocatable) |
| Container image | `vllm/vllm-openai:v0.11.0` |
| Model | `RedHatAI/Mistral-7B-Instruct-v0.3-FP8` (~7 GiB weights, FP8 quantized) |
| Helm chart | `vllm-stack` 0.1.11 (production-stack) |
| Model cache | PVC `vllm-mistral-storage-claim` mounted at `/data` (`HF_HOME=/data`) |

---

## 4. Symptoms (as observed)

```
State:          Waiting (CrashLoopBackOff)
Last State:     Terminated
  Reason:       OOMKilled
  Exit Code:    137
Restart Count:  44
Events:
  Warning  Unhealthy  Startup probe failed: connect: connection refused
  Warning  BackOff    Back-off restarting failed container
```

Key observation: **exit code 137 / OOMKilled is always a host-memory (RAM) kill,
never a GPU/VRAM exhaustion.** A VRAM exhaustion surfaces as a CUDA
`OutOfMemoryError` traceback and a normal crash, not `OOMKilled`. This pointed
the investigation at host RAM from the very start.

---

## 5. Timeline

> Times in cluster UTC. Container log timestamps run on a different TZ (UTC-7).

| Time (UTC) | Event |
|---|---|
| 2026-06-23 21:40 | Pod first scheduled on `node-gpu`. Begins crash-looping. |
| ~21:40 → 02:30 | 44 restarts, all `OOMKilled (137)`. Startup probe `connection refused`. |
| 02:31 | Investigation begins. Confirmed exit 137 = host-RAM OOM, not GPU. |
| 02:32 | **Cause #1 identified** — logs show crash during `torch.compile` (`Dynamo bytecode transform` / `Cache the graph`). Recommended `--enforce-eager`. |
| ~02:35 | `--enforce-eager` deployed. Compile phase gone, but pod **still OOMKilled** right after weights load. |
| ~02:50 | GPU confirmed: RTX 5060 Ti, **16 GiB VRAM free** → VRAM ruled out as the cause. |
| ~02:53 | **Cause #2 addressed** — memory request raised 8Gi→12Gi, explicit limit 16Gi→20Gi added. Still OOMKilled at the profiling step. |
| ~03:00 | **Forensic breakthrough**: `kubectl debug node/node-gpu` used to read the kernel OOM-killer log. Killed processes were **`cicc`** (NVIDIA CUDA compiler), ~1.3 GB each, ~6 in parallel — **not** the Python/vLLM process (0.6 GB). |
| ~03:02 | **Cause #3 identified** — runtime CUDA kernel JIT compilation for Blackwell `sm_120`. |
| ~03:04 | **Cause #3 fixed** — env vars added to cap compiler parallelism and arch scope. |
| ~03:16 | Pod survives compilation (cgroup peak 10.8 GiB, no OOM). |
| ~03:22 | `init engine ... took 241.14 seconds`; `Application startup complete`. Pod `1/1 Running`. |
| ~03:24 | Inference verified via `/v1/chat/completions` — model returns a valid completion. |

---

## 6. Root Cause Analysis

The incident was not a single bug but **three stacked failure modes**, each
masking the next. Fixing one simply revealed the one behind it.

### Cause #1 — `torch.compile` / CUDA-graph host-RAM spike
vLLM V1 runs `torch.compile` (Inductor) and captures CUDA graphs at startup.
On a memory-constrained node this produces a large, transient **host** RAM spike.
The logs ended exactly at `Dynamo bytecode transform` / `Cache the graph for
dynamic shape` before the kill.

- **Fix:** `--enforce-eager` (disables Inductor compilation and CUDA-graph capture).

### Cause #2 — Insufficient memory request and no limit
The pod requested only `8Gi` of memory and had **no memory limit** (QoS
`Burstable`). Under node memory pressure, a Burstable pod exceeding its request
is a prime target for the kernel OOM killer.

- **Fix:** `requestMemory: 12Gi`, `limitMemory: 20Gi` (sized to the 24 GB node).

### Cause #3 — CUDA kernel JIT compilation for an unsupported GPU arch (primary)
The RTX 5060 Ti is a **Blackwell `sm_120`** GPU, newer than the pre-compiled
kernels shipped in `vllm/vllm-openai:v0.11.0` (and its FlashInfer dependency).
On the first forward pass (the memory-profiling step, right after
`Model loading took 7.0085 GiB`), vLLM/FlashInfer **compiled CUDA kernels at
runtime**. With no parallelism cap it spawned ~6 concurrent `cicc` compiler
processes at ~1.3 GB each, plus `nvcc`/`ninja`/`cudafe++` — collectively
~15–20 GB, breaching even the raised 20 GiB cgroup limit.

The triggering condition was visible in the logs as a warning:
```
TORCH_CUDA_ARCH_LIST is not set, all archs for visible cards are included for compilation.
```
i.e. it was compiling for *every* architecture, in parallel, unbounded.

**Smoking-gun evidence** (kernel OOM-killer log, via `kubectl debug node`):
```
Memory cgroup out of memory: Killed process 85419 (cicc) anon-rss:1349268kB
Memory cgroup out of memory: Killed process 85421 (cicc) anon-rss:1324980kB
Memory cgroup out of memory: Killed process 85423 (cicc) anon-rss:1318472kB
Memory cgroup out of memory: Killed process 85425 (cicc) anon-rss:1351256kB
...
Memory cgroup out of memory: Killed process 85068 (vllm)    anon-rss:610300kB   <- vLLM itself only 0.6 GB
```

- **Fix:** cap compilation and scope it to the actual GPU arch:
  - `MAX_JOBS=2` — at most 2 parallel compile jobs (~2.6 GB instead of ~18 GB)
  - `NVCC_THREADS=1`
  - `TORCH_CUDA_ARCH_LIST=12.0` — compile only for `sm_120`, not all archs

---

## 7. Resolution

Final configuration added to `apps/vllm/values.yaml` under the Mistral `modelSpec`:

```yaml
        requestMemory: "12Gi"
        limitMemory: "20Gi"

        env:
          - name: MAX_JOBS
            value: "2"                 # cap parallel CUDA compile jobs (prevents host-RAM OOM)
          - name: NVCC_THREADS
            value: "1"
          - name: TORCH_CUDA_ARCH_LIST
            value: "12.0"              # compile only for the RTX 5060 Ti (sm_120)
          - name: VLLM_CACHE_ROOT
            value: "/data/vllm_cache"
          - name: TORCH_EXTENSIONS_DIR
            value: "/data/torch_ext"

        vllmConfig:
          extraArgs:
            - "--enforce-eager"        # disable torch.compile / cudagraph host-RAM spike
            - "--chat-template"
            - "/templates/mistral-v0.3.jinja"
            - "--gpu-memory-utilization"
            - "0.85"
```

Deployed through the normal GitOps flow (commit → push → Argo CD auto-sync).

---

## 8. Verification

- Pod `vllm-mistral-deployment-vllm-...` reached **`1/1 Running`, 0 restarts**.
- `init engine (profile, create kv cache, warmup model) took 241.14 seconds`
  (one-time first-boot kernel compilation), then `Application startup complete`.
- cgroup memory peaked at **10.8 GiB** (anon 3.4 + file/page-cache 7.3) vs the
  20 GiB limit — comfortable headroom.
- GPU KV cache: 47,744 tokens; max concurrency 5.83x at 8,192 tokens/request.
- **End-to-end inference confirmed** via `POST /v1/chat/completions` — the model
  returned a valid completion.

---

## 9. What Went Well / What Went Wrong

**Went well**
- Correctly ruled out GPU/VRAM early using the exit-137 signal, avoiding a wasted
  detour into model-size reduction.
- The `kubectl debug node` step to read the kernel OOM-killer log was decisive —
  it converted guesswork into proof (compiler processes, not the model).

**Went wrong / contributing factors**
- The node was running a GPU (Blackwell `sm_120`) newer than the vLLM image's
  pre-compiled kernel support — an unvalidated hardware/software combination.
- Initial resource config had no memory limit and an undersized request.
- The startup probe masked the real failure as a generic "connection refused",
  delaying root-cause focus.

---

## 10. Action Items

| # | Action | Owner | Priority | Status |
|---|---|---|---|---|
| 1 | Persist the **FlashInfer JIT cache** to the PVC so restarts don't recompile (~4 min). Add env `FLASHINFER_BASE_DIR=/data` (cache currently lands in ephemeral `/root/.cache/flashinfer`, ~416 MB). | Emmanuel | High | **Pending** |
| 2 | Document the Blackwell `sm_120` + vLLM 0.11.0 JIT-compilation requirement for any future GPU workload on `node-gpu`. | Emmanuel | Medium | Done (memory note) |
| 3 | Reconcile the custom `mistral-v0.3.jinja` chat template with the model's official template (log warns of possible quality degradation). | Emmanuel | Low | Open |
| 4 | Evaluate re-enabling CUDA graphs (drop `--enforce-eager`) for throughput, now that memory limits and compile caps are in place. | Emmanuel | Low | Open |
| 5 | Consider raising the engine startup probe budget, or pre-warming the JIT cache, so first-boot compilation can't trip the probe. | Emmanuel | Low | Open |

---

## 11. Lessons Learned

1. **`OOMKilled` (137) is always host RAM, never VRAM.** Use it to immediately
   split the search space.
2. **When a container OOMs without an obvious large allocation, read the kernel
   OOM-killer log** (`dmesg` / `kubectl debug node`). It names the exact process
   and its RSS — here it revealed `cicc` compilers, not the application.
3. **Bleeding-edge GPUs trigger runtime kernel compilation.** If the GPU arch is
   newer than the framework's pre-built kernels, expect a heavy first-boot
   compile. Cap it (`MAX_JOBS`, `NVCC_THREADS`), scope it (`TORCH_CUDA_ARCH_LIST`),
   and **persist its cache** to durable storage.
4. **Raising memory limits is not a fix when the consumer is unbounded
   parallelism.** On a 24 GB node, no limit value would have contained ~18 GB of
   parallel compilers — the parallelism itself had to be capped.
5. **Symptoms can stack.** Don't assume the first fix that changes behavior is
   "the" fix; verify to the point of a working request.

---

## Appendix A — Useful commands

```bash
# Cluster access from the control node
sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf -n vllm get pods -o wide

# Confirm the host-RAM kill reason
kubectl -n vllm describe pod <pod> | grep -A6 "Last State"

# THE decisive step — read the node's OOM-killer log without SSH
kubectl debug node/node-gpu --image=busybox --profile=sysadmin -- \
  sh -c 'dmesg | grep -iE "Killed process|Memory cgroup out of memory" | tail'

# Inspect live cgroup memory inside the pod
kubectl -n vllm exec <pod> -- sh -c \
  'cat /sys/fs/cgroup/memory.current; grep -E "^anon |^file " /sys/fs/cgroup/memory.stat'

# Verify env vars were injected by the chart
kubectl -n vllm get pod <pod> \
  -o jsonpath='{range .spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}'
```

## Appendix B — Quick diagnostic flow for "GPU pod won't start"

```
OOMKilled (137)? ──yes──> Host RAM problem (NOT VRAM)
   │                          │
   no                         ├─ crash during "Dynamo/torch.compile"? -> --enforce-eager
   │                          ├─ request too low / no limit?           -> set request + limit
   ▼                          └─ dmesg shows cicc/nvcc OOM?            -> cap MAX_JOBS/NVCC_THREADS,
CUDA OutOfMemoryError?                                                    set TORCH_CUDA_ARCH_LIST,
   -> lower gpu-memory-utilization / max-model-len / smaller model        persist JIT cache to PVC
```