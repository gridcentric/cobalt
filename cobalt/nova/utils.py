
# Copyright 2011 Gridcentric Inc.
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

from nova.openstack.common import importutils
from oslo.config import cfg

CONF = cfg.CONF
CONF.import_opt('network_api_class', 'nova.network')

_IS_QUANTUM_ATTEMPTED = False
_IS_QUANTUM = False

def is_quantum():

    # NOTE (dscannell): at some time during Grizzly release this code was added
    #                   to nova.utils. Unfortunately, not all version of grizzly
    #                   have access to it, so we reproduced it here. This can
    #                   probably be cleaned up and removed in Havana
    global _IS_QUANTUM_ATTEMPTED
    global _IS_QUANTUM

    if _IS_QUANTUM_ATTEMPTED:
        return _IS_QUANTUM

    try:
        cls_name = CONF.network_api_class
        _IS_QUANTUM_ATTEMPTED = True

        from nova.network.quantumv2 import api as quantum_api
        _IS_QUANTUM = issubclass(importutils.import_class(cls_name),
            quantum_api.API)
    except ImportError:
        _IS_QUANTUM = False

    return _IS_QUANTUM