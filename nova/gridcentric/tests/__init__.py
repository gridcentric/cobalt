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

def setup():
    import os
    import shutil

    from nova import flags
    from nova.db import migration

    FLAGS = flags.FLAGS
    
    flags.DEFINE_string('sqlite_clean_db', 'tests.clean.sqlite',
                    'File name of clean sqlite db')
    
    FLAGS.sqlite_db = "tests.sqlite"
    FLAGS.state_path = "/tmp"
    testdb = os.path.join(FLAGS.state_path, FLAGS.sqlite_db)
    FLAGS.sql_connection = 'sqlite:///%s' % testdb
    
    print FLAGS.sql_connection
    if os.path.exists(testdb):
        os.unlink(testdb)
    migration.db_sync()

    cleandb = os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db)
    shutil.copyfile(testdb, cleandb)
