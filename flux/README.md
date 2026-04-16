# FluxCD Configuration

This directory contains FluxCD configurations for the K3s homelab cluster. Flux runs alongside ArgoCD to provide a dual GitOps setup for learning and comparison.

## Directory Structure

```
flux/
├── infrastructure/           # Platform-level components
│   ├── sources/             # HelmRepository sources
│   └── metallb/             # MetalLB configuration (IPAddressPool, L2Advertisement)
├── apps/                    # Applications
│   └── development/         # Learning/experimental workloads
│       ├── whoami/          # Simple stateless demo app
│       └── redis/           # Helm-based Redis deployment
└── clusters/
    └── homelab/             # This cluster
        ├── infrastructure.yaml   # Kustomization for infrastructure/
        ├── apps.yaml            # Kustomization for apps/
        └── flux-system/         # Auto-managed by Flux bootstrap
```

## Managed Resources

Flux currently manages:
- **whoami** (namespace: whoami): Simple stateless application for testing
- **Redis** (namespace: redis): Helm-based Redis standalone instance
- **MetalLB configs** (namespace: metallb-system): IPAddressPool and L2Advertisement

## Namespace Separation

- **ArgoCD manages**: `monitoring`, `default`, `argocd`
- **Flux manages**: `whoami`, `redis`, `flux-system`, infrastructure configs

## GitOps Workflow

1. Edit files in `flux/` directory
2. Commit and push to `main` branch
3. Flux detects changes within ~1 minute
4. Resources are automatically reconciled

## Useful Commands

```bash
# Check Flux status
flux check
flux get all

# Watch reconciliation
flux get kustomizations --watch
flux logs --follow

# Check specific resources
flux get sources git
flux get helmreleases -A
kubectl get all -n whoami
kubectl get all -n redis

# Force reconciliation
flux reconcile kustomization flux-system --with-source
flux reconcile kustomization apps
flux reconcile kustomization infrastructure

# Suspend/resume
flux suspend kustomization apps
flux resume kustomization apps
```

## External Access

Applications with ingress are accessible via:
- **whoami**: `https://whoami.homelab.connortech.me` (after NPM configuration)

Access flows through: Internet → nginx-proxy-manager (192.168.1.161) → K3s master (192.168.3.10:32583) → Traefik → Service

## Deployed Applications

### whoami
- **Type**: Stateless demo application
- **Image**: traefik/whoami:v1.10.1
- **Replicas**: 2
- **Resources**: 10m CPU request, 50m limit, 16Mi RAM request, 64Mi limit
- **Ingress**: whoami.homelab.connortech.me

### Redis
- **Type**: Helm chart (Bitnami)
- **Version**: 18.x
- **Architecture**: Standalone (no replication)
- **Storage**: 2Gi PVC via Longhorn
- **Resources**: 100m CPU request, 200m limit, 128Mi RAM request, 256Mi limit
- **Auth**: Enabled (password: changeme123 - for learning only)
- **Metrics**: Enabled

### MetalLB Configuration
- **IPAddressPool**: 192.168.3.200-192.168.3.250
- **L2Advertisement**: Enabled for default pool
- **Note**: MetalLB controller itself is deployed via Helm, Flux only manages the configuration CRDs

## Future Enhancements

- Secret management with Mozilla SOPS or Sealed Secrets
- Image automation for automatic updates
- Multi-environment setup (staging/production)
- Notification system (Slack/Discord)
- Additional infrastructure migrations from k3s-configs/
