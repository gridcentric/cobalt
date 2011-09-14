#!/usr/bin/env bash
#
# This is a slightly modified version of the nova.sh file from the main OpenStack project. This script
# can be used to setup a development environemnt and have the nova develpoment run from the source.
# Modifications were made so that the gridcentric extensions would be included.

DIR=`pwd`
CMD=$1
if [ "$CMD" = "branch" ]; then
    SOURCE_BRANCH=${2:-lp:nova}
    DIRNAME=${3:-nova}
else
    DIRNAME=${2:-nova}
fi

NOVA_DIR=$DIR/$DIRNAME
GC_EXT_DIR=../

if [ ! -n "$HOST_IP" ]; then
    # NOTE(vish): This will just get the first ip in the list, so if you
    #             have more than one eth device set up, this will fail, and
    #             you should explicitly set HOST_IP in your environment
    HOST_IP=`LC_ALL=C ifconfig  | grep -m 1 'inet addr:'| cut -d: -f2 | awk '{print $1}'`
fi

USE_MYSQL=${USE_MYSQL:-0}
INTERFACE=${INTERFACE:-eth0}
FLOATING_RANGE=${FLOATING_RANGE:-192.168.11.0/24}
FIXED_RANGE=${FIXED_RANGE:-10.0.0.0/24}
MYSQL_PASS=${MYSQL_PASS:-nova}
TEST=${TEST:-0}
USE_LDAP=${USE_LDAP:-0}
# Use OpenDJ instead of OpenLDAP when using LDAP
USE_OPENDJ=${USE_OPENDJ:-0}
# Use IPv6
USE_IPV6=${USE_IPV6:-0}
LIBVIRT_TYPE=${LIBVIRT_TYPE:-qemu}
NET_MAN=${NET_MAN:-FlatManager}
# NOTE(vish): If you are using FlatDHCP on multiple hosts, set the interface
#             below but make sure that the interface doesn't already have an
#             ip or you risk breaking things.
# FLAT_INTERFACE=eth0

# XENAPI configurations parameters
XEN_CONN_URL=${XEN_CONN_URL:-http://node1}
XEN_CONN_USER=${XEN_CONN_USR:-root}
XEN_CONN_PASS=${XEN_CONN_PASS:-default}


if [ "$USE_MYSQL" == 1 ]; then
    SQL_CONN=mysql://root:$MYSQL_PASS@localhost/nova
else
    SQL_CONN=sqlite:///$NOVA_DIR/nova.sqlite
fi

if [ "$USE_LDAP" == 1 ]; then
    AUTH=ldapdriver.LdapDriver
else
    AUTH=dbdriver.DbDriver
fi

if [ "$CMD" == "branch" ]; then
    sudo apt-get install -y bzr
    if [ ! -e "$DIR/.bzr" ]; then
        bzr init-repo $DIR
    fi
    rm -rf $NOVA_DIR
    bzr branch $SOURCE_BRANCH $NOVA_DIR
    cd $NOVA_DIR
    mkdir -p $NOVA_DIR/instances
    mkdir -p $NOVA_DIR/networks
    exit
fi

# You should only have to run this once
if [ "$CMD" == "install" ]; then
    sudo apt-get install -y python-software-properties
    sudo add-apt-repository ppa:nova-core/trunk
    sudo apt-get update
    sudo apt-get install -y dnsmasq-base kpartx kvm gawk iptables ebtables
    sudo apt-get install -y user-mode-linux kvm libvirt-bin
    sudo apt-get install -y screen euca2ools vlan curl rabbitmq-server
    sudo apt-get install -y lvm2 iscsitarget open-iscsi
    sudo apt-get install -y socat unzip
    echo "ISCSITARGET_ENABLE=true" | sudo tee /etc/default/iscsitarget
    sudo /etc/init.d/iscsitarget restart
    sudo modprobe kvm
    sudo /etc/init.d/libvirt-bin restart
    sudo modprobe nbd
    sudo apt-get install -y python-twisted python-mox python-ipy python-paste
    sudo apt-get install -y python-migrate python-gflags python-greenlet
    sudo apt-get install -y python-libvirt python-libxml2 python-routes
    sudo apt-get install -y python-netaddr python-pastedeploy python-eventlet
    sudo apt-get install -y python-novaclient python-glance python-cheetah
    sudo apt-get install -y python-carrot python-tempita python-sqlalchemy
    sudo apt-get install -y python-suds


    if [ "$USE_IPV6" == 1 ]; then
        sudo apt-get install -y radvd
        sudo bash -c "echo 1 > /proc/sys/net/ipv6/conf/all/forwarding"
        sudo bash -c "echo 0 > /proc/sys/net/ipv6/conf/all/accept_ra"
    fi

    if [ "$USE_MYSQL" == 1 ]; then
        cat <<MYSQL_PRESEED | debconf-set-selections
mysql-server-5.1 mysql-server/root_password password $MYSQL_PASS
mysql-server-5.1 mysql-server/root_password_again password $MYSQL_PASS
mysql-server-5.1 mysql-server/start_on_boot boolean true
MYSQL_PRESEED
        apt-get install -y mysql-server python-mysqldb
    fi
    mkdir -p $DIR/images
    wget -c http://images.ansolabs.com/tty.tgz
    tar -C $DIR/images -zxf tty.tgz
    exit
fi

NL=`echo -ne '\015'`

function screen_it {
    screen -S nova -X screen -t $1
    screen -S nova -p $1 -X stuff "$2$NL"
}

if [ "$CMD" == "run" ] || [ "$CMD" == "run_detached" ]; then

  cat >$NOVA_DIR/bin/nova.conf << NOVA_CONF_EOF
--verbose
--nodaemon
--dhcpbridge_flagfile=$NOVA_DIR/bin/nova.conf
--network_manager=nova.network.manager.$NET_MAN
--flat_network_bridge=xenbr1
--my_ip=$HOST_IP
--public_interface=$INTERFACE
--vlan_interface=$INTERFACE
--sql_connection=$SQL_CONN
--auth_driver=nova.auth.$AUTH
--libvirt_type=$LIBVIRT_TYPE
--connection_type=xenapi
--xenapi_connection_url=$XEN_CONN_URL
--xenapi_connection_username=$XEN_CONN_USER
--xenapi_connection_password=$XEN_CONN_PASS
--image_service=nova.image.glance.GlanceImageService
--glance_api_servers=localhost:9292
--osapi_extensions_path=$GC_EXT_DIR/extension/
--osapi_path=/v1.1/
--gridcentric_manager=gridcentric.nova.extension.manager.GridCentricManager
NOVA_CONF_EOF

    if [ -n "$FLAT_INTERFACE" ]; then
        echo "--flat_interface=$FLAT_INTERFACE" >>$NOVA_DIR/bin/nova.conf
    fi

    if [ "$USE_IPV6" == 1 ]; then
        echo "--use_ipv6" >>$NOVA_DIR/bin/nova.conf
    fi

    glance-control all stop
    killall dnsmasq
    if [ "$USE_IPV6" == 1 ]; then
       killall radvd
    fi
    screen -d -m -S nova -t nova
    sleep 1
    if [ "$USE_MYSQL" == 1 ]; then
        mysql -p$MYSQL_PASS -e 'DROP DATABASE nova;'
        mysql -p$MYSQL_PASS -e 'CREATE DATABASE nova;'
    else
        rm $NOVA_DIR/nova.sqlite
    fi
    if [ "$USE_LDAP" == 1 ]; then
        if [ "$USE_OPENDJ" == 1 ]; then
            echo '--ldap_user_dn=cn=Directory Manager' >> \
                /etc/nova/nova-manage.conf
            sudo $NOVA_DIR/nova/auth/opendj.sh
        else
            sudo $NOVA_DIR/nova/auth/slap.sh
        fi
    fi
    rm -rf $NOVA_DIR/instances
    mkdir -p $NOVA_DIR/instances
    rm -rf $NOVA_DIR/networks
    mkdir -p $NOVA_DIR/networks
    if [ "$TEST" == 1 ]; then
        cd $NOVA_DIR
        python $NOVA_DIR/run_tests.py
        cd $DIR
    fi

    # create the database
    $NOVA_DIR/bin/nova-manage db sync
    # create an admin user called 'admin'
    $NOVA_DIR/bin/nova-manage user admin admin admin admin
    # create a project called 'admin' with project manager of 'admin'
    $NOVA_DIR/bin/nova-manage project create admin admin
    # create a small network
    $NOVA_DIR/bin/nova-manage network create $FIXED_RANGE 1 32

    if [ "$NET_MAN" == "VlanManager" ]; then

        #Update the VLAN informtion in the database
        sudo sqlite3 $NOVA_DIR/nova.sqlite << VLAN_CONFIG_EOF
update networks set vlan = '0' where id = 1;
update networks set bridge = 'br_vlan0' where id = 1;
update networks set gateway = '10.0.0.7' where id = 1;
update networks set dhcp_start = '10.0.0.8' where id = 1;
update fixed_ips set reserved = 1 where address in ('10.0.0.1','10.0.0.2','10.0.0.3','10.0.0.4','10.0.0.5','10.0.0.6','10.0.0.7');
.quit
VLAN_CONFIG_EOF

    else
        sqlite3 $NOVA_DIR/nova.sqlite << NETWORK_CONFIG_EOF
update networks set bridge = 'xenbr1' where id = 1;
.quit
NETWORK_CONFIG_EOF
    fi


    # create some floating ips
    $NOVA_DIR/bin/nova-manage floating create `hostname` $FLOATING_RANGE

    if [ ! -d "$NOVA_DIR/images" ]; then
        if [ ! -d "$DIR/converted-images" ]; then
            # convert old images
            mkdir $DIR/converted-images
            ln -s $DIR/converted-images $NOVA_DIR/images
            $NOVA_DIR/bin/nova-manage image convert $DIR/images
        else
            ln -s $DIR/converted-images $NOVA_DIR/images
        fi

    fi

    # nova api crashes if we start it with a regular screen command,
    # so send the start command by forcing text into the window.
    SET_PYTHONPATH="export PYTHONPATH=$NOVA_DIR:$GC_EXT_DIR"
    screen_it api "$SET_PYTHONPATH; $NOVA_DIR/bin/nova-api"
    screen_it objectstore "$NOVA_DIR/bin/nova-objectstore"
    screen_it compute "$NOVA_DIR/bin/nova-compute --network_driver=nova.network.xenapi_net"
    screen_it network "$NOVA_DIR/bin/nova-network"
    screen_it scheduler "$NOVA_DIR/bin/nova-scheduler"
    screen_it volume "$NOVA_DIR/bin/nova-volume"
    screen_it ajax_console_proxy "$NOVA_DIR/bin/nova-ajax-console-proxy"
    
    # Start the glance image service
    screen_it glance "glance-control all start"
    
    # Start the gridcentric service
    screen_it gridcentic "$SET_PYTHONPATH; $GC_EXT_DIR/bin/nova-gridcentric --flagfile=$NOVA_DIR/bin/nova.conf"
    
    sleep 2
    # export environment variables for project 'admin' and user 'admin'
    $NOVA_DIR/bin/nova-manage project zipfile admin admin $NOVA_DIR/nova.zip
    unzip -o $NOVA_DIR/nova.zip -d $NOVA_DIR/

    screen_it test "export PATH=$NOVA_DIR/bin:$GC_EXT_DIR/bin:$GC_EXT_DIR/tools:$PATH;. $NOVA_DIR/novarc"
    if [ "$CMD" != "run_detached" ]; then
      screen -S nova -x
    fi
fi

if [ "$CMD" == "run" ] || [ "$CMD" == "terminate" ]; then
    # shutdown instances
    . $NOVA_DIR/novarc; euca-describe-instances | grep i- | cut -f2 | xargs euca-terminate-instances
    sleep 2
    # delete volumes
    . $NOVA_DIR/novarc; euca-describe-volumes | grep vol- | cut -f2 | xargs -n1 euca-delete-volume
    sleep 2
fi

if [ "$CMD" == "run" ] || [ "$CMD" == "clean" ]; then
    screen -S nova -X quit
    rm *.pid*
fi

if [ "$CMD" == "scrub" ]; then
    $NOVA_DIR/tools/clean-vlans
    if [ "$LIBVIRT_TYPE" == "uml" ]; then
        virsh -c uml:///system list | grep i- | awk '{print \$1}' | xargs -n1 virsh -c uml:///system destroy
    else
        virsh list | grep i- | awk '{print \$1}' | xargs -n1 virsh destroy
    fi
fi
