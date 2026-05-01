from django.contrib.auth import logout
from django.shortcuts import redirect
from django.contrib import messages

class OneSessionPerUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            ###############
            # force user to authenticate email before navigating elsewhere
            ###############
            # Check if account is unactivated
            if request.user.unactivated_account:
                # Define paths that are ALLOWED (use the actual URL paths)
                # Adjust these strings to match your actual URLs in urls.py
                allowed_paths = ['/verify/', '/logout/', '/logout', '/verify']
                
                # If the current path is NOT in our allowed list, force redirect
                if request.path_info not in allowed_paths:
                    return redirect('verify_email')

            ###############
            # single sign on logic follows
            ###############
            stored_session_key = request.user.last_session_key
            
            # If a session exists in DB and doesn't match current browser session
            if stored_session_key and request.session.session_key != stored_session_key:
                # 1. Add the message FIRST while the session is still active
                if hasattr(request, '_messages'):
                    messages.error(request, "You have been logged out because someone else logged in from another device.")
                
                # 2. Log out (this clears the current session)
                logout(request)
                
                # 3. Redirect
                return redirect('login')

        return self.get_response(request)