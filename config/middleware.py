import contextvars

_current_user = contextvars.ContextVar('current_user', default=None)

def get_current_user():
    user = _current_user.get()
    if user and user.is_authenticated:
        return user
    return None

def set_current_user(user):
    _current_user.set(user)

class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, 'user') and request.user.is_authenticated:
            set_current_user(request.user)
        else:
            set_current_user(None)

        response = self.get_response(request)

        # Clear contextvar after request finishes
        set_current_user(None)
        return response
