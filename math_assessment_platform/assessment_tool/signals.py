from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    # Update the user record with the new session key
    user.last_session_key = request.session.session_key
    user.save(update_fields=['last_session_key'])