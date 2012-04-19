Project Contents
================
    bin
        nova-gc
            Contains the nova-gc script that is used to start the GridCentric manager.
    
    etc
        nova-gridcentric.con
            An upstart script for the nova-gridcentric service.
    
    gridcentric
        Contains the source for the gridcentric manager that does the actual work to enable the
        GridCentric functionality.
    
    tools
        gc-api
            A management tool that uses the python novaclient to provide a cli to the extended
            functionality.
