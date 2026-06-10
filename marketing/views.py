from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import PromoCode, CommercialGesture, Campaign
from .serializers import PromoCodeSerializer, CommercialGestureSerializer, CampaignSerializer

class PromoCodeViewSet(viewsets.ModelViewSet):
    from accounts.permissions import RoleBasedPermission
    queryset = PromoCode.objects.all().order_by('-created_at')
    serializer_class = PromoCodeSerializer
    permission_classes = [IsAuthenticated, RoleBasedPermission]

class CommercialGestureViewSet(viewsets.ModelViewSet):
    from accounts.permissions import RoleBasedPermission
    queryset = CommercialGesture.objects.all().order_by('-created_at')
    serializer_class = CommercialGestureSerializer
    permission_classes = [IsAuthenticated, RoleBasedPermission]
    
    def get_queryset(self):
        return super().get_queryset().select_related('client', 'cree_par', 'demande')

    def perform_create(self, serializer):
        cree_par = serializer.validated_data.get('cree_par') or self.request.user
        instance = serializer.save(cree_par=cree_par)
        # Link client if missing but demande is there
        if instance.demande and not instance.client:
            instance.client = instance.demande.client
            instance.save()
        
        # Logic for updating Mission financials and Demande financials
        if instance.demande:
            # Apply direct price reduction to Demande
            from decimal import Decimal
            dem = instance.demande
            
            if instance.gesture_type in ['facturation_annulee', 'intervention_gratuite']:
                dem.prix = Decimal(0)
                dem.statut_paiement = instance.gesture_type
                
                # Update formulaire_data for Demande
                form_data = dem.formulaire_data or {}
                if not isinstance(form_data, dict):
                    form_data = {}
                
                facturation = form_data.get('facturation', {})
                if not isinstance(facturation, dict):
                    facturation = {}
                
                # Reset client billing amounts to 0
                facturation['montant_ht'] = 0
                facturation['montant'] = 0
                facturation['montant_ttc'] = 0
                facturation['montant_verse'] = 0
                facturation['part_agence'] = 0
                dem.part_agence = Decimal(0)
                facturation['statut_paiement_ui'] = instance.gesture_type
                facturation['facturation_annulee'] = True
                
                total_profiles_share = float(instance.part_profil or 0)
                facturation['profil_sera_paye'] = total_profiles_share > 0
                facturation['montant_profil_annulation'] = total_profiles_share
                facturation['montant_agence_doit_profil'] = total_profiles_share
                
                parts = facturation.get('parts_repartition', [])
                if isinstance(parts, list) and parts:
                    count = len(parts)
                    amount_per_profile = round(total_profiles_share / count, 2)
                    new_parts = []
                    for i, p in enumerate(parts):
                        if isinstance(p, dict):
                            p_copy = dict(p)
                            if i == count - 1:
                                p_copy['amount'] = round(total_profiles_share - (amount_per_profile * (count - 1)), 2)
                            else:
                                p_copy['amount'] = amount_per_profile
                            p_copy['part_profil_versee'] = False
                            new_parts.append(p_copy)
                    facturation['parts_repartition'] = new_parts
                else:
                    facturation['part_profil_versee'] = False

                form_data['facturation'] = facturation
                dem.formulaire_data = form_data
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

            # Map the exact parts to missions
            form_data = dem.formulaire_data or {}
            facturation = form_data.get('facturation', {}) if isinstance(form_data, dict) else {}
            parts_map = {}
            parts = facturation.get('parts_repartition', []) if isinstance(facturation, dict) else []
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict) and p.get('profile_id'):
                        try:
                            pid = int(p['profile_id'])
                            val = float(p.get('amount') or p.get('part_profil') or p.get('montant_profil') or 0)
                            parts_map[pid] = val
                        except ValueError:
                            pass

            missions = instance.demande.missions.all()
            for mission in missions:
                if instance.gesture_type in ['facturation_annulee', 'intervention_gratuite']:
                    # Cas A: Agency owes profile, client pays 0
                    mission.paiement_client_statut = 'intervention_gratuite' if instance.gesture_type == 'intervention_gratuite' else 'facturation_annulee'
                    mission.montant_paye = 0
                    
                    # Determine the part of this profile
                    p_share = 0
                    if mission.agent_id in parts_map:
                        p_share = parts_map[mission.agent_id]
                    else:
                        p_share = float(instance.part_profil or 0)
                    
                    mission.montant_agence_doit_profil = p_share
                    mission.profil_sera_paye = p_share > 0
                    mission.save()
                elif instance.gesture_type == 'reduction_tarif':
                    # Cas B: Reduced CA
                    pass

            # Send WhatsApp message if configured
            if instance.envoyer_message and 'whatsapp' in (instance.canal_diffusion or []):
                try:
                    client_phone = instance.client.phone if instance.client else None
                    if not client_phone and instance.demande:
                        client_phone = instance.demande.client_phone or instance.demande.client_whatsapp
                    
                    if client_phone:
                        dem = instance.demande
                        client_name = instance.client.display_name if instance.client else (dem.client_name if dem else "Client")
                        demande_service = dem.service if dem else "prestation"
                        type_prestation = dem.service if dem else "Prestation"
                        
                        montant_initial = float(instance.montant_ht or 0)
                        tva_coef = 1.2 if instance.tva_active else 1.0
                        montant_ttc = montant_initial * tva_coef
                        
                        val = float(instance.reduction_value or 0)
                        
                        if instance.gesture_type in ['facturation_annulee', 'intervention_gratuite']:
                            montant_reduction = montant_ttc
                            taux_reduction = 100.0
                        else:
                            if instance.reduction_type == 'pourcentage':
                                taux_reduction = val
                                montant_reduction = montant_ttc * (val / 100.0)
                            else:
                                montant_reduction = val
                                if montant_ttc > 0:
                                    taux_reduction = (val / montant_ttc) * 100.0
                                else:
                                    taux_reduction = 0.0
                                    
                        nouveau_montant = float(instance.total_a_payer or 0)
                        collaborateur_name = instance.cree_par.full_name if instance.cree_par else "Moussa"
                        
                        vars = [
                            client_name,
                            demande_service,
                            f"{taux_reduction:.0f}",
                            type_prestation,
                            f"{montant_ttc:.0f}",
                            f"{montant_reduction:.0f}",
                            f"{taux_reduction:.0f}",
                            f"{nouveau_montant:.0f}",
                            collaborateur_name
                        ]
                        
                        from demandes.utils.whatsapp import WhatsAppService
                        WhatsAppService.send_template_message(
                            to=client_phone,
                            template_name='geste_commercial_client',
                            variables=vars
                        )
                except Exception as wa_err:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Erreur lors de l'envoi auto de geste WA : {str(wa_err)}")

class CampaignViewSet(viewsets.ModelViewSet):
    from accounts.permissions import RoleBasedPermission
    queryset = Campaign.objects.all().order_by('-created_at')
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated, RoleBasedPermission]
