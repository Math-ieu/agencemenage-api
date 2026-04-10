from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Feedback
from .serializers import FeedbackSerializer
from demandes.models import AuditLog


class FeedbackViewSet(viewsets.ModelViewSet):
    queryset = Feedback.objects.select_related('mission', 'client').all()
    serializer_class = FeedbackSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['note', 'client']
    ordering = ['-date']

    def perform_create(self, serializer):
        feedback = serializer.save()
        # Log for the agent
        AuditLog.objects.create(
            user=self.request.user,
            action='Feedback reçu',
            model_name='Feedback',
            object_id=feedback.pk,
            extra_data={
                'agent_id': feedback.mission.agent.pk,
                'note': feedback.note,
                'client_name': feedback.client.display_name if feedback.client else 'Client'
            }
        )
