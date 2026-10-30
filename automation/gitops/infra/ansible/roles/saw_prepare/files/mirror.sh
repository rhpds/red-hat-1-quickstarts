#!/bin/sh
set -eu
umask 077
export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/runtime
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" /tmp/registry-ca
cp /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt /tmp/registry-ca/ca.crt
registry=image-registry.openshift-image-registry.svc:5000
authfile=/tmp/registry-auth.json
skopeo login --tls-verify=true --cert-dir=/tmp/registry-ca --authfile "$authfile" \
  --username=serviceaccount --password-stdin "$registry" < /var/run/secrets/kubernetes.io/serviceaccount/token >/dev/null
if [ -f /source-auth/.dockerconfigjson ]; then
  skopeo copy --all --preserve-digests --remove-signatures --src-tls-verify=true --dest-tls-verify=true \
    --src-authfile /source-auth/.dockerconfigjson --dest-authfile "$authfile" --dest-cert-dir /tmp/registry-ca \
    "docker://$SAW_SOURCE" "docker://$SAW_DESTINATION"
else
  skopeo copy --all --preserve-digests --remove-signatures --src-tls-verify=true --dest-tls-verify=true \
    --dest-authfile "$authfile" --dest-cert-dir /tmp/registry-ca \
    "docker://$SAW_SOURCE" "docker://$SAW_DESTINATION"
fi
echo 'Mirrored the pinned SAW golden image.'
