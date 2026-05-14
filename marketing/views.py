from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import PromoCode, CommercialGesture, Campaign
from .serializers import PromoCodeSerializer, CommercialGestureSerializer, CampaignSerializer

class PromoCodeViewSet(viewsets.ModelViewSet):
    queryset = PromoCode.objects.all().order_by('-created_at')
    serializer_class = PromoCodeSerializer
    permission_classes = [IsAuthenticated]

class CommercialGestureViewSet(viewsets.ModelViewSet):
    queryset = CommercialGesture.objects.all().order_by('-created_at')
    serializer_class = CommercialGestureSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('client', 'cree_par', 'demande')
        user = self.request.user
        if user.is_authenticated and user.role == 'commercial' and not user.is_staff:
            return queryset.filter(cree_par=user)
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save(cree_par=self.request.user)
        # Link client if missing but demande is there
        if instance.demande and not instance.client:
            instance.client = instance.demande.client
            instance.save()
        
        # Logic for updating Mission financials
        if instance.demande:
            missions = instance.demande.missions.all()
            for mission in missions:
                if instance.gesture_type in ['facturation_annulee', 'intervention_gratuite']:
                    # Cas A: Agency owes profile, client pays 0
                    mission.paiement_client_statut = 'facturation_annulee'
                    mission.montant_paye = 0
                    # The agency owes the profile the full share or a specific amount
                    # Here we use the part_profil defined in the gesture
                    mission.montant_agence_doit_profil = instance.part_profil
                    mission.profil_sera_paye = True
                    mission.save()
                elif instance.gesture_type == 'reduction_tarif':
                    # Cas B: Reduced CA
                    # We might want to update the mission's expected CA if needed
                    # For now, we just ensure the mission is aware of the gesture
                    pass

class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all().order_by('-created_at')
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated]
