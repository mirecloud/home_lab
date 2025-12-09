 helm install monitoring oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack -n prometheus-stack
Pulled: ghcr.io/prometheus-community/charts/kube-prometheus-stack:80.1.0
Digest: sha256:ca028a9941faf886ef87f86424adcd664a05c027b540cebaa334a9ab2b8dc991
NAME: monitoring
LAST DEPLOYED: Tue Dec  9 16:47:40 2025
NAMESPACE: prometheus-stack
STATUS: deployed
REVISION: 1
DESCRIPTION: Install complete
NOTES:
kube-prometheus-stack has been installed. Check its status by running:
  kubectl --namespace prometheus-stack get pods -l "release=monitoring"

Get Grafana 'admin' user password by running:

  kubectl --namespace prometheus-stack get secrets monitoring-grafana -o jsonpath="{.data.admin-password}" | base64 -d ; echo

Access Grafana local instance:

  export POD_NAME=$(kubectl --namespace prometheus-stack get pod -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=monitoring" -oname)
  kubectl --namespace prometheus-stack port-forward $POD_NAME 3000

Get your grafana admin user password by running:

  kubectl get secret --namespace prometheus-stack -l app.kubernetes.io/component=admin-secret -o jsonpath="{.items[0].data.admin-password}" | base64 --decode ; echo


Visit https://github.com/prometheus-operator/kube-prometheus for instructions on how to create & configure Alertmanager and Prometheus instances using the Operator.




kubectl -n prometheus-stack create secret tls wildcard-mirecloud-tls     --cert=/home/asd/mirecloud-ca/wildcard.mirecloud.com.crt     --key=/home/asd/mirecloud-ca/wildcard.mirecloud.com.key

