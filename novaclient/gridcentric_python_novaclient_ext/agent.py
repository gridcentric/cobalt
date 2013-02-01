# Copyright 2011 GridCentric Inc.
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

import sys
import time
import subprocess
import threading

from subprocess import PIPE

DEFAULT_LOCATION = "http://downloads.gridcentriclabs.com/packages/public/agent"

TEST_SCRIPT = """
exit 0
"""

# NOTE: The below script requires a single string substition,
# as the bottom. This is the base location of the package repos,
# and will default to the DEFAULT_LOCATION as provided above.
INSTALL_SCRIPT = """
PS1=
set -x
set -e
# Ensure a sensible path for all covered distributions.
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin

# Automatically determine the repo if it wasn't specified.
if grep -i "DISTRIB_ID=Ubuntu" /etc/lsb-release > /dev/null 2>&1; then
    REPO="ubuntu"
elif grep -i "CentOS" /etc/redhat-release > /dev/null 2>&1; then
    REPO="centos"
elif [ -d /etc/yum.repos.d ]; then
    REPO="rpm"
elif [ -d /etc/apt/sources.list.d ]; then
    REPO="deb"
elif test -e /usr/share/cirros; then
    REPO="cirros"
else
    echo "Could not detect Linux distribution." 1>&2
    exit 1
fi

# Figure out the remote directory.
if [ "$REPO" = "cirros" ]; then
    REPO_DIR="tgz"
else
    REPO_DIR=$REPO
fi

# Grab the machine architecture.
ARCH=$(uname -m)

# Sanitize ARCH (for tgz distributions).
case $ARCH in
    64 | x86_64 | amd64)
        ARCH=x86_64
        ;;
    32 | pae | x86_32 | i386 | i486 | i586 | i686)
        ARCH=x86_32
        ;;
    *)
        echo "Invalid architecture ($ARCH)."
        exit 1
esac

# Check if we need sudo.
if [ $(whoami) != "root" ]; then
    if [ -x /usr/bin/sudo ]; then
        SUDO=sudo
    else
        echo "Not root, and no sudo found."
    fi
else
    SUDO=
fi

install_deb_repo() {
    # Install the repository key.
    wget -O - http://downloads.gridcentriclabs.com/packages/gridcentric.key | $SUDO apt-key add -

    # Install the sources file.
    tmpfile=$(mktemp)
    cat > $tmpfile <<EOF
deb $1 gridcentric multiverse
EOF
    $SUDO mv $tmpfile /etc/apt/sources.list.d/gridcentric.list
}

kernel_warning() {
    set +x
    echo "WARNING: Unable to install kernel headers. Some VMS Performance"
    echo "\t optimizations may be disabled. The agent core functionality"
    echo "\t will remain intact."
    set -x
}

install_deb_packages() {
    # Update the metadata.
    # NOTE: We may limit it to the new sources, however below we do include
    # the linux-headers (as they may be required to build the kernel module).
    $SUDO apt-get update

    # Figure out if we need a version string.
    if [ "%(version)s" != "latest" ]; then
        VERSION==%(version)s
    else
        VERSION=
    fi

    # Try to install kernel headers if not already available
    $SUDO apt-get install  -y --force-yes linux-headers-$(uname -r) || kernel_warning
    # Install the agent packages.
    $SUDO apt-get install -o Dpkg::Options::='--force-confnew' -y --force-yes vms-agent$VERSION
}

install_rpm_repo() {
    # If we're on CentOS, we'll need dkms support.
    if [ "$REPO" = "centos" ]; then
        centos_version=$(cat /etc/redhat-release | cut -d' ' -f3 | cut -d'.' -f1)
        centos_arch=$(uname -m)
        tmpfile=$(mktemp)
        wget -O $tmpfile http://packages.sw.be/rpmforge-release/rpmforge-release-0.5.2-2.el$centos_version.rf.$(uname -m).rpm
        rpm -i $tmpfile || rpm -F $tmpfile
        rm -f $tmpfile
        rpm --import http://apt.sw.be/RPM-GPG-KEY.dag.txt
    fi

    # Import the repository key.
    rpm --import http://downloads.gridcentriclabs.com/packages/gridcentric.key

    # Generate the repo configuration.
    tmpfile=$(mktemp)
    cat > $tmpfile <<EOF
[gridcentric]
name=gridcentric
baseurl=$1
enabled=1
gpgcheck=0
EOF
    $SUDO mv $tmpfile /etc/yum.repos.d/gridcentric.repo
}
install_rpm_packages() {
    yum -y install kernel-devel-$(uname -r) || kernel_warning
    if [ "%(version)s" != "latest" ]; then
        # Install the specific version.
        $SUDO yum -y install vms-agent-%(version)s
    else
        # Install the latest.
        $SUDO yum -y install vms-agent
    fi
}

install_cirros_packages() {
    # Extract package contents.
    wget -O - $1/vms-agent-%(version)s_$ARCH.tgz | gzip -d | $SUDO tar -xv -C /
    $SUDO ln -sf /etc/init.d/vmsagent /etc/rc3.d/S99-vmsagent
    $SUDO /etc/init.d/vmsagent restart
}

# Generate our full url.
URL="%(location)s/$REPO_DIR"

if [ "$REPO" = "ubuntu" -o "$REPO" = "deb" ]; then
    install_deb_repo $URL
    install_deb_packages
elif [ "$REPO" = "centos" -o "$REPO" = "rpm" ]; then
    install_rpm_repo $URL
    install_rpm_packages
elif [ "$REPO" = "cirros" ]; then
    install_cirros_packages $URL
fi

exit 0
"""

def get_addrs(server):
    ips = []
    for network in server.networks.values():
        ips.extend(network)
    return ips

class SecureShell(object):

    def __init__(self, server, user, key_path):
        self.host     = get_addrs(server)[0]
        self.user     = user
        self.key_path = key_path

    def ssh_args(self):
        return [
                "ssh",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "StrictHostKeyChecking=no",
                "-o", "PasswordAuthentication=no",
                "-i", self.key_path,
                "%s@%s" % (self.user, self.host),
                ]

    def call(self, script):
        # Our command is always a remote shell for execution.
        command = self.ssh_args() + ['sh', '-']

        # Open an ssh instance.
        # NOTE: We used to pull fancy tricks with stdout, stderr
        # but instead we just allow them to come through as they
        # always have (to the associated terminal). It leaves us
        # with less information here, but should give the user more
        # information if something goes wrong.
        p = subprocess.Popen(command,
                             stdin=subprocess.PIPE,
                             close_fds=True)

        # Execute the command.
        p.communicate("stty -echo 2>/dev/null || true;\n" + script)
        return p.returncode

def wait_for(message, condition, duration=600, interval=1):
    sys.stderr.write("Waiting %ss for %s..." % (duration, message))
    sys.stderr.flush()
    start = time.time()
    while True:
        if condition():
            sys.stderr.write("done\n")
            return
        remaining = start + duration - time.time()
        if remaining <= 0:
            raise Exception('Timeout: waited %ss for %s' % (duration, message))
        time.sleep(min(interval, remaining))

def wait_while_status(server, status):
    def condition():
        if server.status != status:
            return True
        server.get()
        return False
    wait_for('%s on ID %s to finish' % (status, str(server.id)), condition)

def wait_for_ssh(server, user, key_path):
    ssh = SecureShell(server, user, key_path)
    wait_for('ssh ID %s to respond' % str(server.id),
             lambda: ssh.call(TEST_SCRIPT) == 0)

def do_install(server, user, key_path, location, version):
    ssh = SecureShell(server, user, key_path)
    args = { "location" : location, "version" : version }
    if ssh.call(INSTALL_SCRIPT % args) != 0:
        raise Exception("Error during installation.")

def install(server, user, key_path, location=None, version=None):
    if location == None:
        location = DEFAULT_LOCATION
    if version == None:
        version = 'latest'
    wait_while_status(server, 'BUILD')
    if server.status != 'ACTIVE':
        raise Exception("Server is not active.")
    wait_for_ssh(server, user, key_path)
    do_install(server, user, key_path, location, version)
