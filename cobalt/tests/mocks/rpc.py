# Copyright 2014 Gridcentric Inc.
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

from nova.compute import rpcapi as compute_rpc

from cobalt.nova import rpcapi as cobalt_rpc

class RpcRequest(object):

    def __init__(self, server, version, timeout):
        self._server = server
        self._version = version
        self._timout = timeout

        self._is_call = False
        self._is_cast = False
        self._method = None
        self._kw = None

    def cast(self, context, method, **kwargs):
        self._is_cast = True
        self._method = method
        self._kw = kwargs

    def call(self, context, method, **kwargs):
        self._is_call = True
        self._method = method
        self._kw = kwargs

class MockRpcClient(object):

    def __init__(self):
        self._rpc_requests = []

    def prepare(self, server=None, version=None, timeout=None):
        rpc_request = RpcRequest(server, version, timeout)
        self._rpc_requests.append(rpc_request)
        return rpc_request


    def can_send_version(self, version):
        return True

class MockCobaltRpcApi(cobalt_rpc.CobaltRpcApi):

    def _create_client(self):
        return MockRpcClient()

    def num_rpc_requests(self):
        return len(self.client._rpc_requests)

    def rpc_requests(self):
        return self.client._rpc_requests

class MockComputeRpcApi(compute_rpc.ComputeAPI):

    def get_client(self, target, version_cap, serializer):
        return MockRpcClient()
