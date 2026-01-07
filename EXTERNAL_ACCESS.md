# External Access to K3s Services

This document describes the architecture and configuration for accessing K3s cluster services from the internet via nginx-proxy-manager with Authelia 2FA protection.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Network Topology](#network-topology)
- [How It Works](#how-it-works)
- [Current External Services](#current-external-services)
- [Adding New Services](#adding-new-services)
- [Troubleshooting](#troubleshooting)
- [Security Considerations](#security-considerations)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                           Internet                               │
│         *.homelab.connortech.me → 151.241.119.193               │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│          nginx-proxy-manager (192.168.1.161)                    │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  - SSL Termination (Let's Encrypt *.homelab.connortech.me) │
│  │  - Authelia 2FA Protection (http://authelia:9091)     │    │
│  │  - Proxy to: http://192.168.3.10:32583                │    │
│  │  - Preserves Host header for routing                   │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               │ HTTP (internal network)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│               K3s Cluster (192.168.3.0/24)                      │
│                                                                  │
│  ┌─────────────────────────────────────────────┐               │
│  │   Traefik Ingress (NodePort 32583)          │               │
│  │   - Host-based routing                       │               │
│  │   - Routes based on Host header              │               │
│  └──────────┬───────────────────────────────────┘               │
│             │                                                    │
│    ┌────────┴────────┬──────────────┬──────────────┐           │
│    ▼                 ▼              ▼              ▼           │
│  ArgoCD          Grafana         App1           App2          │
│  (80)            (80)            (80)           (80)          │
└─────────────────────────────────────────────────────────────────┘
```

**Key Components**:
- **nginx-proxy-manager (NPM)**: External reverse proxy on 192.168.1.161
- **Authelia**: 2FA authentication provider running alongside NPM
- **K3s Cluster**: Kubernetes cluster on 192.168.3.0/24 network
- **Traefik**: K3s ingress controller with NodePort access

---

## Network Topology

### Networks

| Network Segment | Description | Hosts |
|-----------------|-------------|-------|
| **192.168.1.0/24** | External services network | NPM (192.168.1.161) |
| **192.168.3.0/24** | K3s cluster network | Master (192.168.3.10), Workers, MetalLB IPs |
| **Internet** | Public internet | NPM public IP (151.241.119.193) |

### Why NodePort Instead of LoadBalancer?

**Problem**: MetalLB LoadBalancer IPs (192.168.3.200-250) use Layer 2 ARP announcements, which don't work across different subnets (192.168.1.x cannot reach 192.168.3.200).

**Solution**: Traefik is exposed via:
1. **LoadBalancer** at 192.168.3.200 (for internal/same-subnet access)
2. **NodePort 32583** on all K3s nodes (for cross-subnet access)

NPM proxies to the K3s master IP + NodePort: `192.168.3.10:32583`

### DNS Configuration

**Public DNS** (Route53 hosted zone: `connortech.me`):
- `homelab.connortech.me` → 151.241.119.193
- `*.homelab.connortech.me` → 151.241.119.193

**All services use subdomains**:
- `argocd.homelab.connortech.me`
- `grafana.homelab.connortech.me`
- `myapp.homelab.connortech.me`

---

## How It Works

### Request Flow

**Example**: User accesses `https://argocd.homelab.connortech.me`

1. **DNS Resolution**:
   - DNS query resolves to 151.241.119.193 (NPM public IP)

2. **nginx-proxy-manager**:
   - Receives HTTPS request
   - Terminates SSL using Let's Encrypt wildcard certificate
   - Checks Authelia for authentication:
     ```
     GET http://authelia:9091/api/verify
     Headers:
       Host: argocd.homelab.connortech.me
       X-Original-URL: https://argocd.homelab.connortech.me/
     ```

3. **Authelia Authentication**:
   - **If no session**: Returns 401 → NPM redirects to `https://auth.homelab.connortech.me`
   - **User logs in**: Username/password + 2FA TOTP code
   - **Session created**: Cookie set for `*.homelab.connortech.me`
   - **Redirects back**: User sent to original URL
   - **If valid session**: Returns 200 + user headers

4. **Proxy to K3s**:
   - NPM forwards request to `http://192.168.3.10:32583`
   - Preserves `Host: argocd.homelab.connortech.me` header
   - Adds user info headers (Remote-User, Remote-Groups, etc.)

5. **Traefik Routing**:
   - Receives request on NodePort 32583
   - Reads `Host` header: `argocd.homelab.connortech.me`
   - Matches ingress rule for ArgoCD
   - Forwards to ArgoCD service on port 80

6. **Service Response**:
   - ArgoCD processes request
   - Response flows back through Traefik → NPM → User

### Session Persistence

- Authelia session cookie is shared across `*.homelab.connortech.me`
- Once authenticated, user can access all K3s services without re-login
- Session expires after 1 hour of activity (configurable in Authelia)

---

## Current External Services

| Service | External URL | K3s Namespace | Internal Service | Port |
|---------|-------------|---------------|------------------|------|
| **ArgoCD** | https://argocd.homelab.connortech.me | argocd | argocd-server | 80 |
| **Grafana** | https://grafana.homelab.connortech.me | monitoring | applications-grafana | 80 |

### Access Information

**ArgoCD**:
- URL: https://argocd.homelab.connortech.me
- Username: `admin`
- Password: `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`
- Protected by: Authelia 2FA

**Grafana**:
- URL: https://grafana.homelab.connortech.me
- Credentials: Default Grafana login
- Protected by: Authelia 2FA

**Authelia**:
- URL: https://auth.homelab.connortech.me
- Login portal for all services
- Configured on NPM host (192.168.1.161)

---

## Adding New Services

Follow these steps to expose a new K3s service externally with Authelia 2FA protection.

### Step 1: Create Kubernetes Ingress

Create an ingress resource for your service:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-ingress
  namespace: myapp
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web
spec:
  ingressClassName: traefik
  rules:
  - host: myapp.homelab.connortech.me  # Must use .homelab.connortech.me domain
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: myapp-service
            port:
              number: 80
```

**Apply the ingress**:
```bash
kubectl apply -f myapp-ingress.yaml
```

**Verify ingress created**:
```bash
kubectl get ingress -n myapp
```

**Test internally** (from K3s master):
```bash
curl -H "Host: myapp.homelab.connortech.me" http://192.168.3.10:32583
```

### Step 2: Create nginx-proxy-manager Proxy Host

**On NPM host** (192.168.1.161), access NPM UI at `http://192.168.1.161:81`

**Create new proxy host**:
1. Navigate to: **Hosts → Proxy Hosts → Add Proxy Host**

2. **Details Tab**:
   - **Domain Names**: `myapp.homelab.connortech.me`
   - **Scheme**: `http`
   - **Forward Hostname/IP**: `192.168.3.10`
   - **Forward Port**: `32583`
   - **Cache Assets**: OFF
   - **Block Common Exploits**: ✅ ON
   - **Websockets Support**: ✅ ON (if app uses websockets)

3. **SSL Tab**:
   - **SSL Certificate**: Select `*.homelab.connortech.me` (existing wildcard)
   - **Force SSL**: ✅ ON
   - **HTTP/2 Support**: ✅ ON
   - **HSTS Enabled**: ✅ ON
   - **HSTS Subdomains**: OFF

4. **Advanced Tab** - Copy this entire block:
   ```nginx
   # Preserve hostname for Traefik routing
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_set_header X-Real-IP $remote_addr;
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

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

5. **Save** the proxy host

### Step 3: Configure Authelia Access Rules (Optional)

**On NPM host**, edit Authelia config:
```bash
nano ~/homelab/authelia/config/configuration.yml
```

**Add access rule** in the `access_control.rules` section:
```yaml
access_control:
  default_policy: deny
  rules:
    # Existing rules...

    # New service
    - domain: myapp.homelab.connortech.me
      policy: two_factor  # Options: bypass, one_factor, two_factor
      subject:
        - "group:admins"  # Optional: restrict to specific groups
        - "user:connor"   # Optional: restrict to specific users
```

**Policy Options**:
- `bypass`: No authentication required
- `one_factor`: Username/password only
- `two_factor`: Username/password + TOTP 2FA

**Restart Authelia**:
```bash
cd ~/homelab
docker compose -f authelia/docker-compose.yml restart authelia
```

### Step 4: Test Access

**From external network** (mobile data or different location):
1. Visit: `https://myapp.homelab.connortech.me`
2. Should redirect to Authelia login (if no session)
3. Login with credentials + 2FA
4. Should redirect back to your app
5. Subsequent visits should use existing session

**From K3s cluster**:
```bash
# Test ingress routing
curl -H "Host: myapp.homelab.connortech.me" http://192.168.3.10:32583
```

**From NPM host**:
```bash
# Test connectivity
curl -H "Host: myapp.homelab.connortech.me" http://192.168.3.10:32583

# Test with authentication (will fail without session)
curl -I https://myapp.homelab.connortech.me
```

---

## For Apps Deployed via ArgoCD

If deploying apps through the `argo/applications` umbrella chart, configure ingress in values:

### Edit `argo/applications/values.yaml`:

```yaml
myapp:
  replicas: 1
  ingress:
    enabled: true
    ingressClassName: traefik
    hosts:
      - myapp.homelab.connortech.me
    annotations:
      traefik.ingress.kubernetes.io/router.entrypoints: web
```

### Update Helm dependencies:
```bash
cd argo/applications
helm dependency update
```

### Commit and push:
```bash
git add argo/applications/values.yaml
git commit -m "Add ingress for myapp"
git push origin main
```

ArgoCD will automatically sync and create the ingress. Then proceed to **Step 2** above to create the NPM proxy host.

---

## Troubleshooting

### Service Not Accessible Externally

**Check ingress exists**:
```bash
kubectl get ingress -A | grep myapp
```

**Verify ingress configuration**:
```bash
kubectl get ingress myapp-ingress -n myapp -o yaml
```

**Check hostname matches**:
- Ingress `host` field must be `*.homelab.connortech.me`
- NPM proxy host domain must match exactly

**Test Traefik routing**:
```bash
# From K3s master
curl -H "Host: myapp.homelab.connortech.me" http://localhost:32583 -v
```

**Check Traefik logs**:
```bash
kubectl logs -n kube-system -l app.kubernetes.io/name=traefik --tail=100
```

### 502 Bad Gateway from NPM

**NPM cannot reach K3s**:
```bash
# From NPM host (192.168.1.161)
ping 192.168.3.10
curl http://192.168.3.10:32583 -v
```

**Service not running in K3s**:
```bash
kubectl get pods -n myapp
kubectl logs -n myapp <pod-name>
```

**Traefik NodePort not listening**:
```bash
kubectl get svc traefik -n kube-system
# Should show NodePort 32583
```

### Authelia Redirect Loop

**Check Authelia is running**:
```bash
# On NPM host
docker ps | grep authelia
docker compose -f ~/homelab/authelia/docker-compose.yml logs authelia
```

**Verify NPM can reach Authelia**:
```bash
# From NPM container
docker exec nginx-proxy-manager curl http://authelia:9091/api/healthcheck
```

**Check Authelia access rules**:
```bash
# On NPM host
cat ~/homelab/authelia/config/configuration.yml | grep -A 20 access_control
```

### SSL Certificate Errors

**Wildcard cert covers domain**:
- `*.homelab.connortech.me` covers all subdomains
- Does NOT cover `homelab.connortech.me` itself (need explicit cert)

**Check NPM certificate**:
- NPM UI → SSL Certificates → Verify `*.homelab.connortech.me` is active
- Check expiration date

**Force cert renewal**:
- NPM UI → SSL Certificates → Edit → Save (triggers renewal check)

### Service Works Internally But Not Externally

**Check NPM proxy host configuration**:
- Verify "Host" header preservation in Advanced tab
- Ensure Forward IP is `192.168.3.10` not `192.168.3.200`

**Check firewall rules**:
```bash
# On K3s master
sudo iptables -L -n | grep 32583
```

**Verify DNS resolution**:
```bash
nslookup myapp.homelab.connortech.me 8.8.8.8
# Should return 151.241.119.193
```

### Authelia Not Requiring 2FA

**Check access policy**:
- Policy might be set to `one_factor` or `bypass`
- Check `access_control.rules` in Authelia config

**Check domain matching**:
- Domain in access rule must match exactly
- Wildcards: `*.homelab.connortech.me` or specific `myapp.homelab.connortech.me`

**Restart Authelia after config changes**:
```bash
docker compose -f ~/homelab/authelia/docker-compose.yml restart authelia
```

---

## Security Considerations

### Network Segmentation

- **K3s cluster** (192.168.3.0/24) is isolated from external services network
- **NPM** (192.168.1.161) acts as DMZ/perimeter security
- No direct internet access to K3s nodes
- All external traffic flows through NPM → Authelia → Traefik

### Authentication & Authorization

**Authelia provides**:
- Username/password authentication (Argon2id hashing)
- TOTP-based 2FA (Google Authenticator, Authy, etc.)
- Session management with Redis backend
- Per-domain access policies
- User/group-based restrictions

**Best practices**:
- Always use `two_factor` policy for sensitive services (ArgoCD, admin panels)
- Use `one_factor` for less sensitive services
- Only use `bypass` for truly public services or local network access
- Configure network-based rules for local subnet bypass if desired

### SSL/TLS

- **Let's Encrypt wildcard certificate** for `*.homelab.connortech.me`
- **SSL termination at NPM** - all external traffic is HTTPS
- **Internal traffic is HTTP** (K3s cluster is trusted network)
- **HSTS enabled** on all NPM proxy hosts (forces HTTPS)

**Certificate rotation**:
- NPM automatically renews certificates 30 days before expiration
- Uses DNS-01 challenge via Route53 (requires AWS credentials)

### Secrets Management

**NPM host**:
- Authelia secrets stored in `~/homelab/authelia/config/secrets/`
- Permissions: `chmod 600` on all secret files
- AWS credentials for Route53 stored in NPM config (encrypted)

**K3s cluster**:
- ArgoCD admin password in Secret: `argocd-initial-admin-secret`
- Rotate default passwords after initial setup

### Monitoring & Logging

**NPM logs**:
```bash
docker compose -f ~/homelab/nginx-proxy-manager/docker-compose.yml logs -f
```

**Authelia logs**:
```bash
docker compose -f ~/homelab/authelia/docker-compose.yml logs -f authelia
```

**K3s/Traefik logs**:
```bash
kubectl logs -n kube-system -l app.kubernetes.io/name=traefik -f
```

**Failed authentication attempts**:
- Authelia logs all failed login attempts
- Implements rate limiting (5 attempts per 2 minutes, 5 minute ban)

### Network Policies (Future Enhancement)

Consider implementing Kubernetes NetworkPolicies to:
- Restrict pod-to-pod communication
- Limit egress traffic from pods
- Enforce namespace isolation

---

## Advanced Configuration

### Custom Traefik Middlewares

For advanced routing, you can create Traefik middlewares:

```yaml
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: rate-limit
  namespace: myapp
spec:
  rateLimit:
    average: 100
    burst: 50
```

Apply to ingress:
```yaml
annotations:
  traefik.ingress.kubernetes.io/router.middlewares: myapp-rate-limit@kubernetescrd
```

### Health Checks

**Traefik health check**:
```bash
curl http://192.168.3.10:32583/ping
```

**Authelia health check**:
```bash
curl http://192.168.1.161:9091/api/healthcheck
```

### Backup & Disaster Recovery

**NPM backup** (includes all proxy hosts and SSL certs):
```bash
# On NPM host
tar -czf npm-backup-$(date +%Y%m%d).tar.gz ~/homelab/nginx-proxy-manager/data
```

**Authelia backup** (includes user database and sessions):
```bash
# On NPM host
tar -czf authelia-backup-$(date +%Y%m%d).tar.gz ~/homelab/authelia/config
```

**K3s ingress backup**:
```bash
kubectl get ingress -A -o yaml > ingress-backup.yaml
```

---

## References

- [nginx-proxy-manager Documentation](https://nginxproxymanager.com/)
- [Authelia Documentation](https://www.authelia.com/)
- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [K3s Documentation](https://docs.k3s.io/)
- [MetalLB Documentation](https://metallb.universe.tf/)

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-01-07 | Initial documentation - NPM + K3s + Authelia integration | Connor |
| 2026-01-07 | Added ArgoCD and Grafana ingresses | Connor |

---

**Last Updated**: 2026-01-07
**Maintained By**: Connor
**Related Documentation**: See `CLAUDE.md` for K3s cluster architecture
