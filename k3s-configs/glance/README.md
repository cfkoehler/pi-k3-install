# Glance Secrets Management

## Overview

The Glance application requires a Kubernetes Secret containing the Pi-hole admin password for the DNS statistics widget. This secret is **NOT** stored in the git repository for security reasons.

## Secret File

The secret file `glance-secrets.yaml` is excluded from git via `.gitignore` and must be managed manually.

## Creating the Secret

1. **Create the secret file** (if it doesn't exist):
   ```bash
   cat > k3s-configs/glance/glance-secrets.yaml <<EOF
   apiVersion: v1
   kind: Secret
   metadata:
     name: glance-secrets
     namespace: default
   type: Opaque
   stringData:
     PIHOLE_PASSWORD: YOUR_PIHOLE_PASSWORD_HERE
   EOF
   ```

2. **Replace `YOUR_PIHOLE_PASSWORD_HERE`** with your actual Pi-hole admin password.

3. **Apply the secret** to your cluster:
   ```bash
   kubectl apply -f k3s-configs/glance/glance-secrets.yaml
   ```

## Updating the Secret

If you need to update the password:

1. Edit the `glance-secrets.yaml` file locally
2. Apply the changes:
   ```bash
   kubectl apply -f k3s-configs/glance/glance-secrets.yaml
   ```
3. Restart the Glance deployment to pick up the new password:
   ```bash
   kubectl rollout restart deployment glance -n default
   ```

## Security Notes

- **Never commit** this secret file to git
- The secret is already applied to your cluster
- Keep a secure backup of this file outside of the git repository
- Consider using a password manager to store the Pi-hole password

## Future: Sealed Secrets

This project may implement [Bitnami Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) in the future for encrypted secrets in git. However, there are currently compatibility issues with ARM64 architecture on Raspberry Pi.

## Environment Variables

The Glance deployment uses the `PIHOLE_PASSWORD` environment variable from this secret:

```yaml
# In argo/glance/values.yaml
variables:
  secret:
    existingSecret:
      - envName: PIHOLE_PASSWORD
        name: glance-secrets
        key: PIHOLE_PASSWORD
```

The Glance configuration then references it as `${PIHOLE_PASSWORD}` in the `glance.yml` config.
