from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from .models import UserProfile

class UsernameOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            # Look for the user where username OR user_email matches the input
            user = UserProfile.objects.get(Q(username__iexact=username) | Q(user_email__iexact=username))
        except UserProfile.DoesNotExist:
            return None

        # Check the password (handles the hashing/verification automatically)
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
    
