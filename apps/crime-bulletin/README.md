# Crime bulletin ML510 — deployment on Mirecloud home_lab

Adapted from the k3d manifests in [mirecloud/criminal-work](https://github.com/mirecloud/criminal-work/tree/main/apps/crime_bulletin/deploy/k8s). **The source repository is unchanged.**

## Home-lab integration

- ArgoCD Application: `clusters/home-lab/crime-bulletin-app.yaml`; automated sync (prune + selfHeal).
- Namespace: `ml510`; API: 2 FastAPI replicas; UI: 1 Streamlit replica.
- Security (from `criminal-work`): `RuntimeDefault` seccomp, non-root UID 10001, read-only root filesystem, no Linux capabilities, and 64Mi `/tmp` volumes for API/UI.
- `60-networkpolicy.yaml`: ingress to the API is permitted only from pods in namespace `ml510` on TCP port 8000.
- Cilium Gateway API + cert-manager `mirecloud-ca-issuer`; DNS via ExternalDNS; URL: `https://crimes.mirecloud.com`.
- vLLM: internal ClusterIP router at `http://vllm-router-service.vllm.svc.cluster.local/v1`, model `warshanks/Huihui-Qwen3-14B-abliterated-v2-AWQ`.
- Docker images: `docker.io/mirecloud/crime-api:1.2.0` and `docker.io/mirecloud/crime-ui:1.0.0`.
- CronJob: Monday 07:00 **America/Toronto**, **suspended** until automated data/model refresh exists. The new script returns success for both accepted and rejected LLM responses, records status in JSON logs, and retries once on service errors. Retains 52 successful and 10 failed Jobs.
- ArgoCD automated sync is enabled in the existing Application: committing this update may roll out the API image and security settings immediately.

Unlike the training k3d cluster manifests, these files do **not** use Traefik, `crimes.localhost`, the external vLLM HTTPS endpoint, its custom CA ConfigMap or a Docker Hub pull secret.

## Before first sync

1. Verify both Docker Hub tags are published and pullable. The API image must contain `artifacts/00_start_here/` and `artifacts/04_comparaison/`, built from the intended CSV and model.
2. Verify `vllm-router-service` in namespace `vllm` is reachable and its `/v1/models` response includes the configured model ID.
3. Confirm `GatewayClass/cilium`, `ClusterIssuer/mirecloud-ca-issuer`, ExternalDNS and CA trust are ready.
4. The `LLM_API_KEY=EMPTY` value is **not a secret**: it is a placeholder for an unauthenticated local vLLM router. An optional `crime-llm` Secret can override it if vLLM authentication is added; manage any real credential through Vault/ExternalSecret.
5. If the ArgoCD application-of-applications does not monitor `clusters/home-lab`, register `clusters/home-lab/crime-bulletin-app.yaml` manually.

Apply the Application once these prerequisites are satisfied: `kubectl apply -f clusters/home-lab/crime-bulletin-app.yaml`.

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

After implementing source-data refresh, model re-training, image tagging and validation, update the tags in API Deployment and CronJob, then change `suspend: false`.

The `criminal-work` source repository contains CI and a `taux_rejet.py` analysis script. These are application-code assets, not Kubernetes deployment manifests, and are not duplicated in `home_lab`. The CronJob calls the script embedded in `crime-api:1.2.0`.

**No real credentials are committed in this app folder.** These are GitOps definitions, not a confirmation that workloads are running.
