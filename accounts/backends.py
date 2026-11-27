from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

class EmailOrUsernameModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        
        if not username:
            return None

        try:
            # Check either email or username case-insensitively
            user = UserModel.objects.filter(
                Q(email__iexact=username) | Q(username__iexact=username)
            ).first()
        except UserModel.DoesNotExist:
            return None
        
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
