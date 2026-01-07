# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains Ansible playbooks and Kubernetes configurations for deploying and managing a 5-node K3s cluster on Raspberry Pi hardware (mix of Pi 4s and Pi 3s). The cluster uses ArgoCD for GitOps-based application deployment, MetalLB for load balancing, Longhorn for distributed storage, and includes a monitoring stack (Prometheus/Grafana).

**External Access**: The cluster is accessible externally via nginx-proxy-manager running on a separate host (192.168.1.161), which provides SSL termination, Authelia 2FA protection, and proxying to K3s services via Traefik. All external services are exposed under `*.homelab.connortech.me` domains.

## Ansible Inventory & Configuration

- **Inventory**: `hosts` file defines the cluster topology
  - `[master]` group: Single master node (c-m1) running locally
  - `[node]` group: Worker nodes (c-w1 through c-w4) via SSH
  - Each node has `var_hostname`, `var_storage`, and `var_disk` variables
- **Global variables**: `group_vars/all.yml`
  - K3s version: v1.29.0+k3s1
  - Master IP derived from inventory
  - Server args: `--disable servicelb --disable local-storage --node-taint CriticalAddonsOnly=true:NoExecute`
  - Default users: dev, monitor
- **Ansible config**: `ansible.cfg` sets `become = True`, disables host key checking, inventory path, and enables `profile_tasks` callback

## Common Commands

### Cluster Lifecycle
```bash
# Initial cluster setup (run on master node)
ansible-playbook playbooks/cluster_setup.yml

# Clean up cluster (removes K3s from all nodes)
ansible-playbook playbooks/cluster_cleanup.yml

# Set up storage on worker nodes
ansible-playbook playbooks/setup_storage.yml

# Create system users
ansible-playbook playbooks/create_users.yml

# Configure registry mirror (if needed)
ansible-playbook playbooks/configure_registry_mirror.yml
```

### Kubernetes Operations
```bash
# Access kubectl (available on master after setup)
kubectl get nodes
kubectl get pods -A

# Access kubeconfig
# Located at /root/.kube/config on master (c-m1)
# Configured to use master IP (192.168.3.10) rather than localhost
```

### Helm & ArgoCD Operations
```bash
# ArgoCD is installed and accessible at https://192.168.3.201
# Username: admin
# Get password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# List installed Helm releases
helm list -A

# Update application dependencies (legacy charts in argo/)
cd argo/applications && helm dependency update
cd argo/longhorn && helm dependency update
```

## Deployed Infrastructure

**Current Helm Deployments**:
- **ArgoCD** (namespace: `argocd`): GitOps continuous delivery tool
  - LoadBalancer IP: 192.168.3.201
  - All future applications should be deployed through ArgoCD
- **MetalLB** (namespace: `metallb-system`): Bare-metal load balancer
  - IP pool: 192.168.3.200-192.168.3.250
  - L2 advertisement mode

**Helm Repositories Configured**:
- `argo`: https://argoproj.github.io/argo-helm
- `metallb`: https://metallb.github.io/metallb
- `longhorn`: Longhorn charts repository
- `grafana`: https://grafana.github.io/helm-charts

## Architecture

### Ansible Role Structure

**Execution flow** (from `cluster_setup.yml`):
1. **All hosts**: `preflight` → `download` (install K3s binary)
2. **Master only**: `docker` → `k3s/master` (start K3s server, generate node-token, configure kubectl)
3. **Worker nodes**: `k3s/node` (join cluster using master's node-token)
4. **All hosts**: `k3s/all` (post-setup configurations)

**Key roles**:
- `k3s/master`: Installs K3s server, creates kubeconfig at `~/.kube/config`, generates node-token at `/var/lib/rancher/k3s/server/node-token`, creates kubectl/crictl symlinks
- `k3s/node`: Installs K3s agent using master's node-token
- `k3s/software`: Legacy role for deploying MetalLB, Longhorn, and docker-registry (now superseded by Helm/ArgoCD deployments)
- `k3s/registry-mirror`: Configures containerd mirror for docker.io (reduces bandwidth to Docker Hub)
- `storage/diskSetup`: Prepares attached disks on worker nodes (uses `var_disk` from inventory)
- `system`: Creates users defined in `group_vars/all.yml`

**Note**: MetalLB and ArgoCD are now deployed via Helm. Other infrastructure components should follow this pattern.

### Kubernetes Configuration Layout

**k3s-configs/** - Raw Kubernetes YAML manifests organized by component:
- `MetalLB/`: IPAddressPool and L2Advertisement configuration (MetalLB itself deployed via Helm)
- `longhorn/`: Distributed block storage service definitions
- `docker-registry/`: In-cluster container registry (namespace, PVC, service)
- `monitoring/`: Prometheus operator stack, Grafana, node-exporter, kube-state-metrics, ServiceMonitors for Traefik/Longhorn/Kubelet
- `elk/`: Elasticsearch, Logstash, Kibana, Filebeat (optional logging stack)
- `linkerd/`: Service mesh configurations
- `logging/`: Additional logging patches

**Note**: Many of these are legacy manifests. New deployments should use ArgoCD for GitOps-based management.

**argo/** - Helm charts managed by ArgoCD for GitOps deployment:
- `applications/`: Umbrella chart for application deployments managed by the `applications` ArgoCD Application
  - Currently deploys: Grafana 7.2.1 to monitoring namespace
  - Uses Helm dependencies pattern (requirements.yaml)
  - ArgoCD auto-syncs changes from main branch
  - Add new apps by updating requirements.yaml and values.yaml, then commit/push
- `longhorn/`: Longhorn storage deployment chart with custom values (not yet managed by ArgoCD):
  - Default data path: `/var/lib/longhorn`
  - longhornManager nodeSelector requires `storage: "longhorn"` label
  - Priority class: high-priority

**k3s-configs/argocd-apps/** - ArgoCD Application manifests:
- `applications.yaml`: Manages the argo/applications umbrella chart
- Add new Application manifests here for standalone deployments

### Cluster Configuration Details

**Master node specifics**:
- Bind address: 192.168.3.10
- Taints: `CriticalAddonsOnly=true:NoExecute` (prevents workload pods on master)
- ServiceLB disabled (using MetalLB instead)
- Local-storage disabled (using Longhorn instead)
- Cloud controller disabled

**Storage architecture**:
- Worker nodes have external disks attached (var_disk: sdb)
- Longhorn provides distributed persistent storage across nodes with storage label
- Node selector ensures Longhorn manager runs only on labeled nodes

**Monitoring stack**:
- Prometheus scrapes metrics via ServiceMonitors for: Traefik ingress, Longhorn storage, Kubelet, kube-state-metrics
- Node-exporter runs as DaemonSet on all nodes
- Grafana deployed via Helm (v7.2.1) with 1 replica

**Network architecture**:
- K3s cluster network: 192.168.3.0/24
- Master node: 192.168.3.10
- MetalLB IP pool: 192.168.3.200-192.168.3.250 (L2 mode, NOT routable from 192.168.1.x network)
- Traefik LoadBalancer: 192.168.3.200 (also exposed via NodePort 32583 on master)
- External proxy (nginx-proxy-manager): 192.168.1.161 (separate network)
- **Important**: NPM cannot reach MetalLB IPs directly due to L2 ARP limitations across subnets
- **Solution**: NPM proxies to K3s master IP + Traefik NodePort (192.168.3.10:32583)

## Important Patterns

### Adding New Nodes
1. Add entry to `[node]` section in `hosts` with hostname, storage flag, disk variable
2. Ensure SSH access configured for root user
3. Run `ansible-playbook playbooks/cluster_setup.yml --limit=<new-node>`

### Modifying K3s Server Arguments
Edit `extra_server_args` in `group_vars/all.yml`. Common flags:
- `--disable <component>`: Disable built-in components (servicelb, local-storage, traefik)
- `--node-taint <taint>`: Add taints to prevent scheduling
- `--bind-address <ip>`: API server bind address

### Deploying New Applications via ArgoCD
All applications should be deployed through ArgoCD for GitOps workflow using the `argo/applications` Helm chart pattern.

**Current Setup**:
- Grafana is deployed via the `applications` ArgoCD Application
- This Application manages the `argo/applications` Helm chart which uses Helm dependencies
- Grafana runs in the `monitoring` namespace (ClusterIP service on port 80)

**To add a new application**:

1. **Add Helm chart dependency** to `argo/applications/requirements.yaml`:
   ```yaml
   dependencies:
     - name: grafana
       version: 7.2.1
       repository: https://grafana.github.io/helm-charts
     - name: <new-app>
       version: <version>
       repository: <helm-repo-url>
   ```

2. **Configure values** in `argo/applications/values.yaml`:
   ```yaml
   grafana:
     replicas: 1
   <new-app>:
     # custom values here
   ```

3. **Update Helm dependencies**:
   ```bash
   cd argo/applications
   helm dependency update
   ```

4. **Commit and push changes**:
   ```bash
   git add argo/applications/
   git commit -m "Add <new-app> to applications chart"
   git push origin main
   ```

5. **ArgoCD will automatically sync** the changes (automated sync is enabled)
   - Check status: `kubectl get application applications -n argocd`
   - View in UI: https://192.168.3.201

**Alternative: Create standalone ArgoCD Application**:
For applications that don't fit the umbrella chart pattern, create a manifest in `k3s-configs/argocd-apps/`:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app-name>
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/cfkoehler/pi-k3-install.git
    targetRevision: main
    path: <path-to-manifests>
  destination:
    server: https://kubernetes.default.svc
    namespace: <target-namespace>
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```
Then apply: `kubectl apply -f k3s-configs/argocd-apps/<app-name>.yaml`

### Storage Configuration
- Longhorn requires nodes labeled with `storage: "longhorn"` due to nodeSelector in values
- Label nodes: `kubectl label nodes <node-name> storage=longhorn`
- Storage path on nodes: `/var/lib/longhorn`

### Exposing Services Externally via nginx-proxy-manager

**Architecture Overview**:
```
Internet (*.homelab.connortech.me)
    ↓ DNS → 151.241.119.193
nginx-proxy-manager (192.168.1.161)
    ├─ SSL Termination (Let's Encrypt wildcard cert)
    ├─ Authelia 2FA Protection
    └─ Proxy to K3s
         ↓ http://192.168.3.10:32583
    Traefik NodePort
         ├─ Host-based routing (via Host header)
         └─ Services (ArgoCD, Grafana, etc.)
```

**Current External Services**:
- ArgoCD: `https://argocd.homelab.connortech.me`
- Grafana: `https://grafana.homelab.connortech.me`

**To expose a new service externally**:

1. **Create Ingress in K3s** with proper hostname:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: Ingress
   metadata:
     name: myapp
     namespace: myapp
     annotations:
       traefik.ingress.kubernetes.io/router.entrypoints: web
   spec:
     ingressClassName: traefik
     rules:
     - host: myapp.homelab.connortech.me  # MUST use .homelab.connortech.me domain
       http:
         paths:
         - path: /
           pathType: Prefix
           backend:
             service:
               name: myapp
               port:
                 number: 80
   ```

2. **Create NPM Proxy Host** (on 192.168.1.161 via NPM UI):
   - **Domain Names**: `myapp.homelab.connortech.me`
   - **Scheme**: `http`
   - **Forward Hostname/IP**: `192.168.3.10` (K3s master)
   - **Forward Port**: `32583` (Traefik NodePort)
   - **Block Common Exploits**: ✅ ON
   - **Websockets Support**: ✅ ON (if needed for real-time features)
   - **SSL Tab**: Select `*.homelab.connortech.me` certificate, Force SSL ✅ ON

   **Advanced Tab** (required):
   ```nginx
   # Preserve hostname for Traefik routing
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_set_header X-Real-IP $remote_addr;

   # Authelia 2FA Protection
   auth_request /api/verify;
   auth_request_set $target_url $scheme://$http_host$request_uri;
   auth_request_set $user $upstream_http_remote_user;
   auth_request_set $groups $upstream_http_remote_groups;
   auth_request_set $name $upstream_http_remote_name;
   auth_request_set $email $upstream_http_remote_email;
   proxy_set_header Remote-User $user;
   proxy_set_header Remote-Groups $groups;
   proxy_set_header Remote-Name $name;
   proxy_set_header Remote-Email $email;

   error_page 401 =302 https://auth.homelab.connortech.me/?rd=$target_url;

   location /api/verify {
       internal;
       proxy_pass http://authelia:9091/api/verify;
       proxy_set_header Host $host;
       proxy_set_header X-Original-URL $scheme://$http_host$request_uri;
       proxy_set_header X-Forwarded-Method $request_method;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_set_header X-Forwarded-Host $http_host;
       proxy_set_header X-Forwarded-Uri $request_uri;
       proxy_set_header X-Forwarded-For $remote_addr;
       proxy_set_header Content-Length "";
       proxy_set_header Connection "";
       proxy_pass_request_body off;
   }
   ```

3. **Optional: Configure Authelia access rules** (on NPM host):
   Edit `~/homelab/authelia/config/configuration.yml`:
   ```yaml
   access_control:
     rules:
       - domain: myapp.homelab.connortech.me
         policy: two_factor  # or one_factor, or bypass for local network
         subject:
           - "group:admins"  # optional: restrict to specific groups
   ```
   Then restart: `docker compose -f ~/homelab/authelia/docker-compose.yml restart authelia`

4. **No DNS changes needed**: Wildcard `*.homelab.connortech.me` already points to NPM

**Important Notes**:
- All K3s ingress hostnames MUST use `*.homelab.connortech.me` domain
- NPM Advanced tab config is REQUIRED to preserve Host header for Traefik routing
- Authelia protection is optional but recommended for security
- Test internally first: `curl -H "Host: myapp.homelab.connortech.me" http://192.168.3.10:32583`

**For apps in the `argo/applications` umbrella chart**:
Configure ingress in the app's values section:
```yaml
# argo/applications/values.yaml
myapp:
  ingress:
    enabled: true
    ingressClassName: traefik
    hosts:
      - myapp.homelab.connortech.me
    annotations:
      traefik.ingress.kubernetes.io/router.entrypoints: web
```

See `EXTERNAL_ACCESS.md` for complete documentation of the external access architecture.

## Node Configuration Files

`node-configs/etc/hosts` - Custom /etc/hosts entries for cluster nodes (if needed for name resolution)
