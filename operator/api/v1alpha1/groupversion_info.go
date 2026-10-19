// Package v1alpha1 contains the PowerScaleExporter CRD API types.
//
// Group: monitoring.chanawh.io, Version: v1alpha1, Kind: PowerScaleExporter
package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

var (
	GroupVersion = schema.GroupVersion{Group: "monitoring.chanawh.io", Version: "v1alpha1"}

	SchemeBuilder = runtime.NewSchemeBuilder(addKnownTypes)
	AddToScheme   = SchemeBuilder.AddToScheme
)

func addKnownTypes(s *runtime.Scheme) error {
	s.AddKnownTypes(GroupVersion,
		&PowerScaleExporter{},
		&PowerScaleExporterList{},
	)
	metav1.AddToGroupVersion(s, GroupVersion)
	return nil
}
