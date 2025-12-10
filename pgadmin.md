#  MireCloud – PGAdmin Deployment on Kubernetes

This document describes how PGAdmin4 is deployed inside the MireCloud Kubernetes Lab, using the Helm chart `runix/pgadmin4`. It includes installation, configuration, and UI access instructions.

---

##  Overview

PGAdmin is deployed as:

- A Kubernetes Deployment
- Exposed via a LoadBalancer service
- Configured with:
  - Email: info@mirecloud.com
  - Password: admin
- Namespace: `pgadmin`

This provides a graphical interface for managing the PostgreSQL service running in the `postgres` namespace.

---

##  Installation Command

```bash
helm upgrade --install pgadmin \
  runix/pgadmin4 \
  --set env.email=info@mirecloud.com \
  --set env.password=admin \
  --set service.type=LoadBalancer \
  -n pgadmin
