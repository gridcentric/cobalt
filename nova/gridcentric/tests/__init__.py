# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 GridCentric Inc.
# All Rights Reserved.
#
# Originally from the OpenStack project:
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import tempfile

def setup():
    import os
    import shutil

    sqlite_db = "tests.sqlite"
    state_path = tempfile.mkdtemp()
    testdb = os.path.join(state_path, sqlite_db)
    if os.path.exists(testdb):
        os.unlink(testdb)

    from nova import flags
    from nova.openstack.common import cfg
    from nova.db import migration

    test_opts = [
                 cfg.StrOpt('sqlite_clean_db',
                 default='tests.clean.sqlite',
                 help='File name of clean sqlite db') ]

    FLAGS = flags.FLAGS
    FLAGS.register_opts(test_opts)

    FLAGS.sqlite_db = sqlite_db
    FLAGS.state_path = state_path
    FLAGS.sql_connection = 'sqlite:///%s' % testdb

    print FLAGS.sql_connection
    migration.db_sync()

    cleandb = os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db)
    shutil.copyfile(testdb, cleandb)
