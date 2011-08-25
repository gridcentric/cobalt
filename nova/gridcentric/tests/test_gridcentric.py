import unittest
import os
import shutil

from nova import db
from nova.db import migration
from nova import flags
from nova import context

import gridcentric.nova.extension as gridcentric
import gridcentric.nova.extension.manager as gc_manager

import gridcentric.tests.utils as utils

FLAGS = flags.FLAGS

class MockXenAPISession():
    """
    A simple mock class to stub-out interaction with the XenAPI because these tests will likely be
    executed on a machine not running on top of the XenHypervisor. Plus we don't really want to
    be creating virtual machines.
    """

    def __call__(self, *args, **kwargs):
       print "call: %s, %s" % (args, kwargs)
       return self

    def __getattr__(self, value):
       print "get: %s" % value
       return self
   
    def __repr__(self):
        return "MockXenAPISession"


class GridCentricTestCase(unittest.TestCase):

    def setUp(self):

        FLAGS.connection_type='xenapi'
        # Copy the clean database over
        shutil.copyfile(os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db),
                        os.path.join(FLAGS.state_path, FLAGS.sqlite_db))
    
        self.mockXenSession = MockXenAPISession()
        self.gridcentric = gc_manager.GridCentricManager()
        # Mock out the XenAPI session
        self.gridcentric._get_xen_session = self._returnMock
        self.gridcentric_api = gridcentric.API()
        self.context = context.RequestContext('fake', 'fake', True)

    def tearDown(self):
        pass

    def _returnMock(self):
            return self.mockXenSession

    def test_bless_instance(self):
        
        instance_id = utils.create_instance(self.context)
        
        num_instance_before = len( db.instance_get_all(self.context) )
        self.gridcentric.bless_instance(self.context, instance_id)
        
        # Ensure that we have a 2nd instance in the database that is a "clone" of our
        # original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before + 1, 
                        "There should be a single new instance after blessing.")
        # Ensure that we have correctly setup the meta-data on our instance to reflect
        # the generation id (e.g. incremented it)
        metadata = db.instance_metadata_get(self.context, instance_id)
        self.assertEquals(metadata['generation_id'], '0',
                          "The generation id should be 0 because this is the first time the instance " \
                          "was blessed.")
        
    
    def test_bless_instance_twice(self):
        
        instance_id = utils.create_instance(self.context)
        
        num_instance_before = len( db.instance_get_all(self.context) )
        self.gridcentric.bless_instance(self.context, instance_id)
        
        # Ensure that we have a 2nd instance in the database that is a "clone" of our
        # original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before + 1, 
                        "There should be a single new instance after blessing.")
        # Ensure that we have correctly setup the meta-data on our instance to reflect
        # the generation id (e.g. incremented it)
        metadata = db.instance_metadata_get(self.context, instance_id)
        self.assertEquals(metadata['generation_id'], '0',
                          "The generation id should be 0 because this is the first time the instance " \
                          "was blessed.")
        
        self.gridcentric.bless_instance(self.context, instance_id)
        
        # Ensure that we have a 2nd instance in the database that is a "clone" of our
        # original instance.
        instances = db.instance_get_all(self.context)
        self.assertTrue(len(instances) == num_instance_before + 2, 
                        "There should be two new instance after blessing twice.")
        # Ensure that we have correctly setup the meta-data on our instnace to reflect
        # the generation id (e.g. incremented it)
        metadata = db.instance_metadata_get(self.context, instance_id)
        self.assertEquals(metadata['generation_id'], '1',
                          "The generation id should be 1 because this is the second time the instance " \
                          "was blessed.")
    
    def test_bless_nonexisting_instance(self):
        try:
            self.gridcentric.bless_instance(self.context, 1500)
            self.fail("Suspending a non-existing instance should fail.")
        except Exception, e:
            pass # Success

    
    

