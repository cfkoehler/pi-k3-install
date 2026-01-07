# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains Ansible playbooks and Kubernetes configurations for deploying and managing a 5-node K3s cluster on Raspberry Pi hardware (mix of Pi 4s and Pi 3s). The cluster uses ArgoCD for GitOps-based application deployment, MetalLB for load balancing, Longhorn for distributed storage, and includes a monitoring stack (Prometheus/Grafana).

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

**argo/** - Helm charts for GitOps deployment:
- `applications/`: Parent chart for application deployments (currently Grafana via requirements.yaml)
- `longhorn/`: Longhorn storage deployment chart with custom values:
  - Default data path: `/var/lib/longhorn`
  - longhornManager nodeSelector requires `storage: "longhorn"` label
  - Priority class: high-priority

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
All applications should be deployed through ArgoCD for GitOps workflow:

1. **Create ArgoCD Application manifest**:
   ```yaml
   apiVersion: argoproj.io/v1alpha1
   kind: Application
   metadata:
     name: <app-name>
     namespace: argocd
   spec:
     project: default
     source:
       repoURL: <git-repo-url>
       targetRevision: HEAD
       path: <path-to-manifests>
     destination:
       server: https://kubernetes.default.svc
       namespace: <target-namespace>
     syncPolicy:
       automated:
         prune: true
         selfHeal: true
   ```

2. **Alternative: Deploy Helm charts via ArgoCD**:
   - Use ArgoCD's Helm integration by specifying chart details in Application source
   - Or add Helm chart to `argo/` directory and reference in ArgoCD Application

3. **Legacy method (deprecated)**: Manually apply YAML files from `k3s-configs/` using kubectl

### Storage Configuration
- Longhorn requires nodes labeled with `storage: "longhorn"` due to nodeSelector in values
- Label nodes: `kubectl label nodes <node-name> storage=longhorn`
- Storage path on nodes: `/var/lib/longhorn`

## Node Configuration Files

`node-configs/etc/hosts` - Custom /etc/hosts entries for cluster nodes (if needed for name resolution)
