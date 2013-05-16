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

from nova import exception
from nova.image import glance
from nova.openstack.common import log as logging
from nova.virt.libvirt import driver

from cobalt.nova.extension import vmsconn
from cobalt.nova.extension import vmsapi

LOG = logging.getLogger('nova.cobalt.driver.libvirt')

class LibvirtDriver(driver.LibvirtDriver):

    def __init__(self, read_only=False):
        super(LibvirtDriver, self).__init__(read_only=read_only)

        self.vms_conn = vmsconn.LibvirtConnection(vmsapi.get_vmsapi())
        self.vms_conn.configure()

    @exception.wrap_exception()
    def spawn(self, context, instance, image_meta, injected_files,
        admin_password, network_info=None, block_device_info=None):

        image_properties = image_meta.get('properties', {})
        is_live_image = 'live_image' in image_properties

        if not is_live_image:
            # This is not a cobalt image, pass through to boot
            return super(LibvirtDriver, self).spawn(context, instance,
                    image_meta, injected_files, admin_password, network_info,
                    block_device_info)

        LOG.debug("Spawning from a live-image. "
                  "Performing launch instead of boot")

        # The master live image is the vms descriptor file that has
        # references to potentially related files in its metadata
        # (e.g. disk files, separate memory, etc). We need to
        # download this entire set of images from glance.

        LOG.debug('image_properties=%s' %(image_properties))

        if instance['instance_type_id'] != \
                int(image_properties['instance_type_id']):
            # TODO(dscannell): We might want to look into booting the live
            # image and then doing a resize to the new image_type_id
            raise Exception("Unable to boot a live image with a different"
                            " instance_type_id")
        image_refs = [image_meta['id']]
        for image_prop, value in image_properties.iteritems():
            # The descriptor's image properties contain key-value pairs in
            # the form 'live_image_[image_type]' = Glance uuid of image. For
            # example it might have:
            #   live_image_data_disk.0 = uuid1
            #   live_image_data_disk.1 = uuid2
            #   live_image_data_memory = uuid3
            # We collect all of these uuids so that they can all be retrieved
            # from Glance.
            if image_prop.startswith('live_image_data_'):
                image_refs.append(value)

        blessed_instance_name = image_properties.get('live_image_source', None)
        LOG.debug('network_info=%s' %(network_info))
        self.ensure_filtering_rules_for_instance(instance, network_info)

        vms_policy_template = image_properties.get('vms_policy_template', '')
        vms_policy = vms_policy_template % ({'uuid':instance['uuid'],
                                             'tenant': instance['project_id']})

        self.vms_conn.launch(context, blessed_instance_name, instance,
                network_info,image_refs=image_refs, vms_policy=vms_policy)
