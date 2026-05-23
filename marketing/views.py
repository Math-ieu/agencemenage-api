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
        
        # Logic for updating Mission financials and Demande financials
        if instance.demande:
            # Apply direct price reduction to Demande
            from decimal import Decimal
            dem = instance.demande
            if instance.gesture_type == 'intervention_gratuite':
                dem.prix = Decimal(0)
                dem.statut_paiement = 'integral'
                dem.save()
            elif instance.gesture_type == 'reduction_tarif':
                current_price = dem.prix or Decimal(0)
                reduction_value = Decimal(instance.reduction_value or 0)
                if instance.reduction_type == 'pourcentage':
                    new_price = current_price * (Decimal(1) - reduction_value / Decimal(100))
                else:
                    new_price = max(Decimal(0), current_price - reduction_value)
                dem.prix = new_price
                dem.save()

            missions = instance.demande.missions.all()
            for mission in missions:
                if instance.gesture_type in ['facturation_annulee', 'intervention_gratuite']:
                    # Cas A: Agency owes profile, client pays 0
                    mission.paiement_client_statut = 'intervention_gratuite' if instance.gesture_type == 'intervention_gratuite' else 'facturation_annulee'
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
