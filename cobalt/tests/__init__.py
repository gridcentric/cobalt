# Copyright 2011 Gridcentric Inc.
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

import os
import shutil
import tempfile
import stat

def tmpfs_tmp_dir():
    path = '/dev/shm/'
    if os.path.isdir(path) and \
       stat.S_IMODE(os.stat(path).st_mode) == 01777:
        return path
    else:
        return tempfile.tmpdir

def setup():

    sqlite_db = "tests.sqlite"
    # Set COBALT_TESTS_TMPFS to a tmpfs mount for faster setup. The fsyncs that
    # sqlite does nops :-)

    state_path = tempfile.mkdtemp(dir=tmpfs_tmp_dir(), prefix='cobalt.tests.')
    testdb = os.path.join(state_path, sqlite_db)
    if os.path.exists(testdb):
        os.unlink(testdb)

    from oslo.config import cfg
    from nova.db import migration

    test_opts = [
                 cfg.StrOpt('sqlite_clean_db',
                 default='tests.clean.sqlite',
                 help='File name of clean sqlite db') ]

    CONF = cfg.CONF
    CONF.register_opts(test_opts)
    CONF.import_opt('connection', 'nova.openstack.common.db.sqlalchemy.session',
                    group='database')

    CONF.sqlite_db = sqlite_db
    CONF.state_path = state_path
    CONF.sql_connection = 'sqlite:///%s' % testdb
    CONF.set_override('connection', CONF.sql_connection, group='database')
    CONF.database.connection = CONF.sql_connection

    print CONF.sqlite_clean_db
    migration.db_sync()

    cleandb = os.path.join(CONF.state_path, CONF.sqlite_clean_db)
    shutil.copyfile(testdb, cleandb)

def teardown():
    from oslo.config import cfg
    shutil.rmtree(cfg.CONF.state_path)
