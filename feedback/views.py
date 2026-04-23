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
        
        # Determine agent ID for logging if mission exists
        agent_id = None
        if feedback.mission and feedback.mission.agent:
            agent_id = feedback.mission.agent.pk
        elif feedback.demande:
            # Fallback to last profile sent for this demande
            last_agent = feedback.demande.profils_envoyes.last()
            if last_agent:
                agent_id = last_agent.pk

        # Log action
        client_name = 'Client'
        if feedback.client:
            client_name = feedback.client.display_name
        elif feedback.demande:
            client_name = feedback.demande.client_name or 'Client'

        AuditLog.objects.create(
            user=self.request.user if self.request.user.is_authenticated else None,
            action='Feedback reçu',
            model_name='Feedback',
            object_id=feedback.pk,
            extra_data={
                'agent_id': agent_id,
                'note_intervenant': feedback.note_intervenant,
                'note_agence': feedback.note_agence,
                'client_name': client_name
            }
        )
