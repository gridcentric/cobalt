Overview
========

An extension hook for novaclient that enables it to interact with the Gridcentric endpoints.

Command line usage
==================

After installing the operations provided by the Gridcentric extension will be available to the 
nova command line application:

    # Display all of the available commands of the nova script. The gridcentric bless, launch, 
    # list-blessed, list-launched, discard and gc-migrate are listed.
    $ nova help
    
    # Doing nova help <command> on any of these commands will display how to use them in detail.
    $ nova help bless
    usage: nova bless <instance id>
    
    Bless an instance
    
    Positional arguments:
      <instance id>  ID of the instance to bless
    
    $ nova help launch
    usage: nova launch [--target <target memory>] [--params <key=value>]
                       <blessed id>
    
    Launch a new instance
    
    Positional arguments:
      <blessed id>          ID of the blessed instance
    
    Optional arguments:
      --target <target memory>
                            The memory target of the launched instance
      --params <key=value>  Guest parameters to send to vms-agent
    
    $ nova help discard
    usage: nova discard <blessed id>
    
    Discard a blessed instance
    
    Positional arguments:
      <blessed id>  ID of the blessed instance
    
    $ nova help gc-migrate
    usage: nova gc-migrate <instance id> <destination host>
    
    Migrate an instance using Gridcentric VMS
    
    Positional arguments:
      <instance id>       ID of the instance to migrate
      <destination host>  Host to migrate to
    
    $ nova help list-launched
    usage: nova list-launched <blessed id>
    
    List instances launched from this blessed instance.
    
    Positional arguments:
      <blessed id>  ID of the blessed instance
    
    $ nova help list-blessed
    usage: nova list-blessed <server id>
    
    List instances blessed from this instance.
    
    Positional arguments:
      <server id>  ID of the instance
    

Scripting usage
===============

The novaclient hooks can also be accessed directly using the python API.

    user = "admin"
    apikey = "admin"
    project = "openstackDemo"
    authurl = "http://localhost:5000/v2.0" 
    
    extensions = shell.OpenStackComputeShell()._discover_extensions("1.1")
    novaclient = NovaClient(user, apikey, project, authurl, extensions=extensions,
                            endpoint_type=shell.DEFAULT_NOVA_ENDPOINT_TYPE,
                            service_type=shell.DEFAULT_NOVA_SERVICE_TYPE)
    
    def wait_for_status(server, status):
        while server.status != status:
            time.sleep(30)
            server = novaclient.gridcentric.get(server.id)
        return server

    def wait_until_gone(server):
        try:
            while True:
                server = novaclient.gridcentric.get(server.id)
                time.sleep(10)
        except Exception, e:
            # server is no longer there.
            pass

    # Boot a new server using flavor 1 and the image passed in as the first arguement.
    image_id = sys.argv[1]
    flavor_id = 1
    server = novaclient.servers.create("Gridcentric instance",
                                  image_id,
                                  flavor_id)
    server = wait_for_status(server, "ACTIVE")
    
    # Bless the server. This will return an instance of the blessed_server. We need to
    # wait until the server becomes active.
    blessed_server = novaclient.gridcentric.bless(server)[0]
    blessed_server = wait_for_status(blessed_server, "BLESSED")
    
    # Launch a new server based off of the blessed one. Note that we can do this
    # by either calling launch on the server itself, or passing the server into the
    # gridcentric manager.
    launched_server = blessed_server.launch()[0]
    launched_server2 = novaclient.gridcentric.launch(blessed_server)[0]
    
    # list the servers that were launched from the blessed ones.
    for s in blessed_server.list_launched():
        print "Server %s was launched from %s" %(s.id, blessed_server.id)
        
    # Delete the launched servers.
    launched_server2 = wait_for_status(launched_server2, "ACTIVE")
    launched_server2.delete()
    launched_server = wait_for_status(launched_server, "ACTIVE")
    novaclient.servers.delete(launched_server)

    # W need to ensure that the launched instances have been deleted before discarding
    # the blessed instance.
    wait_until_gone(launched_server2)
    wait_until_gone(launched_server)

    # Delete the original server. Note we can delete this server
    # and keep the blessed one around.
    server.delete()

    # Discard the blessed server
    blessed_server.discard()
