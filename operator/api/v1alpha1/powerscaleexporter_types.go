package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// IsilonConnection describes how to reach a single OneFS cluster.
// Used when TargetClusters is empty (single-cluster mode, the exporter's
// v1 behavior).
type IsilonConnection struct {
	// Host is the OneFS cluster hostname or IP (mirrors ISILON_HOST).
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	Host string `json:"host"`

	// Port is the OneFS API port (mirrors ISILON_PORT).
	// +kubebuilder:default=8080
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port,omitempty"`
}

// SecretKeyRef points at a single key inside a Secret in the same namespace
// as the PowerScaleExporter resource.
type SecretKeyRef struct {
	// Name of the Secret.
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	Name string `json:"name"`

	// Key inside the Secret holding the username.
	// +kubebuilder:default="ISILON_USER"
	UserKey string `json:"userKey,omitempty"`

	// Key inside the Secret holding the password.
	// +kubebuilder:default="ISILON_PASS"
	PasswordKey string `json:"passwordKey,omitempty"`
}

// TargetCluster describes one OneFS cluster in multi-cluster mode. It mirrors
// the exporter's ISILON_TARGETS entries ({name, host, port, user, password}):
// non-secret fields come from the CR, credentials are always resolved from
// Secrets — never inlined in the CR.
type TargetCluster struct {
	// Name is the logical cluster name (becomes the cluster_name label and
	// the ISILON_TARGETS entry name).
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	Name string `json:"name"`

	// Host is the OneFS cluster hostname or IP.
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	Host string `json:"host"`

	// Port is the OneFS API port.
	// +kubebuilder:default=8080
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port,omitempty"`

	// AuthSecretRef points at the Secret holding this cluster's username
	// and password.
	// +kubebuilder:validation:Required
	AuthSecretRef SecretKeyRef `json:"authSecretRef"`
}

// ServiceMonitorSpec toggles Prometheus Operator ServiceMonitor management.
type ServiceMonitorSpec struct {
	// Enabled creates a ServiceMonitor scraping the exporter's /metrics/.
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`
}

// PowerScaleExporterSpec defines the desired state of a PowerScaleExporter.
type PowerScaleExporterSpec struct {
	// Isilon is the single-cluster connection. Ignored when TargetClusters
	// is non-empty (multi-cluster mode), mirroring the Helm chart's
	// behavior where isilon.* is ignored once clusters: is set.
	// +kubebuilder:validation:Required
	Isilon IsilonConnection `json:"isilon"`

	// AuthSecretRef points at the Secret holding ISILON_USER/ISILON_PASS for
	// single-cluster mode. Credentials are never inlined in the CR.
	// +kubebuilder:validation:Required
	AuthSecretRef SecretKeyRef `json:"authSecretRef"`

	// TargetClusters enables multi-cluster mode. When non-empty, the
	// controller renders a targets.json Secret (ISILON_TARGETS_FILE) from
	// these entries and ignores Isilon/AuthSecretRef, exactly like the
	// exporter's ISILON_TARGETS semantics.
	// +optional
	// +kubebuilder:validation:MinItems=1
	TargetClusters []TargetCluster `json:"targetClusters,omitempty"`

	// Replicas is the exporter Deployment replica count.
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=1
	Replicas *int32 `json:"replicas,omitempty"`

	// Image is the exporter container image.
	// +kubebuilder:default="awhchan/powerscale-exporter:latest"
	Image string `json:"image,omitempty"`

	// ServiceMonitor toggles management of a Prometheus Operator
	// ServiceMonitor for the exporter Service.
	// +optional
	ServiceMonitor ServiceMonitorSpec `json:"serviceMonitor,omitempty"`

	// Resources for the exporter container.
	// +optional
	Resources corev1.ResourceRequirements `json:"resources,omitempty"`
}

// PowerScaleExporterStatus defines the observed state.
type PowerScaleExporterStatus struct {
	// Conditions report Available/Degraded state of the managed exporter.
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// ObservedGeneration tracks which spec generation was last reconciled.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Available",type=string,JSONPath=`.status.conditions[?(@.type=="Available")].status`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// PowerScaleExporter manages a PowerScale (OneFS) Prometheus exporter
// Deployment, Service, and optional ServiceMonitor from a single CR.
type PowerScaleExporter struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   PowerScaleExporterSpec   `json:"spec,omitempty"`
	Status PowerScaleExporterStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// PowerScaleExporterList contains a list of PowerScaleExporter.
type PowerScaleExporterList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []PowerScaleExporter `json:"items"`
}
