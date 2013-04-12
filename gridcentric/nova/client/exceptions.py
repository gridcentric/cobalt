# Copyright 2011 GridCentric Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

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
