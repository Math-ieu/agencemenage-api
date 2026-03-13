from django.db import models
from missions.models import Mission
from clients.models import Client


class Feedback(models.Model):
    mission = models.OneToOneField(Mission, on_delete=models.CASCADE, related_name='feedback')
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    commentaire = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=50, default='backoffice')  # 'client' | 'backoffice'

    class Meta:
        verbose_name = 'Feedback'
        verbose_name_plural = 'Feedbacks'
        ordering = ['-date']

    def __str__(self):
        return f"Feedback {self.note}/5 — {self.mission}"
