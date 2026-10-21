"""api/auth/errors.py -- one error type for every way a sign-in or a token can fail. The message is a fixed code, never text from the token."""


class AuthError(Exception):
    def __init__(self, code, status=401):
        super().__init__(code)
        self.code = code
        self.status = status
