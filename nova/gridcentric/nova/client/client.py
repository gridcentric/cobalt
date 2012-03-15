# Copyright 2011, GridCentric
#
# Portions of this file are taken from python-novaclient:
#
# Copyright 2011 OpenStack LLC.
# Copyright 2011, Piston Cloud Computing, Inc.
#
# All Rights Reserved.

"""
The client connector used to interface with the nova api.
"""

import httplib2
import json
import urlparse

import gridcentric.nova.client.exceptions as exceptions

class NovaClient(httplib2.Http):
    
    USER_AGENT="gridcentric-novaclient"
    
    def __init__(self, auth_url, user, apikey, project=None, version='v1.0'):
        super(NovaClient, self).__init__()
        
        self.auth_url = auth_url
        self.user = user
        self.apikey = apikey
        self.project = project
        
        self.version = version
        self.auth_token = None
        self.management_url = None
        
        # Need to set for the httplib2 library.
        self.force_exception_to_status_code = True

    def bless_instance(self, instance_id):
        self.authenticated_request('/servers/%s/action' % instance_id,
                                   'POST', body={'gc_bless':{}})

    def launch_instance(self, blessed_instance_id):
        self.authenticated_request('/servers/%s/action' % blessed_instance_id,
                                   'POST', body={'gc_launch':{}})

    def delete_instance(self, instance_id):
        self.authenticated_request('/servers/%s' % instance_id, 'DELETE')

    def discard_instance(self, instance_id):
        self.authenticated_request('/servers/%s/action' % instance_id,
                                   'POST', body={'gc_discard':{}})

    def list_launched_instances(self, blessed_instance_id):
        resp, body = self.authenticated_request('/servers/%s/action' % blessed_instance_id,
                                                'POST', body={'gc_list_launched':{}})
        return body.get('instances', [])

    def authenticated_request(self, url, method, **kwargs):
        if not self.management_url:
            self._authenticate()
        
        # Perform the request once. If we get a 401 back then it
        # might be because the auth token expired, so try to
        # re-authenticate and try again. If it still fails, bail.
        try:
            kwargs.setdefault('headers', {})['X-Auth-Token'] = self.auth_token
            if self.project:
                kwargs['headers']['X-Auth-Project-Id'] = self.project

            resp, body = self.request(self.management_url + url, method,
                                      **kwargs)
            return resp, body
        except exceptions.HttpException, ex:
            if ex.code == 401:
                """
                This is an unauthorized exception. Reauthenticate and try again
                """ 
                self._authenticate()
                resp, body = self.request(self.management_url + url, method,
                                          **kwargs)
                return resp, body
            else:
                raise ex

    def request(self, *args, **kwargs):
        kwargs.setdefault('headers', kwargs.get('headers', {}))
        kwargs['headers']['User-Agent'] = self.USER_AGENT
        if 'body' in kwargs:
            kwargs['headers']['Content-Type'] = 'application/json'
            kwargs['body'] = json.dumps(kwargs['body'])

        resp, body = super(NovaClient, self).request(*args, **kwargs)

        if body:
            try:
                body = json.loads(body)
            except ValueError, e:
                pass
        else:
            body = None

        if resp.status in (400, 401, 403, 404, 408, 413, 500, 501):
            raise create_exception_from_response(resp, body)

        return resp, body

    def _authenticate(self):
        """
        Authenticates the client against the nova server
        """
        auth_url = self.auth_url
        if self.version == "v2.0":
            while auth_url:
                auth_url = self._v2_auth(auth_url)

        else:
            try:
                while auth_url:
                    auth_url = self._v1_auth(auth_url)
            # In some configurations nova makes redirection to
            # v2.0 keystone endpoint. Also, new location does not contain
            # real endpoint, only hostname and port.
            except exceptions.AuthorizationFailure:
                if auth_url.find('v2.0') < 0:
                    auth_url = urlparse.urljoin(auth_url, 'v2.0/')
                self._v2_auth(auth_url)

    def _v1_auth(self, url):
        headers = {'X-Auth-User': self.user,
                   'X-Auth-Key': self.apikey}

        if self.project:
            headers['X-Auth-Project-Id'] = self.project

        resp, body = self.request(url, 'GET', headers=headers)
        if resp.status in (200, 204):
            try:
                self.management_url = resp['x-server-management-url']
                self.auth_token = resp['x-auth-token']
                self.auth_url = url
            except KeyError:
                raise exceptions.AuthorizationFailure()
        elif resp.status == 305:
            return resp['location']
        else:
            raise create_exception_from_response(resp, body)

    def _v2_auth(self, url):
        """Authenticate against a v2.0 auth service."""
        body = {"auth": {
                   "passwordCredentials": {"username": self.user,
                                           "password": self.apikey}}}

        if self.projectid:
            body['auth']['tenantName'] = self.projectid

        token_url = urlparse.urljoin(url, "tokens")
        resp, body = self.request(token_url, "POST", body=body)
        return self._extract_service_catalog(url, resp, body)

    def _extract_service_catalog(self, url, resp, body):
        """See what the auth service told us and process the response.
        We may get redirected to another site, fail or actually get
        back a service catalog with a token and our endpoints."""

        if resp.status == 200:  # content must always present
            try:
                self.auth_url = url
                service_catalog = service_catalog.ServiceCatalog(body)
                self.auth_token = service_catalog.get_token()

                self.management_url = self.service_catalog.url_for(
                                           attr='region',
                                           filter_value=self.region_name)
                return None
            except KeyError:
                raise exceptions.AuthorizationFailure()
            except exceptions.EndpointNotFound:
                print "Could not find any suitable endpoint. Correct region?"
                raise

        elif resp.status == 305:
            return resp['location']
        else:
            raise create_exception_from_response(resp, body)

def create_exception_from_response(resp, body):
    message = None
    details = None
    if body and hasattr(body, 'keys'):
        error = body[body.keys()[0]]
        message = error.get('message', None)
        details = error.get('details', None)
        
    return exceptions.HttpException(code=resp.status, message=message, details=details)

class ServiceCatalog:
    """Helper methods for dealing with a Keystone Service Catalog."""

    def __init__(self, resource_dict):
        self.catalog = resource_dict

    def get_token(self):
        return self.catalog['access']['token']['id']

    def url_for(self, attr=None, filter_value=None):
        """Fetch the public URL from the Compute service for
        a particular endpoint attribute. If none given, return
        the first. See tests for sample service catalog."""
        catalog = self.catalog['access']['serviceCatalog']

        for service in catalog:
            if service['type'] != 'compute':
                continue

            endpoints = service['endpoints']
            for endpoint in endpoints:
                if filter_value == None or endpoint[attr] == filter_value:
                    return endpoint['publicURL']

        raise exceptions.EndpointNotFound()
