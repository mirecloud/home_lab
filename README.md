===============================
  MireCloud Kubernetes Lab
===============================

Réseau LAN : 192.168.2.0/24
DNS local : 192.168.2.40
Domaine  : mirecloud.com

------------------------------------------------
Nœuds Kubernetes
------------------------------------------------
Control-plane : 192.168.2.22
Worker node-1 : 192.168.2.27 (node-1.mirecloud.com)
Worker node-2 : 192.168.2.28 (node-2.mirecloud.com)
Worker node-3 : 192.168.2.29 (node-3.mirecloud.com)

------------------------------------------------
Stack technique
------------------------------------------------
OS              : Ubuntu Server
Installation    : kubeadm
CNI             : Cilium 1.18.4
LoadBalancer    : MetalLB
Plage MetalLB   : 192.168.2.200-192.168.2.220
Ingress         : NGINX Ingress Controller
Storage         : NFS StorageClass
DNS             : DNS local (192.168.2.40)

------------------------------------------------
DNS Configuration
------------------------------------------------
Example DNS resolutions:

node-1.mirecloud.com  -> 192.168.2.27
node-2.mirecloud.com  -> 192.168.2.28
node-3.mirecloud.com  -> 192.168.2.29
gitlab.mirecloud.com  -> IP MetalLB
keycloak.mirecloud.com -> IP MetalLB

Ubuntu control-plane DNS setup:

nmcli connection modify netplan-eno1 ipv4.dns "192.168.2.40 1.1.1.1"
nmcli connection modify netplan-eno1 ipv4.ignore-auto-dns yes
nmcli connection down netplan-eno1
nmcli connection up netplan-eno1

------------------------------------------------
Flux de requêtes HTTP
------------------------------------------------
Utilisateur
   |
   v
gitlab.mirecloud.com
   |
   v
DNS local (192.168.2.40)
   |
   v
MetalLB (IP LoadBalancer)
   |
   v
NGINX Ingress Controller
   |
   v
Service Kubernetes
   |
   v
Pod (Application)

------------------------------------------------
Objectifs de ce Lab
------------------------------------------------
- Se former en profondeur sur Kubernetes
- Simuler une infra entreprise chez moi
- Tester DNS, Ingress, Cilium, LoadBalancing
- Déployer Keycloak, GitLab, Monitoring

------------------------------------------------
Auteur : MireCloud Lab
------------------------------------------------
