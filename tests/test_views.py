from django.test import TestCase

from rest_framework.permissions import IsAuthenticated

from mcserver.models import AnalysisFunction
from mcserver.serializers import AnalysisFunctionSerializer
from mcserver.views import AnalysisFunctionAPIView


class SerializersTests(TestCase):
    def test_analysis_function_serializer_represents_correct_fields(self):
        self.assertEqual(
            set(AnalysisFunctionSerializer.Meta.fields),
            {'id', 'title', 'description'}
        )


class ViewsTests(TestCase):
    def test_analysis_function_api_view_has_correct_permission_classes(self):
        self.assertEqual(AnalysisFunctionAPIView.permission_classes, (IsAuthenticated, ))
    
    def test_analysis_function_api_view_uses_correct_serializer_class(self):
        self.assertTrue(
            issubclass(AnalysisFunctionAPIView.serializer_class, AnalysisFunctionSerializer)
        )

    def test_analysis_function_api_view_list_only_active_functions(self):
        AnalysisFunction.objects.create(title='function 0', description='description 0')
        AnalysisFunction.objects.create(title='function 1', description='description 1')
        inactive_func = AnalysisFunction.objects.create(
            title='function 2', description='description 2', is_active=False
        )
        view = AnalysisFunctionAPIView()
        qs = view.get_queryset()
        self.assertEqual(qs.count(), 2)
        self.assertNotIn(inactive_func.id, list(qs.values_list('id', flat=True)))
