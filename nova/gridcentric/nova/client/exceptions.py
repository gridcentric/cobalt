"""
Exceptions used by the scale manager
"""

class AuthorizationFailure(Exception):
    pass

class EndpointNotFound(Exception):
    """Could not find Service or Region in Service Catalog."""
    pass

class HttpException(Exception):
    def __init__(self, code, message=None, details=None):
        self.code = code
        self.message = message or ''
        self.deatils = details
        
    def __str__(self):
        return "(HTTP %s) %s)" % (self.code, self.message)
