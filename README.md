Overview
========

This code extends several pieces of OpenStack's nova (compute) project, in
order to expose instances that use Virtual Memory Streaming (VMS).

This code includes an OpenStack Dashboard (horizon) plugin that allows for web
based, VMS-enabled workflows. In other words, it exposes the functionality
provided by the Gridcentric OpenStack Extension to the Dashboard.

Installation Instructions
=========================
There are two main components that need to be installed:

* API-Extension: This is the actual API extension that exposes the new REST end points
* Gridcentric Service: A new OpenStack service that performs the gridcentric specific operations.

This extension needs to be installed where-ever the nova-api and nova-compute services are running.
Note also that Gridcentric's vms package need to be installed on all of the compute nodes.

Installing from deb package:

    # Build the deb package
    $ make deb

    # Install the package found in the main directory. If using Ubuntu use the one labeled 'ubuntu'.
    $ sudo dpkg -i nova-gridcentric_1.0-{ubuntu}*.deb

Installing from source:

    # Build the extension
    $ python setup.py build

    # Install the extension
    $ sudo python setup.py install

    # Modify your nova.conf to include the API extension.
    # i.e.
    # osapi_compute_extension=nova.api.openstack.compute.contrib.standard_extensions
    # osapi_compute_extension=gridcentric.nova.osapi.gridcentric_extension.Gridcentric_extension

    # Ensure file exists
    $ sudo touch /usr/local/lib/python2.7/dist-packages/gridcentric/__init__.py

    # (Optional) Copy the nova-gridcentric upstart script (etc/nova-gc.conf) to /etc/init/
    $ sudo cp etc/nova-gc.conf /etc/init

    # Restart the nova-api service
    $ sudo restart nova-api

    # Start the nova-gridcentric service. Check the /var/log/nova/nova-gc.log file to ensure the
    # service is running. Note this is only needed on the machines running the nova-compute service.
    $ sudo start nova-gc
    $ tail /var/log/nova/nova-gc.log

Installing the Horizon plugin:

    # Add 'gridcentric.horizon' to INSTALLED_APPS
    # eg. in /etc/openstack-dashboard/local_settings.py, add the following lines
    import sys
    mod = sys.modules['openstack_dashboard.settings']
    mod.INSTALLED_APPS += ('gridcentric.horizon',)

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
        nova-gc
            Contains the script that is used to start the GridCentric manager.

    etc
        nova-gc.conf
            An upstart script for the nova-gc service.

    gridcentric
        Contains the source for the gridcentric manager that does the actual
        work to enable the GridCentric functionality.
