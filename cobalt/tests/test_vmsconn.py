# Copyright 2013 GridCentric Inc.
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
import cobalt.nova.extension.vmsconn as vms_conn

class CobaltVmsConnTestCase(unittest.TestCase):

    def setUp(self):
        self.vmsconn = vms_conn.get_vms_connection('fake')

    def test_glance_appearance(self):
        expected_results = {('hello','instance-00000001.gc') : ('hello','Live-Image'),
                            ('hello','instance-00000001.xml') : ('hello.xml','Image'),
                            ('hello','instance-00000001.0.disk') : ('hello.0.disk','Image'),
                            ('hello','instance-00000001.1.disk') : ('hello.1.disk','Image'),
                            ('hello','instance-00000001.789.disk') : ('hello.789.disk','Image'),
                            ('A.1','instance-aaaaa.gc') : ('A.1','Live-Image'),
                            ('A.1','instance-aaaaa.xml') : ('A.1.xml','Image'),
                            ('A.1','instance-aaaaa.0.disk') : ('A.1.0.disk','Image'),
                            ('A.1','instance-aaaaa.1.disk') : ('A.1.1.disk','Image'),
                            ('A.1','instance-aaaaa.00000001.789.disk') : ('A.1.789.disk','Image'),
                            ('no_extension','instance') : ('no_extension', 'Image'),
                            ('not-a-disk','instance.0.disk.no') : ('not-a-disk.no', 'Image'),
                            ('not-a-disk','instance.diskdisk') : ('not-a-disk.diskdisk','Image'),
                            ('spaces','file has space.ext') : ('spaces.ext','Image'),
                            ('spaces','file ends space .ext') : ('spaces.ext','Image'),
                            ('spaces','ext has space. ext') : ('spaces. ext','Image'),
                            ('spaces','ext ends in space.ext ') : ('spaces.ext ','Image')
                            }

        for (display_name, file_name), (expected_name, expected_type) in expected_results.iteritems():
            instance_ref = {'display_name':display_name}
            image_name, image_type = self.vmsconn._get_glance_displayname_and_type(instance_ref, file_name)
            self.assertEqual(image_name, expected_name)
            self.assertEqual(image_type, expected_type)

