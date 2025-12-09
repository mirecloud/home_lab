helm repo add runix https://helm.runix.net
"runix" has been added to your repositories
root@node-4:/home/asd/Postgres# helm install pgadmin  runix/pgadmin4 --set env.email=info@mireclod.com --set env.password=admin  --set service.type=LoadBalancer -n pgadmin
level=WARN msg="unable to find exact version; falling back to closest available version" chart=pgadmin4 requested="" selected=1.50.0
NAME: pgadmin
LAST DEPLOYED: Tue Dec  9 12:13:06 2025
NAMESPACE: pgadmin
STATUS: deployed
REVISION: 1
DESCRIPTION: Install complete
NOTES:
CHART NAME: pgadmin4
CHART VERSION: 1.50.0
APP VERSION: 9.8



1. Get the application URL by running these commands:
     NOTE: It may take a few minutes for the LoadBalancer IP to be available.
           You can watch the status of by running 'kubectl get --namespace pgadmin svc -w pgadmin-pgadmin4'
  export SERVICE_IP=$(kubectl get svc --namespace pgadmin pgadmin-pgadmin4 -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
