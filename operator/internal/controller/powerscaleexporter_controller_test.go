package controller

import (
	"context"
	"encoding/json"
	"testing"

	monitoringv1 "github.com/prometheus-operator/prometheus-operator/pkg/apis/monitoring/v1"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	monitoringv1alpha1 "github.com/chanawh/pscale-exporter/operator/api/v1alpha1"
)

func testScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(s); err != nil {
		t.Fatal(err)
	}
	if err := monitoringv1alpha1.AddToScheme(s); err != nil {
		t.Fatal(err)
	}
	if err := monitoringv1.AddToScheme(s); err != nil {
		t.Fatal(err)
	}
	return s
}

func newReconciler(s *runtime.Scheme, objs ...client.Object) (*PowerScaleExporterReconciler, client.Client) {
	c := fake.NewClientBuilder().
		WithScheme(s).
		WithObjects(objs...).
		WithStatusSubresource(&monitoringv1alpha1.PowerScaleExporter{}, &appsv1.Deployment{}).
		Build()
	return &PowerScaleExporterReconciler{Client: c, Scheme: s}, c
}

func singleClusterCR() *monitoringv1alpha1.PowerScaleExporter {
	three := int32(3)
	return &monitoringv1alpha1.PowerScaleExporter{
		ObjectMeta: metav1.ObjectMeta{Name: "prod", Namespace: "monitoring", UID: "uid-prod"},
		Spec: monitoringv1alpha1.PowerScaleExporterSpec{
			Isilon:        monitoringv1alpha1.IsilonConnection{Host: "powerscale.example.com", Port: 8080},
			AuthSecretRef: monitoringv1alpha1.SecretKeyRef{Name: "isilon-auth"},
			Replicas:      &three,
			Image:         "awhchan/powerscale-exporter:3.0.1",
		},
	}
}

func authSecret() *corev1.Secret {
	return &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Name: "isilon-auth", Namespace: "monitoring"},
		Data: map[string][]byte{
			"ISILON_USER": []byte("root"),
			"ISILON_PASS": []byte("s3cret"),
		},
	}
}

func reconcile(t *testing.T, r *PowerScaleExporterReconciler, name types.NamespacedName) ctrl.Result {
	t.Helper()
	res, err := r.Reconcile(context.Background(), ctrl.Request{NamespacedName: name})
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	return res
}

func getDeployment(t *testing.T, c client.Client, cr *monitoringv1alpha1.PowerScaleExporter) *appsv1.Deployment {
	t.Helper()
	var d appsv1.Deployment
	if err := c.Get(context.Background(), deploymentKey(cr), &d); err != nil {
		t.Fatalf("get deployment: %v", err)
	}
	return &d
}

// assertControlled verifies the controller OwnerReference that lets the
// API server's garbage collector cascade-delete owned resources in a real
// cluster (the fake client has no GC, so this is the honest assertion).
func assertControlled(t *testing.T, cr *monitoringv1alpha1.PowerScaleExporter, obj client.Object, what string) {
	t.Helper()
	if cr.UID == "" {
		t.Fatalf("test bug: CR %s has no UID, OwnerReference assertion would be vacuous", cr.Name)
	}
	found := false
	for _, ref := range obj.GetOwnerReferences() {
		if ref.Kind == "PowerScaleExporter" && ref.Name == cr.Name && ref.UID == cr.UID &&
			ref.Controller != nil && *ref.Controller {
			found = true
		}
	}
	if !found {
		t.Errorf("%s %s/%s missing controller OwnerReference to the CR", what, obj.GetNamespace(), obj.GetName())
	}
}

func envByName(env []corev1.EnvVar, name string) *corev1.EnvVar {
	for i := range env {
		if env[i].Name == name {
			return &env[i]
		}
	}
	return nil
}

func TestReconcileSingleCluster(t *testing.T) {
	s := testScheme(t)
	cr := singleClusterCR()
	r, c := newReconciler(s, cr, authSecret())
	reconcile(t, r, types.NamespacedName{Name: "prod", Namespace: "monitoring"})

	dep := getDeployment(t, c, cr)
	if *dep.Spec.Replicas != 3 {
		t.Errorf("replicas = %d, want 3", *dep.Spec.Replicas)
	}
	ctr := dep.Spec.Template.Spec.Containers[0]
	if ctr.Image != "awhchan/powerscale-exporter:3.0.1" {
		t.Errorf("image = %q", ctr.Image)
	}
	if e := envByName(ctr.Env, "ISILON_HOST"); e == nil || e.Value != "powerscale.example.com" {
		t.Errorf("ISILON_HOST env wrong: %+v", e)
	}
	if e := envByName(ctr.Env, "ISILON_PORT"); e == nil || e.Value != "8080" {
		t.Errorf("ISILON_PORT env wrong: %+v", e)
	}
	if e := envByName(ctr.Env, "ISILON_USER"); e == nil || e.ValueFrom == nil ||
		e.ValueFrom.SecretKeyRef.Name != "isilon-auth" || e.ValueFrom.SecretKeyRef.Key != "ISILON_USER" {
		t.Errorf("ISILON_USER should be a secretKeyRef to isilon-auth/ISILON_USER: %+v", e)
	}
	if e := envByName(ctr.Env, "ISILON_PASS"); e == nil || e.ValueFrom == nil ||
		e.ValueFrom.SecretKeyRef.Name != "isilon-auth" || e.ValueFrom.SecretKeyRef.Key != "ISILON_PASS" {
		t.Errorf("ISILON_PASS should be a secretKeyRef to isilon-auth/ISILON_PASS: %+v", e)
	}
	if e := envByName(ctr.Env, "ISILON_TARGETS_FILE"); e != nil {
		t.Errorf("single-cluster mode must not set ISILON_TARGETS_FILE")
	}
	// Probes mirror the exporter's /livez and /readyz endpoints.
	if ctr.LivenessProbe == nil || ctr.LivenessProbe.HTTPGet.Path != "/livez" {
		t.Errorf("liveness probe should hit /livez")
	}
	if ctr.ReadinessProbe == nil || ctr.ReadinessProbe.HTTPGet.Path != "/readyz" {
		t.Errorf("readiness probe should hit /readyz")
	}
	assertControlled(t, cr, dep, "Deployment")

	var svc corev1.Service
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "monitoring", Name: "prod-exporter"}, &svc); err != nil {
		t.Fatalf("get service: %v", err)
	}
	if svc.Spec.Ports[0].Port != 8000 {
		t.Errorf("service port = %d, want 8000", svc.Spec.Ports[0].Port)
	}
	assertControlled(t, cr, &svc, "Service")

	// No ServiceMonitor, no targets Secret in single-cluster default mode.
	var sm monitoringv1.ServiceMonitor
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "monitoring", Name: "prod-exporter"}, &sm); err == nil {
		t.Errorf("ServiceMonitor should not exist when disabled")
	}
	var ts corev1.Secret
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "monitoring", Name: "prod-targets"}, &ts); err == nil {
		t.Errorf("targets Secret should not exist in single-cluster mode")
	}

	// No available replicas yet (no deployment controller in the fake
	// client) → Available=False.
	var live monitoringv1alpha1.PowerScaleExporter
	if err := c.Get(context.Background(), types.NamespacedName{Name: "prod", Namespace: "monitoring"}, &live); err != nil {
		t.Fatal(err)
	}
	if cond := meta.FindStatusCondition(live.Status.Conditions, "Available"); cond == nil || cond.Status != metav1.ConditionFalse {
		t.Errorf("Available should be False with no replicas, got %+v", cond)
	}
}

func TestReconcileAvailableWhenReplicasReady(t *testing.T) {
	s := testScheme(t)
	cr := singleClusterCR()
	r, c := newReconciler(s, cr, authSecret())
	nn := types.NamespacedName{Name: "prod", Namespace: "monitoring"}
	reconcile(t, r, nn)

	// Simulate the deployment controller reporting ready replicas.
	dep := getDeployment(t, c, cr)
	dep.Status.AvailableReplicas = 3
	if err := c.Status().Update(context.Background(), dep); err != nil {
		t.Fatal(err)
	}
	reconcile(t, r, nn)

	var live monitoringv1alpha1.PowerScaleExporter
	if err := c.Get(context.Background(), nn, &live); err != nil {
		t.Fatal(err)
	}
	if cond := meta.FindStatusCondition(live.Status.Conditions, "Available"); cond == nil || cond.Status != metav1.ConditionTrue {
		t.Errorf("Available should be True, got %+v", cond)
	}
	if live.Status.ObservedGeneration != live.Generation {
		t.Errorf("ObservedGeneration not tracked")
	}
}

func TestReconcileSpecUpdateRollsDeployment(t *testing.T) {
	s := testScheme(t)
	cr := singleClusterCR()
	r, c := newReconciler(s, cr, authSecret())
	nn := types.NamespacedName{Name: "prod", Namespace: "monitoring"}
	reconcile(t, r, nn)

	// Update the CR: scale down and change the image.
	var live monitoringv1alpha1.PowerScaleExporter
	if err := c.Get(context.Background(), nn, &live); err != nil {
		t.Fatal(err)
	}
	one := int32(1)
	live.Spec.Replicas = &one
	live.Spec.Image = "awhchan/powerscale-exporter:3.0.2"
	if err := c.Update(context.Background(), &live); err != nil {
		t.Fatal(err)
	}
	reconcile(t, r, nn)

	dep := getDeployment(t, c, cr)
	if *dep.Spec.Replicas != 1 {
		t.Errorf("replicas = %d, want 1 after update", *dep.Spec.Replicas)
	}
	if dep.Spec.Template.Spec.Containers[0].Image != "awhchan/powerscale-exporter:3.0.2" {
		t.Errorf("image not rolled: %q", dep.Spec.Template.Spec.Containers[0].Image)
	}
}

func TestReconcileServiceMonitorToggle(t *testing.T) {
	s := testScheme(t)
	cr := singleClusterCR()
	cr.Spec.ServiceMonitor.Enabled = true
	r, c := newReconciler(s, cr, authSecret())
	nn := types.NamespacedName{Name: "prod", Namespace: "monitoring"}
	reconcile(t, r, nn)

	var sm monitoringv1.ServiceMonitor
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "monitoring", Name: "prod-exporter"}, &sm); err != nil {
		t.Fatalf("get servicemonitor: %v", err)
	}
	if sm.Spec.Endpoints[0].Port != "http" || sm.Spec.Endpoints[0].Path != "/metrics/" {
		t.Errorf("servicemonitor endpoint wrong: %+v", sm.Spec.Endpoints[0])
	}
	if sm.Spec.Selector.MatchLabels["app.kubernetes.io/instance"] != "prod" {
		t.Errorf("servicemonitor selector wrong: %v", sm.Spec.Selector.MatchLabels)
	}
	assertControlled(t, cr, &sm, "ServiceMonitor")

	// Disable → the owned ServiceMonitor is removed.
	var live monitoringv1alpha1.PowerScaleExporter
	if err := c.Get(context.Background(), nn, &live); err != nil {
		t.Fatal(err)
	}
	live.Spec.ServiceMonitor.Enabled = false
	if err := c.Update(context.Background(), &live); err != nil {
		t.Fatal(err)
	}
	reconcile(t, r, nn)
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "monitoring", Name: "prod-exporter"}, &sm); err == nil {
		t.Errorf("ServiceMonitor should be deleted after disable")
	}
}

func multiClusterCR() *monitoringv1alpha1.PowerScaleExporter {
	return &monitoringv1alpha1.PowerScaleExporter{
		ObjectMeta: metav1.ObjectMeta{Name: "fleet", Namespace: "monitoring", UID: "uid-fleet"},
		Spec: monitoringv1alpha1.PowerScaleExporterSpec{
			Isilon:        monitoringv1alpha1.IsilonConnection{Host: "ignored.example.com"},
			AuthSecretRef: monitoringv1alpha1.SecretKeyRef{Name: "ignored"},
			TargetClusters: []monitoringv1alpha1.TargetCluster{
				{
					Name: "prod", Host: "ps-prod.example.com", Port: 8080,
					AuthSecretRef: monitoringv1alpha1.SecretKeyRef{Name: "auth-prod"},
				},
				{
					Name: "dr", Host: "ps-dr.example.com", Port: 8080,
					AuthSecretRef: monitoringv1alpha1.SecretKeyRef{Name: "auth-dr", UserKey: "username", PasswordKey: "password"},
				},
			},
		},
	}
}

func TestReconcileMultiCluster(t *testing.T) {
	s := testScheme(t)
	cr := multiClusterCR()
	r, c := newReconciler(s, cr,
		&corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "auth-prod", Namespace: "monitoring"},
			Data: map[string][]byte{"ISILON_USER": []byte("root"), "ISILON_PASS": []byte("pw1")}},
		&corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "auth-dr", Namespace: "monitoring"},
			Data: map[string][]byte{"username": []byte("admin"), "password": []byte("pw2")}},
	)
	nn := types.NamespacedName{Name: "fleet", Namespace: "monitoring"}
	reconcile(t, r, nn)

	// targets.json Secret rendered with both clusters' credentials.
	var ts corev1.Secret
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "monitoring", Name: "fleet-targets"}, &ts); err != nil {
		t.Fatalf("get targets secret: %v", err)
	}
	var entries []map[string]any
	if err := json.Unmarshal(ts.Data["targets.json"], &entries); err != nil {
		t.Fatalf("targets.json invalid: %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("want 2 target entries, got %d", len(entries))
	}
	byName := map[string]map[string]any{}
	for _, e := range entries {
		byName[e["name"].(string)] = e
	}
	if byName["prod"]["user"] != "root" || byName["prod"]["password"] != "pw1" || byName["prod"]["host"] != "ps-prod.example.com" {
		t.Errorf("prod entry wrong: %v", byName["prod"])
	}
	if byName["dr"]["user"] != "admin" || byName["dr"]["password"] != "pw2" {
		t.Errorf("dr entry wrong (custom keys): %v", byName["dr"])
	}
	assertControlled(t, cr, &ts, "targets Secret")

	// Deployment uses ISILON_TARGETS_FILE, not single-cluster env.
	dep := getDeployment(t, c, cr)
	ctr := dep.Spec.Template.Spec.Containers[0]
	if e := envByName(ctr.Env, "ISILON_TARGETS_FILE"); e == nil || e.Value != "/etc/powerscale/targets.json" {
		t.Errorf("ISILON_TARGETS_FILE env wrong: %+v", e)
	}
	if e := envByName(ctr.Env, "ISILON_HOST"); e != nil {
		t.Errorf("multi-cluster mode must ignore single-cluster ISILON_HOST")
	}
	mounted := false
	for _, v := range ctr.VolumeMounts {
		if v.MountPath == "/etc/powerscale" {
			mounted = true
		}
	}
	if !mounted {
		t.Errorf("targets volume not mounted at /etc/powerscale")
	}

	// Switching back to single-cluster mode removes the targets Secret.
	var live monitoringv1alpha1.PowerScaleExporter
	if err := c.Get(context.Background(), nn, &live); err != nil {
		t.Fatal(err)
	}
	live.Spec.TargetClusters = nil
	live.Spec.Isilon = monitoringv1alpha1.IsilonConnection{Host: "powerscale.example.com", Port: 8080}
	live.Spec.AuthSecretRef = monitoringv1alpha1.SecretKeyRef{Name: "auth-prod"}
	if err := c.Update(context.Background(), &live); err != nil {
		t.Fatal(err)
	}
	reconcile(t, r, nn)
	if err := c.Get(context.Background(), types.NamespacedName{Namespace: "monitoring", Name: "fleet-targets"}, &ts); err == nil {
		t.Errorf("stale targets Secret should be deleted in single-cluster mode")
	}
}

func TestReconcileMissingClusterSecret(t *testing.T) {
	s := testScheme(t)
	cr := multiClusterCR() // references auth-prod/auth-dr, which we do NOT create
	r, c := newReconciler(s, cr)
	nn := types.NamespacedName{Name: "fleet", Namespace: "monitoring"}
	res := reconcile(t, r, nn)

	if res.RequeueAfter == 0 {
		t.Errorf("expected requeue on missing credential secret")
	}
	// Degraded condition set; no half-built Deployment left behind.
	var live monitoringv1alpha1.PowerScaleExporter
	if err := c.Get(context.Background(), nn, &live); err != nil {
		t.Fatal(err)
	}
	if cond := meta.FindStatusCondition(live.Status.Conditions, "Degraded"); cond == nil || cond.Status != metav1.ConditionTrue {
		t.Errorf("Degraded should be True, got %+v", cond)
	}
	var dep appsv1.Deployment
	if err := c.Get(context.Background(), deploymentKey(cr), &dep); err == nil {
		t.Errorf("no Deployment should exist when credentials are unresolvable")
	}
}

func TestReconcileDuplicateClusterNames(t *testing.T) {
	s := testScheme(t)
	cr := multiClusterCR()
	cr.Spec.TargetClusters[1].Name = "prod" // duplicate
	r, c := newReconciler(s, cr,
		&corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "auth-prod", Namespace: "monitoring"},
			Data: map[string][]byte{"ISILON_USER": []byte("root"), "ISILON_PASS": []byte("pw1")}},
	)
	nn := types.NamespacedName{Name: "fleet", Namespace: "monitoring"}
	reconcile(t, r, nn)

	var live monitoringv1alpha1.PowerScaleExporter
	if err := c.Get(context.Background(), nn, &live); err != nil {
		t.Fatal(err)
	}
	if cond := meta.FindStatusCondition(live.Status.Conditions, "Degraded"); cond == nil || cond.Status != metav1.ConditionTrue {
		t.Errorf("Degraded should be True on duplicate cluster names, got %+v", cond)
	}
}
