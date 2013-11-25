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


from nova.virt.xenapi import driver
from nova.virt.xenapi import vmops
from nova.virt.xenapi import vm_utils

class CobaltVmOps(vmops.VMOps):

    def __init__(self, session, virtapi):
        super(CobaltVmOps, self).__init__(session, virtapi)

    def _create_vm_record(self, context, instance, name_label, vdis,
                          disk_image_type, kernel_file, ramdisk_file):
        vm_ref = super(CobaltVmOps, self)._create_vm_record(context,
                                                            instance,
                                                            name_label,
                                                            vdis,
                                                            disk_image_type,
                                                            kernel_file,
                                                            ramdisk_file)

        # (dscannell): Set other_config:xenops=org.xen.xcp.xenops.classic on
        # the instance to ensure that xenguest is used to perform operations
        # on it.
        other_config = self._session.call_xenapi('VM.get_other_config', vm_ref)
        other_config['xenops'] = 'org.xen.xcp.xenops.classic'
        self._session.call_xenapi('VM.set_other_config', vm_ref, other_config)

        # (dscannell): We set the min / max memory of the instance to be equal
        # to the instance's memory. This is to prevent the instance from
        # ballooning, which may confuse vmsd.
        memory_max = self._session.call_xenapi('VM.get_memory_static_max',
                                               vm_ref)
        self._session.call_xenapi('VM.set_memory_dynamic_max',
                                  vm_ref,
                                  memory_max)
        self._session.call_xenapi('VM.set_memory_dynamic_min',
                                  vm_ref,
                                  0)

        return vm_ref

    def find_sr_uuid(self):
        default_sr_ref = vm_utils.safe_find_sr(self._session)
        default_sr_rec =self._session.call_xenapi('SR.get_record',
                                                  default_sr_ref)
        return default_sr_rec['uuid']

class XenApiDriver(driver.XenAPIDriver):

    def __init__(self, virtapi, read_only=False):
        super(XenApiDriver, self).__init__(virtapi, read_only=read_only)

        # The _vmops object does most of the work when spawning an instance
        # and we need to intercept calls within to do proper booting and
        # launching.
        self._vmops = CobaltVmOps(self._session, self.virtapi)


    def bless(self, context, vmsapi, instance_name, new_instance,
              migration_url=None):


        return vmsapi.bless(instance_name,
                            new_instance['name'],
                            path=self._vmops.find_sr_uuid(),
                            mem_url=migration_url,
                            migration=migration_url and True)

    def launch(self, context, vmsapi, instance_name, new_instance, target, path,
               mem_url=None, migration=False, guest_params=None,
               vms_options=None):


        return vmsapi.launch(instance_name, new_instance['name'], target,
                             path, mem_url=mem_url, migration=migration,
                             guest_params=guest_params, vms_options=vms_options)