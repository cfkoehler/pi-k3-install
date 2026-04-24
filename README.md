# pi-k3-install

Ansible playbooks and Kubernetes configurations for a 5-node K3s cluster running on Raspberry Pi hardware. The cluster uses a dual GitOps setup (Flux + ArgoCD) for application deployment.

## Hardware

| Node | Role | Model |
|------|------|-------|
| c-m1 | Control plane | Raspberry Pi 4 |
| c-w1 | Worker | Raspberry Pi 4 |
| c-w2 | Worker | Raspberry Pi 4 |
| c-w3 | Worker | Raspberry Pi 3 |
| c-w4 | Worker | Raspberry Pi 3 |

All nodes run ARM64. Worker nodes have external disks attached for storage.

## Network Layout

```
Internet (*.homelab.connortech.me)
    ↓ DNS → 151.241.119.193
nginx-proxy-manager (192.168.1.161)     ← SSL termination, Authelia 2FA
    ↓ http://192.168.3.10:32583
Traefik NodePort (on c-m1)
    ↓ host-based routing
K3s services (192.168.3.0/24)
```

- **Master**: 192.168.3.10
- **MetalLB pool**: 192.168.3.200–192.168.3.250 (L2 mode)
- **Traefik LoadBalancer**: 192.168.3.200 / NodePort 32583
- **External domain**: `*.homelab.connortech.me`

## Cluster Setup

The cluster is bootstrapped with Ansible. All playbooks live in `playbooks/` and use roles from `roles/`.

### Prerequisites

- SSH access as root to all nodes
- Python on all nodes
- Ansible installed on the machine running playbooks

### Initial Setup

```bash
# Bootstrap the full cluster (master + all workers)
ansible-playbook playbooks/cluster_setup.yml

# Prepare storage disks on worker nodes
ansible-playbook playbooks/setup_storage.yml

# Create system users (dev, monitor)
ansible-playbook playbooks/create_users.yml
```

### Adding a New Node

1. Add entry to `[node]` section in `hosts` with `var_hostname`, `var_storage`, `var_disk`
2. Run: `ansible-playbook playbooks/cluster_setup.yml --limit=<new-node>`

### Cluster Teardown

```bash
ansible-playbook playbooks/cluster_cleanup.yml
```

## Ansible Structure

```
hosts                    # Inventory: [master] c-m1, [node] c-w1–c-w4
group_vars/all.yml       # K3s version, server args, default users
ansible.cfg              # become=True, profile_tasks callback
playbooks/               # Top-level playbooks
roles/
├── preflight/           # Pre-checks and OS prep
├── download/            # K3s binary installation
├── k3s/
│   ├── master/          # K3s server, kubeconfig, node-token
│   ├── node/            # K3s agent join
│   └── all/             # Post-setup (both master and workers)
├── storage/diskSetup/   # Format and mount external disks
└── system/              # Create users
```

**K3s server args** (from `group_vars/all.yml`):
- `--disable servicelb` — MetalLB used instead
- `--disable local-storage` — Longhorn used instead (when deployed)
- `--node-taint CriticalAddonsOnly=true:NoExecute` — no workload pods on master
- `--bind-address 192.168.3.10`

## What's Running

### GitOps: Flux

Flux manages infrastructure components and developer tooling. See `flux/README.md` for full details.

| App | Namespace | Access |
|-----|-----------|--------|
| MetalLB config (CRDs) | metallb-system | — |
| whoami (demo) | whoami | whoami.homelab.connortech.me |
| Redis | redis | Internal only |
| **SonarQube** | sonarqube | sonarqube.homelab.connortech.me |

### GitOps: ArgoCD

ArgoCD manages the observability and dashboard stack via Helm umbrella charts in `argo/`.

| App | Namespace | Access |
|-----|-----------|--------|
| ArgoCD | argocd | argocd.homelab.connortech.me |
| Grafana | monitoring | grafana.homelab.connortech.me |
| Metricbeat | monitoring | → Elasticsearch at 192.168.3.100 |
| Glance dashboard | default | glance.homelab.connortech.me |

**ArgoCD UI**: https://192.168.3.201  
Password: `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`

### Infrastructure (Helm, pre-GitOps)

| Component | Namespace | Notes |
|-----------|-----------|-------|
| MetalLB | metallb-system | Bare-metal load balancer, L2 mode |
| Traefik | kube-system | Built into K3s, LoadBalancer at 192.168.3.200 |

### Monitoring (raw manifests in `k3s-configs/monitoring/`)

| Component | Namespace |
|-----------|-----------|
| Prometheus | monitoring |
| Node Exporter | monitoring (DaemonSet) |
| kube-state-metrics | monitoring |

### Storage

Longhorn was previously deployed for distributed block storage but is not currently active. Storage-dependent workloads (SonarQube) use local hostPath PVs pinned to `c-w1`.

When Longhorn is re-deployed:
```bash
# Label nodes for Longhorn
kubectl label nodes c-w1 c-w2 c-w3 c-w4 storage=longhorn
```
The Longhorn chart values are in `argo/longhorn/`.

## SonarQube

Code quality and static analysis for Java projects. Stores analysis history in PostgreSQL for trend tracking over time.

- **URL**: `https://sonarqube.homelab.connortech.me`
- **Managed by**: Flux (`flux/apps/sonarqube/`)
- **Pinned to**: `c-w1` (local PVs at `/opt/sonarqube/`)
- **Default login**: `admin` / `admin` (forced change on first login)

To run a Maven project scan:
```bash
mvn sonar:sonar \
  -Dsonar.host.url=https://sonarqube.homelab.connortech.me \
  -Dsonar.login=<token>
```

## Exposing a New Service Externally

1. Add a Traefik `Ingress` with host `<name>.homelab.connortech.me` and `ingressClassName: traefik`
2. In NPM (192.168.1.161): create a proxy host forwarding to `192.168.3.10:32583` with the Advanced config from `k3s-configs/npm-advanced-config-snippet.conf`
3. Optionally add an Authelia access rule on the NPM host

See `EXTERNAL_ACCESS.md` for the full architecture and step-by-step instructions.

## Repository Layout

```
hosts                        # Ansible inventory
group_vars/all.yml           # Cluster-wide variables
ansible.cfg
playbooks/                   # Ansible playbooks
roles/                       # Ansible roles
flux/                        # Flux GitOps (infrastructure + dev tooling)
argo/                        # ArgoCD Helm charts (observability + dashboards)
k3s-configs/                 # Raw Kubernetes manifests
├── argocd-apps/             # ArgoCD Application manifests
├── MetalLB/                 # MetalLB CRD configs (superseded by flux/infrastructure)
├── monitoring/              # Prometheus stack manifests
├── longhorn/                # Longhorn service definitions
├── docker-registry/         # In-cluster registry
├── elk/                     # ELK stack (optional)
└── linkerd/                 # Service mesh (experimental)
node-configs/                # Per-node config files
```
