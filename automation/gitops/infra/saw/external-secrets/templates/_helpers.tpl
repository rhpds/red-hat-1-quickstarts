{{/*
Determines if the current cluster is a hub cluster.
First checks if clusterGroup.isHubCluster is explicitly set and uses that value.
If not set, falls back to comparing global.localClusterDomain and global.hubClusterDomain.
If domains are equal or localClusterDomain is not set (defaults to hubClusterDomain), this is a hub cluster.
Usage: {{ include "ocp_eso.ishubcluster" . }}
Returns: "true" or "false" as a string
*/}}
{{- define "ocp_eso.ishubcluster" -}}
{{- if and (hasKey .Values.clusterGroup "isHubCluster") (not (kindIs "invalid" .Values.clusterGroup.isHubCluster)) -}}
  {{- .Values.clusterGroup.isHubCluster | toString -}}
{{- else if $.Values.global.hubClusterDomain -}}
  {{- $localDomain := coalesce $.Values.global.localClusterDomain $.Values.global.hubClusterDomain -}}
  {{- if eq $localDomain $.Values.global.hubClusterDomain -}}
true
  {{- else -}}
false
  {{- end -}}
{{- else -}}
false
{{- end -}}
{{- end }}
