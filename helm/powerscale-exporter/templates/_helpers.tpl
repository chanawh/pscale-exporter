{{/*
Expand the name of the chart.
*/}}
{{- define "powerscale-exporter.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "powerscale-exporter.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "powerscale-exporter.labels" -}}
helm.sh/chart: {{ include "powerscale-exporter.chart" . }}
{{ include "powerscale-exporter.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "powerscale-exporter.selectorLabels" -}}
app.kubernetes.io/name: {{ include "powerscale-exporter.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Mock service labels (the mock is part of this release but a separate component).
*/}}
{{- define "powerscale-exporter.mockLabels" -}}
helm.sh/chart: {{ include "powerscale-exporter.chart" . }}
app.kubernetes.io/name: {{ include "powerscale-exporter.name" . }}-mock
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Chart name and version label.
*/}}
{{- define "powerscale-exporter.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Name of the Secret holding ISILON_USER / ISILON_PASS.
Uses an existing Secret when auth.existingSecret is set.
*/}}
{{- define "powerscale-exporter.secretName" -}}
{{- if .Values.auth.existingSecret }}
{{- .Values.auth.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "powerscale-exporter.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Name of the ConfigMap holding exporter configuration.
*/}}
{{- define "powerscale-exporter.configName" -}}
{{- printf "%s-config" (include "powerscale-exporter.fullname" .) }}
{{- end }}

{{/*
DNS name of the mock OneFS service (only meaningful when mock.enabled).
*/}}
{{- define "powerscale-exporter.mockHost" -}}
{{- printf "%s-mock" (include "powerscale-exporter.fullname" .) }}
{{- end }}
