# Crime bulletin ML510 — deployment on Mirecloud home_lab

Adapted from the k3d manifests in [mirecloud/criminal-work](https://github.com/mirecloud/criminal-work/tree/main/apps/crime_bulletin/deploy/k8s). **The source repository is unchanged.**

## Home-lab integration

- ArgoCD Application: `clusters/home-lab/crime-bulletin-app.yaml`; **manual sync** (no automated sync policy).
- Namespace: `ml510`; API: 2 FastAPI replicas; UI: 1 Streamlit replica.
- Cilium Gateway API + cert-manager `mirecloud-ca-issuer`; DNS via ExternalDNS; URL: `https://crimes.mirecloud.com`.
- vLLM: internal ClusterIP router at `http://vllm-router-service.vllm.svc.cluster.local/v1`, model `warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ`.
- Docker images: `docker.io/mirecloud/crime-api:1.0.0` and `docker.io/mirecloud/crime-ui:1.0.0`.
- CronJob: Monday 07:00 **America/Toronto**, but **suspended** until automated data/model refresh exists.

Unlike the training k3d cluster manifests, these files do **not** use Traefik, `crimes.localhost`, the external vLLM HTTPS endpoint, its custom CA ConfigMap or a Docker Hub pull secret.

## Before first sync

1. Verify both Docker Hub tags are published and pullable. The API image must contain `artifacts/00_start_here/` and `artifacts/04_comparaison/`, built from the intended CSV and model.
2. Verify `vllm-router-service` in namespace `vllm` is reachable and its `/v1/models` response includes the configured model ID.
3. Confirm `GatewayClass/cilium`, `ClusterIssuer/mirecloud-ca-issuer`, ExternalDNS and CA trust are ready.
4. The `LLM_API_KEY=EMPTY` value is **not a secret**: it is a placeholder for an unauthenticated local vLLM router. If the router requires authentication, replace it with a Vault/ExternalSecret-managed credential.
5. If the ArgoCD application-of-applications does not monitor `clusters/home-lab`, register `clusters/home-lab/crime-bulletin-app.yaml` manually.

Sync the `crime-bulletin` Application manually in ArgoCD once these prerequisites are satisfied.

## Verify

```bash
kubectl -n ml510 get deploy,svc,gateway,httproute,certificate,cronjob
kubectl -n ml510 rollout status deploy/crime-api
kubectl -n ml510 rollout status deploy/crime-ui
kubectl -n ml510 port-forward svc/crime-ui 8501:80
```

The API readiness probe verifies that the Ridge model loaded; it does not check vLLM availability. Test the end-to-end LLM by generating a bulletin through the UI.

## Scheduled bulletin caveat

The API image embeds a static panel and Ridge model. The CronJob does not download the latest CSV, retrain, or build images; unsuspending it now would publish repeated stale predictions. For a one-time test with current image:

```bash
kubectl -n ml510 create job --from=cronjob/crime-bilan-hebdo crime-bilan-manual
kubectl -n ml510 logs job/crime-bilan-manual
```

After implementing source-data refresh, model re-training, image tagging and validation, update the tags in API Deployment and CronJob, change `suspend: false`, and (optionally) enable ArgoCD automated sync.

**No real credentials are committed in this app folder.** These are GitOps definitions, not a confirmation that workloads are running.
