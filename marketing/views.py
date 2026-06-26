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

    from rest_framework.decorators import action

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        campaign = self.get_object()
        
        # Check channels
        channels = campaign.channel or []
        if not isinstance(channels, list):
            channels = [channels]

        if "email" not in channels:
            return Response(
                {"success": False, "message": "Cette campagne ne cible pas le canal email."},
                status=status.HTTP_400_BAD_REQUEST
            )

        from clients.models import Client
        from agents.models import Agent
        from accounts.emails import send_resend_email, get_base_html_template
        from django.db.models import Count
        from django.utils import timezone
        from datetime import timedelta

        sent_count = 0
        failed_count = 0

        # Subject and body
        subject = campaign.title
        # Convert newlines to <br> for HTML rendering in email template
        html_body = campaign.message.replace("\n", "<br>")

        if campaign.target == 'client':
            recipients = Client.objects.filter(is_archived=False, is_blacklisted=False).exclude(email="")
            if campaign.segment == 'particulier':
                recipients = recipients.filter(segment=Client.PARTICULIER)
            elif campaign.segment == 'entreprise':
                recipients = recipients.filter(segment=Client.ENTREPRISE)

            if campaign.criteria == 'nouveau':
                recipients = recipients.filter(created_at__gte=timezone.now() - timedelta(days=30))
            elif campaign.criteria == 'abonne':
                recipients = recipients.filter(demandes__frequence='abonnement').distinct()
            elif campaign.criteria == 'regulier':
                recipients = recipients.annotate(num_demandes=Count('demandes')).filter(num_demandes__gte=2)
            elif campaign.criteria == 'inactif':
                cutoff = timezone.now() - timedelta(days=60)
                recipients = recipients.exclude(demandes__created_at__gte=cutoff)

            if campaign.city:
                recipients = recipients.filter(city__iexact=campaign.city)

            for client in recipients:
                html_content = get_base_html_template(subject, html_body)
                success = send_resend_email(client.email, subject, html_content)
                if success:
                    sent_count += 1
                else:
                    failed_count += 1

        elif campaign.target == 'profil':
            recipients = Agent.objects.filter(is_archived=False, is_blacklisted=False).exclude(email="")
            if campaign.criteria == 'femme_de_menage':
                recipients = recipients.filter(poste='femme_menage')
            elif campaign.criteria == 'garde_malade':
                recipients = recipients.filter(poste='garde_malade')
            elif campaign.criteria == 'auxiliaire_vie':
                recipients = recipients.filter(poste='auxiliaire_vie')
            elif campaign.criteria == 'nounou':
                recipients = recipients.filter(poste='nounou')

            if campaign.city:
                recipients = recipients.filter(city__iexact=campaign.city)

            for agent in recipients:
                html_content = get_base_html_template(subject, html_body)
                success = send_resend_email(agent.email, subject, html_content)
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
        
        # Update campaign status
        campaign.status = 'envoyee'
        campaign.broadcast_date = timezone.localdate()
        campaign.save()

        return Response({
            "success": True,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "message": f"Campagne envoyée avec succès à {sent_count} destinataire(s)."
        }, status=status.HTTP_200_OK)


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone

class PublicPromoCodeValidateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        code_str = request.data.get('code', '').strip()
        segment = request.data.get('segment', '').strip()
        service = request.data.get('service', '').strip()
        phone = request.data.get('phone', '').strip()

        if not code_str:
            return Response(
                {"valid": False, "message": "Veuillez saisir un code promo."},
                status=status.HTTP_400_BAD_REQUEST
            )

        promo = PromoCode.objects.filter(code__iexact=code_str, archived=False).first()
        if not promo:
            return Response(
                {"valid": False, "message": "Ce code promo n'existe pas ou est invalide."},
                status=status.HTTP_404_NOT_FOUND
            )

        if promo.status != 'active':
            return Response(
                {"valid": False, "message": "Ce code promo n'est pas actif."},
                status=status.HTTP_400_BAD_REQUEST
            )

        today = timezone.localdate()
        if promo.valid_from > today:
            return Response(
                {"valid": False, "message": "Ce code promo n'est pas encore valide."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if promo.valid_until and promo.valid_until < today:
            return Response(
                {"valid": False, "message": "Ce code promo a expiré."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Segment check
        if promo.segment != 'tous' and segment:
            if promo.segment == 'particulier' and segment != 'particulier':
                return Response(
                    {"valid": False, "message": "Ce code promo est réservé aux particuliers."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            elif promo.segment == 'entreprise' and segment != 'entreprise':
                return Response(
                    {"valid": False, "message": "Ce code promo est réservé aux entreprises."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Service check
        if promo.services and isinstance(promo.services, list) and len(promo.services) > 0:
            import unicodedata
            def clean_service(s):
                if not s:
                    return ""
                s = s.lower().strip()
                s = "".join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
                s = s.replace("nettoyage", "menage")
                s = s.replace("air bnb", "airbnb")
                s = s.replace("garde malade", "auxiliaire de vie")
                s = s.replace("placement & gestion", "placement")
                s = s.replace("placement et gestion", "placement")
                return "".join(c for c in s if c.isalnum())

            cleaned_services = [clean_service(srv) for srv in promo.services]
            cleaned_input_service = clean_service(service)

            if not service or cleaned_input_service not in cleaned_services:
                return Response(
                    {"valid": False, "message": "Ce code promo n'est pas applicable à ce service."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Target client check for BD promo codes
        if promo.promo_type == 'bd':
            if not phone:
                return Response(
                    {"valid": False, "message": "Veuillez renseigner votre téléphone pour appliquer ce code."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            is_valid_target, target_msg = promo.matches_phone(phone)
            if not is_valid_target:
                return Response(
                    {"valid": False, "message": target_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Usage limit validation
        if promo.limit_uses is not None and promo.uses >= promo.limit_uses:
            return Response(
                {"valid": False, "message": "Ce code promo a atteint sa limite d'utilisation."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # One use per client check
        if promo.one_use_per_client and phone:
            from clients.models import Client
            phone_clean = phone.strip()
            phone_no_spaces = phone_clean.replace(" ", "")
            
            client = Client.objects.filter(phone=phone_clean, is_archived=False).order_by('-created_at').first()
            if not client:
                client = Client.objects.filter(phone=phone_no_spaces, is_archived=False).order_by('-created_at').first()
                
            if client and client.demandes.filter(promo_code=promo).exists():
                return Response(
                    {"valid": False, "message": "Vous avez déjà utilisé ce code promo."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        return Response({
            "valid": True,
            "id": promo.id,
            "code": promo.code,
            "name": promo.name,
            "reduction": float(promo.reduction),
            "reduction_type": promo.reduction_type,
            "promo_type": promo.promo_type,
            "message": "Code promo valide !"
        }, status=status.HTTP_200_OK)

