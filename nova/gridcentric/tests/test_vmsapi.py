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



import unittest
import gridcentric.nova.extension.vmsapi as vms_api


class GridCentricApiTestCase(unittest.TestCase):

    def setUp(self):
        self.vmsapi = vms_api.get_vmsapi()
        self.vmsapi.select_hypervisor('dummy')

    def test_config(self):
        # Simply verify that we can push a value into the config Management
        config = self.vmsapi.config()
        config.MANAGEMENT['test-value'] = "testvalue"
