// Package controller implements the PowerScaleExporter reconciler.
//
// The reconciler owns, per PowerScaleExporter CR:
//   - a Deployment running the exporter (env from Secrets, never inline creds)
//   - a ClusterIP Service fronting the exporter pods
//   - a targets.json Secret in multi-cluster mode (ISILON_TARGETS_FILE)
//   - a Prometheus Operator ServiceMonitor when spec.serviceMonitor.enabled
//
// All owned resources carry a controller OwnerReference so a real cluster's
// garbage collector cascades deletion. Status reports Available/Degraded.
package controller

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	monitoringv1 "github.com/prometheus-operator/prometheus-operator/pkg/apis/monitoring/v1"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	monitoringv1alpha1 "github.com/chanawh/pscale-exporter/operator/api/v1alpha1"
)

const (
	defaultImage        = "awhchan/powerscale-exporter:latest"
	defaultPort         = int32(8080)
	exporterPort        = int32(8000)
	exporterPortName    = "http"
	targetsMountPath    = "/etc/powerscale/targets.json"
	targetsSecretSuffix = "-targets"
	requeueOnConfigErr  = 30 * time.Second
)

// PowerScaleExporterReconciler reconciles PowerScaleExporter objects.
//
// +kubebuilder:rbac:groups=monitoring.chanawh.io,resources=powerscaleexporters,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=monitoring.chanawh.io,resources=powerscaleexporters/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=monitoring.chanawh.io,resources=powerscaleexporters/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=services;secrets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=monitoring.coreos.com,resources=servicemonitors,verbs=get;list;watch;create;update;patch;delete
type PowerScaleExporterReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// Reconcile implements reconcile.Reconciler.
func (r *PowerScaleExporterReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	var cr monitoringv1alpha1.PowerScaleExporter
	if err := r.Get(ctx, req.NamespacedName, &cr); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	spec := defaultedSpec(cr.Spec)

	// Multi-cluster mode: resolve every cluster's credentials from Secrets
	// and render the targets.json Secret the exporter consumes via
	// ISILON_TARGETS_FILE. Any missing/empty credential is a config error:
	// mark Degraded and retry rather than deploying a broken exporter.
	var targetsSecret *corev1.Secret
	if len(spec.TargetClusters) > 0 {
		targets, err := r.resolveTargets(ctx, cr.Namespace, spec.TargetClusters)
		if err != nil {
			logger.Error(err, "resolving target cluster credentials")
			if uerr := r.setConditions(ctx, &cr, false, "InvalidTargetCredentials", err.Error()); uerr != nil {
				return ctrl.Result{}, uerr
			}
			return ctrl.Result{RequeueAfter: requeueOnConfigErr}, nil
		}
		targetsSecret = buildTargetsSecret(&cr, targets)
		if err := r.createOrUpdateSecret(ctx, &cr, targetsSecret); err != nil {
			return ctrl.Result{}, err
		}
	} else {
		// Single-cluster mode: ensure a stale targets Secret from a
		// previous multi-cluster spec does not linger.
		stale := &corev1.Secret{ObjectMeta: metav1.ObjectMeta{
			Name: secretKey(&cr).Name, Namespace: cr.Namespace,
		}}
		if err := r.deleteIfExists(ctx, stale); err != nil {
			return ctrl.Result{}, err
		}
	}

	deploy := buildDeployment(&cr, spec, targetsSecret != nil)
	if err := r.createOrUpdateDeployment(ctx, &cr, deploy); err != nil {
		return ctrl.Result{}, err
	}

	svc := buildService(&cr)
	if err := r.createOrUpdateService(ctx, &cr, svc); err != nil {
		return ctrl.Result{}, err
	}

	if spec.ServiceMonitor.Enabled {
		sm := buildServiceMonitor(&cr)
		if err := r.createOrUpdateServiceMonitor(ctx, &cr, sm); err != nil {
			return ctrl.Result{}, err
		}
	} else {
		stale := &monitoringv1.ServiceMonitor{ObjectMeta: metav1.ObjectMeta{
			Name: serviceMonitorKey(&cr).Name, Namespace: cr.Namespace,
		}}
		if err := r.deleteIfExists(ctx, stale); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Report availability from the Deployment's own status.
	var live appsv1.Deployment
	available := false
	if err := r.Get(ctx, deploymentKey(&cr), &live); err == nil {
		desired := int32(1)
		if spec.Replicas != nil {
			desired = *spec.Replicas
		}
		available = live.Status.AvailableReplicas >= desired && desired > 0
	}
	if err := r.setConditions(ctx, &cr, available, "", ""); err != nil {
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// SetupWithManager wires the reconciler to the manager and declares the
// owned resources so their events trigger re-reconciliation.
func (r *PowerScaleExporterReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&monitoringv1alpha1.PowerScaleExporter{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.Secret{}).
		Owns(&monitoringv1.ServiceMonitor{}).
		Complete(r)
}

// defaultedSpec applies CRD-level defaults in-memory (no defaulting webhook:
// this keeps the operator runnable without cert-manager).
func defaultedSpec(s monitoringv1alpha1.PowerScaleExporterSpec) monitoringv1alpha1.PowerScaleExporterSpec {
	out := *s.DeepCopy()
	if out.Replicas == nil {
		one := int32(1)
		out.Replicas = &one
	}
	if out.Image == "" {
		out.Image = defaultImage
	}
	if out.Isilon.Port == 0 {
		out.Isilon.Port = defaultPort
	}
	if out.AuthSecretRef.UserKey == "" {
		out.AuthSecretRef.UserKey = "ISILON_USER"
	}
	if out.AuthSecretRef.PasswordKey == "" {
		out.AuthSecretRef.PasswordKey = "ISILON_PASS"
	}
	for i := range out.TargetClusters {
		if out.TargetClusters[i].Port == 0 {
			out.TargetClusters[i].Port = defaultPort
		}
		if out.TargetClusters[i].AuthSecretRef.UserKey == "" {
			out.TargetClusters[i].AuthSecretRef.UserKey = "ISILON_USER"
		}
		if out.TargetClusters[i].AuthSecretRef.PasswordKey == "" {
			out.TargetClusters[i].AuthSecretRef.PasswordKey = "ISILON_PASS"
		}
	}
	return out
}

// targetEntry is one ISILON_TARGETS JSON entry.
type targetEntry struct {
	Name     string `json:"name"`
	Host     string `json:"host"`
	Port     int32  `json:"port"`
	User     string `json:"user"`
	Password string `json:"password"`
}

// resolveTargets reads every cluster's credentials from their Secrets and
// returns ISILON_TARGETS entries. Fail-fast mirrors the exporter: an entry
// without a password is a hard error, never silently skipped.
func (r *PowerScaleExporterReconciler) resolveTargets(ctx context.Context, ns string, clusters []monitoringv1alpha1.TargetCluster) ([]targetEntry, error) {
	seen := map[string]bool{}
	entries := make([]targetEntry, 0, len(clusters))
	for _, c := range clusters {
		if seen[c.Name] {
			return nil, fmt.Errorf("duplicate target cluster name %q", c.Name)
		}
		seen[c.Name] = true
		var sec corev1.Secret
		if err := r.Get(ctx, types.NamespacedName{Namespace: ns, Name: c.AuthSecretRef.Name}, &sec); err != nil {
			return nil, fmt.Errorf("cluster %q: secret %q: %w", c.Name, c.AuthSecretRef.Name, err)
		}
		user := string(sec.Data[c.AuthSecretRef.UserKey])
		password := string(sec.Data[c.AuthSecretRef.PasswordKey])
		if user == "" {
			return nil, fmt.Errorf("cluster %q: key %q empty in secret %q", c.Name, c.AuthSecretRef.UserKey, c.AuthSecretRef.Name)
		}
		if password == "" {
			return nil, fmt.Errorf("cluster %q: key %q empty in secret %q", c.Name, c.AuthSecretRef.PasswordKey, c.AuthSecretRef.Name)
		}
		entries = append(entries, targetEntry{
			Name: c.Name, Host: c.Host, Port: c.Port, User: user, Password: password,
		})
	}
	return entries, nil
}

// labels returns the selector + pod labels shared by the Deployment,
// its pods, and the Service/ServiceMonitor selectors.
func labels(cr *monitoringv1alpha1.PowerScaleExporter) map[string]string {
	return map[string]string{
		"app.kubernetes.io/name":     "powerscale-exporter",
		"app.kubernetes.io/instance": cr.Name,
	}
}

func deploymentKey(cr *monitoringv1alpha1.PowerScaleExporter) types.NamespacedName {
	return types.NamespacedName{Namespace: cr.Namespace, Name: cr.Name + "-exporter"}
}

func secretKey(cr *monitoringv1alpha1.PowerScaleExporter) types.NamespacedName {
	return types.NamespacedName{Namespace: cr.Namespace, Name: cr.Name + targetsSecretSuffix}
}

func serviceMonitorKey(cr *monitoringv1alpha1.PowerScaleExporter) types.NamespacedName {
	return types.NamespacedName{Namespace: cr.Namespace, Name: cr.Name + "-exporter"}
}

// setOwner sets the CR as controller owner so deletion cascades via GC.
func (r *PowerScaleExporterReconciler) setOwner(cr *monitoringv1alpha1.PowerScaleExporter, obj client.Object) error {
	return controllerutil.SetControllerReference(cr, obj, r.Scheme)
}

// buildTargetsSecret renders the ISILON_TARGETS_FILE content.
func buildTargetsSecret(cr *monitoringv1alpha1.PowerScaleExporter, entries []targetEntry) *corev1.Secret {
	data, _ := json.Marshal(entries)
	return &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      secretKey(cr).Name,
			Namespace: cr.Namespace,
			Labels:    labels(cr),
		},
		Type: corev1.SecretTypeOpaque,
		Data: map[string][]byte{"targets.json": data},
	}
}

// buildDeployment renders the exporter Deployment from the CR spec.
func buildDeployment(cr *monitoringv1alpha1.PowerScaleExporter, spec monitoringv1alpha1.PowerScaleExporterSpec, multiCluster bool) *appsv1.Deployment {
	lbls := labels(cr)
	env := []corev1.EnvVar{}
	var volumes []corev1.Volume
	var mounts []corev1.VolumeMount

	if multiCluster {
		env = append(env, corev1.EnvVar{Name: "ISILON_TARGETS_FILE", Value: targetsMountPath})
		volumes = append(volumes, corev1.Volume{
			Name: "targets",
			VolumeSource: corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{SecretName: secretKey(cr).Name},
			},
		})
		mounts = append(mounts, corev1.VolumeMount{
			Name: "targets", MountPath: "/etc/powerscale", ReadOnly: true,
		})
	} else {
		env = append(env,
			corev1.EnvVar{Name: "ISILON_HOST", Value: spec.Isilon.Host},
			corev1.EnvVar{Name: "ISILON_PORT", Value: fmt.Sprintf("%d", spec.Isilon.Port)},
			corev1.EnvVar{
				Name: "ISILON_USER",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{Name: spec.AuthSecretRef.Name},
						Key:                  spec.AuthSecretRef.UserKey,
					},
				},
			},
			corev1.EnvVar{
				Name: "ISILON_PASS",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{Name: spec.AuthSecretRef.Name},
						Key:                  spec.AuthSecretRef.PasswordKey,
					},
				},
			},
		)
	}

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      deploymentKey(cr).Name,
			Namespace: cr.Namespace,
			Labels:    lbls,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: spec.Replicas,
			Selector: &metav1.LabelSelector{MatchLabels: lbls},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: lbls},
				Spec: corev1.PodSpec{
					Volumes: volumes,
					Containers: []corev1.Container{{
						Name:            "powerscale-exporter",
						Image:           spec.Image,
						ImagePullPolicy: corev1.PullIfNotPresent,
						Ports: []corev1.ContainerPort{{
							Name: exporterPortName, ContainerPort: exporterPort, Protocol: corev1.ProtocolTCP,
						}},
						Env:            env,
						VolumeMounts:   mounts,
						Resources:      spec.Resources,
						LivenessProbe:  httpProbe("/livez"),
						ReadinessProbe: httpProbe("/readyz"),
					}},
				},
			},
		},
	}
}

// httpProbe hits the exporter's health endpoints (added in v1.2).
func httpProbe(path string) *corev1.Probe {
	return &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{Path: path, Port: intstr.FromString(exporterPortName)},
		},
		PeriodSeconds:    15,
		FailureThreshold: 3,
	}
}

// buildService renders the ClusterIP Service fronting the exporter pods.
func buildService(cr *monitoringv1alpha1.PowerScaleExporter) *corev1.Service {
	lbls := labels(cr)
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      deploymentKey(cr).Name,
			Namespace: cr.Namespace,
			Labels:    lbls,
		},
		Spec: corev1.ServiceSpec{
			Type:     corev1.ServiceTypeClusterIP,
			Selector: lbls,
			Ports: []corev1.ServicePort{{
				Name: exporterPortName, Port: exporterPort,
				TargetPort: intstr.FromString(exporterPortName), Protocol: corev1.ProtocolTCP,
			}},
		},
	}
}

// buildServiceMonitor renders the Prometheus Operator ServiceMonitor.
// The /metrics/ path (trailing slash) matches the exporter and the chart.
func buildServiceMonitor(cr *monitoringv1alpha1.PowerScaleExporter) *monitoringv1.ServiceMonitor {
	lbls := labels(cr)
	return &monitoringv1.ServiceMonitor{
		ObjectMeta: metav1.ObjectMeta{
			Name:      serviceMonitorKey(cr).Name,
			Namespace: cr.Namespace,
			Labels:    lbls,
		},
		Spec: monitoringv1.ServiceMonitorSpec{
			Selector: metav1.LabelSelector{MatchLabels: lbls},
			Endpoints: []monitoringv1.Endpoint{{
				Port:     exporterPortName,
				Path:     "/metrics/",
				Interval: "30s",
			}},
		},
	}
}

// setConditions updates Available/Degraded on the CR status.
func (r *PowerScaleExporterReconciler) setConditions(ctx context.Context, cr *monitoringv1alpha1.PowerScaleExporter, available bool, degradedReason, degradedMsg string) error {
	avail := metav1.Condition{
		Type:               "Available",
		Status:             metav1.ConditionFalse,
		Reason:             "NotAvailable",
		Message:            "exporter Deployment has no available replicas yet",
		ObservedGeneration: cr.Generation,
	}
	if available {
		avail.Status = metav1.ConditionTrue
		avail.Reason = "DeploymentAvailable"
		avail.Message = "exporter Deployment is available"
	}
	degraded := metav1.Condition{
		Type:               "Degraded",
		Status:             metav1.ConditionFalse,
		Reason:             "ReconcileOK",
		ObservedGeneration: cr.Generation,
	}
	if degradedReason != "" {
		degraded.Status = metav1.ConditionTrue
		degraded.Reason = degradedReason
		degraded.Message = degradedMsg
	}
	meta.SetStatusCondition(&cr.Status.Conditions, avail)
	meta.SetStatusCondition(&cr.Status.Conditions, degraded)
	cr.Status.ObservedGeneration = cr.Generation
	return r.Status().Update(ctx, cr)
}

// createOrUpdateDeployment creates the Deployment or rolls it on drift.
func (r *PowerScaleExporterReconciler) createOrUpdateDeployment(ctx context.Context, cr *monitoringv1alpha1.PowerScaleExporter, desired *appsv1.Deployment) error {
	if err := r.setOwner(cr, desired); err != nil {
		return err
	}
	var live appsv1.Deployment
	err := r.Get(ctx, deploymentKey(cr), &live)
	if apierrors.IsNotFound(err) {
		return r.Create(ctx, desired)
	}
	if err != nil {
		return err
	}
	live.Spec.Replicas = desired.Spec.Replicas
	live.Spec.Template = desired.Spec.Template
	live.Labels = desired.Labels
	return r.Update(ctx, &live)
}

func (r *PowerScaleExporterReconciler) createOrUpdateService(ctx context.Context, cr *monitoringv1alpha1.PowerScaleExporter, desired *corev1.Service) error {
	if err := r.setOwner(cr, desired); err != nil {
		return err
	}
	var live corev1.Service
	key := types.NamespacedName{Namespace: cr.Namespace, Name: desired.Name}
	err := r.Get(ctx, key, &live)
	if apierrors.IsNotFound(err) {
		return r.Create(ctx, desired)
	}
	if err != nil {
		return err
	}
	live.Spec.Ports = desired.Spec.Ports
	live.Spec.Selector = desired.Spec.Selector
	live.Labels = desired.Labels
	return r.Update(ctx, &live)
}

func (r *PowerScaleExporterReconciler) createOrUpdateSecret(ctx context.Context, cr *monitoringv1alpha1.PowerScaleExporter, desired *corev1.Secret) error {
	if err := r.setOwner(cr, desired); err != nil {
		return err
	}
	var live corev1.Secret
	err := r.Get(ctx, secretKey(cr), &live)
	if apierrors.IsNotFound(err) {
		return r.Create(ctx, desired)
	}
	if err != nil {
		return err
	}
	live.Data = desired.Data
	live.Labels = desired.Labels
	return r.Update(ctx, &live)
}

func (r *PowerScaleExporterReconciler) createOrUpdateServiceMonitor(ctx context.Context, cr *monitoringv1alpha1.PowerScaleExporter, desired *monitoringv1.ServiceMonitor) error {
	if err := r.setOwner(cr, desired); err != nil {
		return err
	}
	var live monitoringv1.ServiceMonitor
	err := r.Get(ctx, serviceMonitorKey(cr), &live)
	if apierrors.IsNotFound(err) {
		return r.Create(ctx, desired)
	}
	if err != nil {
		return err
	}
	live.Spec = desired.Spec
	live.Labels = desired.Labels
	return r.Update(ctx, &live)
}

// deleteIfExists removes an optional owned resource (targets Secret,
// ServiceMonitor). NotFound is fine.
func (r *PowerScaleExporterReconciler) deleteIfExists(ctx context.Context, obj client.Object) error {
	if err := r.Get(ctx, client.ObjectKeyFromObject(obj), obj); err != nil {
		return client.IgnoreNotFound(err)
	}
	// Only delete objects we own — never touch a same-named foreign resource.
	for _, ref := range obj.GetOwnerReferences() {
		if ref.Controller != nil && *ref.Controller && ref.Kind == "PowerScaleExporter" {
			return client.IgnoreNotFound(r.Delete(ctx, obj))
		}
	}
	return nil
}
