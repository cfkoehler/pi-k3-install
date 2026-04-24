# FluxCD Configuration

This directory contains FluxCD configurations for the K3s homelab cluster. Flux runs alongside ArgoCD in a dual GitOps setup — Flux manages infrastructure and developer tooling, ArgoCD manages observability and dashboard applications.

## Directory Structure

```
flux/
├── infrastructure/               # Platform-level components
│   ├── sources/
│   │   ├── bitnami.yaml          # HelmRepository: Bitnami charts
│   │   └── sonarqube.yaml        # HelmRepository: SonarSource charts
│   └── metallb/                  # MetalLB configuration (IPAddressPool, L2Advertisement)
├── apps/                         # Applications
│   ├── development/              # Experimental/utility workloads
│   │   ├── whoami/               # Simple stateless demo app
│   │   └── redis/                # Helm-based Redis deployment
│   └── sonarqube/                # SonarQube code quality platform
│       ├── namespace.yaml
│       ├── storage.yaml          # StorageClass + pre-bound PVs (local hostPath on c-w1)
│       ├── postgres.yaml         # PostgreSQL 15 Deployment + Services + Secret
│       ├── helmrelease.yaml      # SonarQube HelmRelease (SonarSource chart)
│       └── kustomization.yaml
└── clusters/
    └── homelab/                  # This cluster
        ├── infrastructure.yaml   # Kustomization for infrastructure/
        ├── apps.yaml             # Kustomization for apps/
        └── flux-system/          # Auto-managed by Flux bootstrap
```

## Managed Resources

| App | Namespace | Type | Notes |
|-----|-----------|------|-------|
| MetalLB config | metallb-system | Kustomization | IPAddressPool + L2Advertisement CRDs only (controller via Helm) |
| whoami | whoami | Kustomization | Stateless demo for testing ingress |
| Redis | redis | HelmRelease | Bitnami, standalone, no persistence |
| SonarQube | sonarqube | HelmRelease + Kustomization | Code quality platform, pinned to c-w1 with local PVs |

## Namespace Separation

- **Flux manages**: `whoami`, `redis`, `sonarqube`, `flux-system`, infrastructure CRDs
- **ArgoCD manages**: `monitoring` (Grafana, Metricbeat), `default` (Glance dashboard), `argocd`

## GitOps Workflow

1. Edit files in `flux/` directory
2. Commit and push to `main` branch
3. Flux detects changes within ~10 minutes (or force with commands below)
4. Resources are automatically reconciled and drift is corrected

## Useful Commands

```bash
# Check Flux status
flux check
flux get all -A

# Watch reconciliation
flux get kustomizations --watch
flux logs --follow

# Force reconciliation
flux reconcile kustomization infrastructure --with-source
flux reconcile kustomization apps --with-source
flux reconcile helmrelease sonarqube -n sonarqube

# Check HelmReleases
flux get helmreleases -A

# Suspend/resume
flux suspend kustomization apps
flux resume kustomization apps
```

## SonarQube

SonarQube Community Edition for static analysis and trend tracking of Java projects.

- **URL**: `http://sonarqube.homelab.connortech.me` (internal) / `https://sonarqube.homelab.connortech.me` (via NPM)
- **Version**: 24.12.0 (SonarQube 10.8.1 chart)
- **Database**: Standalone `postgres:15` Deployment (not the bundled Bitnami subchart)
- **Storage**: Local hostPath PVs on `c-w1`
  - SonarQube data: 10Gi at `/opt/sonarqube/data`
  - PostgreSQL data: 20Gi at `/opt/sonarqube/postgresql`
- **Pinned to**: `c-w1` via `nodeSelector: kubernetes.io/hostname: c-w1`
- **Default login**: `admin` / `admin` (forced change on first login)

### Storage Architecture Note

The SonarQube chart mounts the PVC via subPath for each of `data`, `temp`, `logs`, and `extensions`. The chart's built-in `init-fs` container only chowns `data`, `temp`, and `logs` — the `extensions` subPath directory is created by Kubernetes as root-owned and is not fixed by the chart. A `fix-extensions-perms` extra init container runs as root to chown `extensions` to uid 1000 before the main container starts.

### PostgreSQL Note

The SonarQube 10.8.1 chart bundles `bitnami/postgresql:10.15.0` which pins to PostgreSQL 11. That image has been removed from Docker Hub and was never built for ARM64. The bundled subchart is disabled (`postgresql.enabled: false`) and replaced with an explicit `postgres:15` Deployment. Two alias services are maintained:
- `sonarqube-db` — the actual Deployment selector
- `sonarqube-postgresql` — alias required by the chart's hardcoded `wait-for-db` init container

## External Access

Applications with ingress are accessible via:
- **whoami**: `https://whoami.homelab.connortech.me`
- **SonarQube**: `https://sonarqube.homelab.connortech.me` (requires NPM proxy host — see root README)

Access flows: Internet → nginx-proxy-manager (192.168.1.161) → K3s master (192.168.3.10:32583) → Traefik → Service

## Redis

Bitnami Redis in standalone mode. Auth enabled with a placeholder password — for learning/testing only, not used in production workloads.

- **Architecture**: Standalone (no replication, no persistence)
- **Resources**: 100m–200m CPU / 128–256Mi RAM
