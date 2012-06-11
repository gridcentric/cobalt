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
import logging

import gridcentric.nova.client.exceptions as exceptions

class NovaClient(httplib2.Http):

    USER_AGENT = "gridcentric-novaclient"

    def __init__(self, auth_url, user, apikey, project=None, default_version='v1.0', region=None):
        super(NovaClient, self).__init__()

        self.auth_url = auth_url
        self.user = user
        self.apikey = apikey
        self.project = project
        self.region = region

        self.version = None
        self.default_version = 'v1.0'
        self.auth_token = None
        self.management_url = None

        # Need to set for the httplib2 library.
        self.force_exception_to_status_code = True

    def bless_instance(self, instance_id):
        resp, body = self.authenticated_request('/servers/%s/action' % instance_id,
                                                'POST', body={'gc_bless':{}})
        return body

    def launch_instance(self, blessed_instance_id, params={}):
        resp, body = self.authenticated_request('/servers/%s/action' % blessed_instance_id,
                                                'POST', body={'gc_launch':params})
        return body

    def migrate_instance(self, instance_id, dest):
        resp, body = self.authenticated_request('/servers/%s/action' % instance_id,
                                                'POST', body={'gc_migrate':{'dest':str(dest)}})
        return body

    def delete_instance(self, instance_id):
        resp, body = self.authenticated_request('/servers/%s' % instance_id, 'DELETE')
        return body

    def discard_instance(self, instance_id):
        resp, body = self.authenticated_request('/servers/%s/action' % instance_id,
                                                'POST', body={'gc_discard':{}})
        return body

    def list_launched_instances(self, instance_id):
        resp, body = self.authenticated_request('/servers/%s/action' % instance_id,
                                                'POST', body={'gc_list_launched':{}})
        return body

    def list_blessed_instances(self, instance_id):
        resp, body = self.authenticated_request('/servers/%s/action' % instance_id,
                                                'POST', body={'gc_list_blessed':{}})
        return body

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

            logging.debug("Sending request to %s (body=%s)" % (url, kwargs.get('body', '')))
            resp, body = self.request(self.management_url + url, method,
                                      **kwargs)
            logging.debug("Response from %s (body=%s)" % (url, body))
            return resp, body
        except exceptions.HttpException, ex:
            if ex.code == 401:
                """
                This is an unauthorized exception. Reauthenticate and try again
                """
                self._authenticate()
                logging.debug("Sending request to %s (body=%s) [REAUTHENTICATED]" % (url, kwargs['body']))
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
                logging.warn("Request (%s) body failed to be parsed as json: body='%s'" % (args[0], body))
                pass
        else:
            body = None

        if resp.status in (400, 401, 403, 404, 408, 413, 500, 501):
            raise create_exception_from_response(resp, body)

        return resp, body

    def determine_version(self):
        if self.version == None:
            magic_tuple = urlparse.urlsplit(self.auth_url)
            scheme, netloc, path, query, frag = magic_tuple
            path_parts = path.split('/')
            for part in path_parts:
                if len(part) > 0 and part[0] == 'v':
                    self.version = part
                    return
            self.version = self.default_version

    def _authenticate(self):
        """
        Authenticates the client against the nova server
        """

        self.determine_version()
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

        if self.project:
            body['auth']['tenantName'] = self.project

        token_url = url + "/tokens"
        resp, body = self.request(token_url, "POST", body=body)
        return self._extract_service_catalog(url, resp, body)

    def _extract_service_catalog(self, url, resp, body):
        """See what the auth service told us and process the response.
        We may get redirected to another site, fail or actually get
        back a service catalog with a token and our endpoints."""

        if resp.status == 200:  # content must always present
            try:
                self.auth_url = url
                service_catalog = ServiceCatalog(body)
                self.auth_token = service_catalog.get_token()

                self.management_url = service_catalog.url_for(
                                           attr='region',
                                           filter_value=self.region)
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
