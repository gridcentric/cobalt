Overview
========

This code extends several pieces of OpenStack's nova (compute) project, in
order to expose instances that use Virtual Memory Streaming (VMS).

Installation Instructions
=========================
There are two main components that need to be installed:

* API-Extension: This is the actual API extension that exposes the new REST end points
* Cobalt service: A new OpenStack service that performs the Gridcentric-specific operations.

This extension needs to be installed where-ever the nova-api and nova-compute services are running.
Note also that Gridcentric's vms package need to be installed on all of the compute nodes.

Installing from source:

    # Build the extension
    $ python setup.py build
    
    # Install the extension
    $ sudo python setup.py install
    
    # Modify your nova.conf to include the API extension.
    # i.e.
    # osapi_compute_extension=nova.api.openstack.compute.contrib.standard_extensions
    # osapi_compute_extension=cobalt.nova.osapi.cobalt_extension.CobaltExtension

    # (Optional) Copy the upstart script (etc/cobalt-compute.conf) to /etc/init/
    $ sudo cp etc/cobalt-compute.conf /etc/init
    
    # Restart the nova-api service
    $ sudo restart nova-api
    
    # Start the cobalt-compute service. Check the /var/log/nova/compute-compute.log
    # file to ensure the service is running. Note this is only needed on the machines
    # running the nova-compute service.
    $ sudo start cobalt-compute
    $ tail /var/log/nova/cobalt-compute.log


Usage
=====

    # Boot a new instance using the regular OpenStack API
    $ nova boot --flavor 1 --image 1 ChromeOS-HVM
    
    # Wait for the first instance to move from BUILD to ACTIVE. Once ACTIVE ssh into the instance
    # and install the vms-agent package. The agent package is used to ensure that the networking is
    # reconfigured correctly when launching new instances.
    
    # Bless the instance. This will create a running snapshot of the instance that can later be
    # used to launch new instances. Launched instances will be started with the same loaded memory
    # as this blessed one.
    $ nova bless <id of the instance from step 1>
    
    # List the nova instances and there should now be a new one with a status of BLESSED. This
    # instance represents a blessed snapshot that can be launched. Note that this instance is not
    # using any CPU or RAM resources.
    
    # Launch more instances based off of the blessed one
    $ nova launch <blessed instance id>
    $ nova launch <blessed instance id>
    # ... etc ...
    
    # Delete the launched instances.
    $ nova delete <instance_id>
    
    # Discard the blessed instance. This will clean up all the VMS artifacts associated with the
    # snapshot and remove the blessed instance from the nova database.
    $ nova discard <blessed instance id>

Project Contents
================

    bin
        cobalt-compute
            Contains the script that is used to start the Cobalt manager.

    etc
        cobalt-compute.conf
            An upstart script for the cobalt-compute service.

    cobalt
        Contains the source for the manager and extensions.
