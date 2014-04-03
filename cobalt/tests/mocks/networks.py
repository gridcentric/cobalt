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

from nova.network import model as network_model

from cobalt.tests import utils

class Network(object):

    def __init__(self, context, network_api, name=None, ips=None, cidr=None):

        self._name = name or utils.create_uuid()
        self._available_ips = ips or  ['10.0.0.10', '10.0.0.11', '10.0.0.12',
                                       '10.0.0.13', '10.0.0.14', '10.0.0.15']
        self._cidr = cidr or '10.0.0.0/24'
        self._context = context
        self._network_api = network_api

    def create(self):
        networks = self._network_api._networks.get(self._context.project_id)
        if networks is None:
            networks = {}
            self._network_api._networks[self._context.project_id] = networks

        networks[self._name] = self
        return self

    def allocate_for_instance(self):

        allocated_ip = self._available_ips.pop()
        subnet = network_model.Subnet(cidr=self._cidr,
                                      ips=[network_model.FixedIP(
                                                address=allocated_ip)])
        return network_model.VIF(id=0, address='aa:bb:cc:dd:ee',
                                network={'label': self._name,
                                         'id': self._name,
                                         'subnets': [subnet]})

class MockNetworkApi(object):

    def __init__(self):
        self._networks = {}
        self._instance_networks = {}


    def _project_networks(self,context):

        networks = self._networks.get(context.project_id, None)
        if networks is None:
            network = Network(context, self).create()
            networks = {network._name: network}

        return networks

    def allocate_for_instance(self, context, instance, vpn=False,
                              requested_networks=None, conductor_api=None):
        # Ensure that the conductor_api is passed in.
        assert conductor_api is not None

        project_networks = self._project_networks(context)
        if requested_networks is None:
            # Use all the networks for this project.
            requested_networks = project_networks.keys()
        else:
            requested_networks = [net[0] for net in requested_networks]

        # Enusre that all of the requested networks are associated with
        # the instance's project.
        network_info = network_model.NetworkInfo()
        for net in requested_networks:
            assert net in project_networks
            network = project_networks[net]
            vif = network.allocate_for_instance()

            network_info.append(vif)

        self._instance_networks[instance['uuid']] = network_info
        return network_info

    def get_instance_nw_info(self, context, instance):
        return self._instance_networks.get(instance['uuid'],
                                network_model.NetworkInfo())


    def setup_networks_on_host(self, context, instance, host=None):
        pass
