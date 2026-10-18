// Hand-written deepcopy functions (no code-generator in this environment).

package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
)

func (in *PowerScaleExporter) DeepCopyInto(out *PowerScaleExporter) {
	*out = *in
	out.TypeMeta = in.TypeMeta
	in.ObjectMeta.DeepCopyInto(&out.ObjectMeta)
	in.Spec.DeepCopyInto(&out.Spec)
	in.Status.DeepCopyInto(&out.Status)
}

func (in *PowerScaleExporter) DeepCopy() *PowerScaleExporter {
	if in == nil {
		return nil
	}
	out := new(PowerScaleExporter)
	in.DeepCopyInto(out)
	return out
}

func (in *PowerScaleExporter) DeepCopyObject() runtime.Object {
	if c := in.DeepCopy(); c != nil {
		return c
	}
	return nil
}

func (in *PowerScaleExporterList) DeepCopyInto(out *PowerScaleExporterList) {
	*out = *in
	out.TypeMeta = in.TypeMeta
	in.ListMeta.DeepCopyInto(&out.ListMeta)
	if in.Items != nil {
		in, out := &in.Items, &out.Items
		*out = make([]PowerScaleExporter, len(*in))
		for i := range *in {
			(*in)[i].DeepCopyInto(&(*out)[i])
		}
	}
}

func (in *PowerScaleExporterList) DeepCopy() *PowerScaleExporterList {
	if in == nil {
		return nil
	}
	out := new(PowerScaleExporterList)
	in.DeepCopyInto(out)
	return out
}

func (in *PowerScaleExporterList) DeepCopyObject() runtime.Object {
	if c := in.DeepCopy(); c != nil {
		return c
	}
	return nil
}

func (in *IsilonConnection) DeepCopyInto(out *IsilonConnection) {
	*out = *in
}

func (in *IsilonConnection) DeepCopy() *IsilonConnection {
	if in == nil {
		return nil
	}
	out := new(IsilonConnection)
	in.DeepCopyInto(out)
	return out
}

func (in *SecretKeyRef) DeepCopyInto(out *SecretKeyRef) {
	*out = *in
}

func (in *SecretKeyRef) DeepCopy() *SecretKeyRef {
	if in == nil {
		return nil
	}
	out := new(SecretKeyRef)
	in.DeepCopyInto(out)
	return out
}

func (in *TargetCluster) DeepCopyInto(out *TargetCluster) {
	*out = *in
	out.AuthSecretRef = in.AuthSecretRef
}

func (in *TargetCluster) DeepCopy() *TargetCluster {
	if in == nil {
		return nil
	}
	out := new(TargetCluster)
	in.DeepCopyInto(out)
	return out
}

func (in *ServiceMonitorSpec) DeepCopyInto(out *ServiceMonitorSpec) {
	*out = *in
}

func (in *ServiceMonitorSpec) DeepCopy() *ServiceMonitorSpec {
	if in == nil {
		return nil
	}
	out := new(ServiceMonitorSpec)
	in.DeepCopyInto(out)
	return out
}

func (in *PowerScaleExporterSpec) DeepCopyInto(out *PowerScaleExporterSpec) {
	*out = *in
	out.Isilon = in.Isilon
	out.AuthSecretRef = in.AuthSecretRef
	if in.TargetClusters != nil {
		in, out := &in.TargetClusters, &out.TargetClusters
		*out = make([]TargetCluster, len(*in))
		copy(*out, *in)
	}
	if in.Replicas != nil {
		in, out := &in.Replicas, &out.Replicas
		*out = new(int32)
		**out = **in
	}
	out.ServiceMonitor = in.ServiceMonitor
	in.Resources.DeepCopyInto(&out.Resources)
}

func (in *PowerScaleExporterSpec) DeepCopy() *PowerScaleExporterSpec {
	if in == nil {
		return nil
	}
	out := new(PowerScaleExporterSpec)
	in.DeepCopyInto(out)
	return out
}

func (in *PowerScaleExporterStatus) DeepCopyInto(out *PowerScaleExporterStatus) {
	*out = *in
	if in.Conditions != nil {
		in, out := &in.Conditions, &out.Conditions
		*out = make([]metav1.Condition, len(*in))
		for i := range *in {
			(*in)[i].DeepCopyInto(&(*out)[i])
		}
	}
}
