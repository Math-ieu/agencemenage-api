from django.db import models
from missions.models import Mission
from clients.models import Client
from demandes.models import Demande


class Feedback(models.Model):
    mission = models.OneToOneField(Mission, on_delete=models.CASCADE, related_name='feedback', null=True, blank=True)
    demande = models.ForeignKey(Demande, on_delete=models.CASCADE, related_name='feedbacks', null=True, blank=True)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Ratings
    note = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)], null=True, blank=True) # Overall or Intervenant
    note_intervenant = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)], null=True, blank=True)
    note_agence = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)], null=True, blank=True)
    
    commentaire = models.TextField(blank=True)
    opt_out = models.BooleanField(default=False)
    
    date = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=50, default='backoffice')  # 'client' | 'backoffice'

    class Meta:
        verbose_name = 'Feedback'
        verbose_name_plural = 'Feedbacks'
        ordering = ['-date']

    def __str__(self):
        n = self.note_intervenant or self.note or "?"
        return f"Feedback {n}/5 — {self.demande or self.mission}"
