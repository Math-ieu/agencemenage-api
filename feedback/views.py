from rest_framework import viewsets, filters, permissions
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Q
from .models import Feedback
from .serializers import FeedbackSerializer
from demandes.models import AuditLog, Demande
from rest_framework.decorators import action
from rest_framework.response import Response


class FeedbackViewSet(viewsets.ModelViewSet):
    queryset = Feedback.objects.select_related('mission', 'client', 'demande').all()
    serializer_class = FeedbackSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_fields = ['client', 'note_agence', 'note_intervenant']
    search_fields = [
        'commentaire', 
        'demande__client_name', 
        'demande__formulaire_data',
        'demande__service'
    ]
    ordering = ['-date']

    def get_queryset(self):
        qs = super().get_queryset()
        city = self.request.query_params.get('city')
        if city:
            qs = qs.filter(demande__neighborhood_city__icontains=city)
        return qs

    @action(detail=False, methods=['get'])
    def stats(self, request):
        # KPI: Total finished prestations
        total_finished = Demande.objects.filter(statut='pres_terminee').count()
        
        # KPI: Feedbacks counts
        all_feedbacks = Feedback.objects.all()
        positives = all_feedbacks.filter(Q(note_agence__gte=4) | Q(note_intervenant__gte=4)).count()
        negatives = all_feedbacks.filter(Q(note_agence__lte=2) | Q(note_intervenant__lte=2)).count()

        # Chart: Distribution of ratings
        agency_dist = {str(i): 0 for i in range(1, 6)}
        agent_dist = {str(i): 0 for i in range(1, 6)}
        
        for f in all_feedbacks:
            if f.note_agence:
                agency_dist[str(f.note_agence)] += 1
            if f.note_intervenant:
                agent_dist[str(f.note_intervenant)] += 1

        # Satisfaction levels (Pie chart)
        satisfaction = {
            'Très satisfait': 0,
            'Satisfait': 0,
            'Moyen': 0,
            'Pas satisfait': 0
        }
        for f in all_feedbacks:
            n_agence = f.note_agence or 0
            n_inter = f.note_intervenant or 0
            count = (1 if f.note_agence else 0) + (1 if f.note_intervenant else 0)
            mean_note = (n_agence + n_inter) / (count or 1)
            
            if mean_note >= 4.5: satisfaction['Très satisfait'] += 1
            elif mean_note >= 3.5: satisfaction['Satisfait'] += 1
            elif mean_note >= 2.5: satisfaction['Moyen'] += 1
            else: satisfaction['Pas satisfait'] += 1

        return Response({
            'kpis': {
                'total_finished': total_finished,
                'positives': positives,
                'negatives': negatives,
            },
            'charts': {
                'distribution': [
                    {
                        'name': f"{i}★",
                        'agence': agency_dist[str(i)],
                        'profil': agent_dist[str(i)]
                    } for i in range(1, 6)
                ],
                'satisfaction': [
                    {'name': k, 'value': v} for k, v in satisfaction.items() if v > 0
                ]
            }
        })

    def perform_create(self, serializer):
        feedback = serializer.save()

        # Update client opt-out if requested
        if feedback.opt_out:
            client = feedback.client
            if not client and feedback.demande:
                client = feedback.demande.client
            
            if client:
                client.opt_out_feedback = True
                client.save()
        
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
                'client_name': client_name,
                'opt_out': feedback.opt_out
            }
        )
