#!/usr/bin/make -f

# The path to the nova source code. Keeping it empty will assume that
# nova is already on the python path.
NOVA_PATH ?=

# The path to the vms source code. Keeping it empty will asusme that
# vms is already on the python path
VMS_PATH ?=

# Allow a python version spec.
PYTHON_VERSION ?= $(shell python -V 2>&1 |cut -d' ' -f2|cut -d'.' -f1,2)

# Ensure that the correct python version is used.
PYTHON ?= python$(PYTHON_VERSION)

# This command is used to setup the package directories.
INSTALL_DIR := install -d -m0755 -p
INSTALL_BIN := install -m0755 -p 
INSTALL_DATA := install -m0644 -p 

# The version of the extensions.
VERSION ?= 1.0
RELEASE ?= 0

# This matches the OpenStack release version.
OPENSTACK_RELEASE ?= unknown

# The timestamp release for the extensions.
TIMESTAMP := $(shell date "+%Y-%m-%dT%H:%M:%S%:z")

# **** TARGETS ****

full : $(NOVA_PATH)/.venv/bin/activate
	$(NOVA_PATH)/tools/with_venv.sh $(MAKE) all
.PHONY : full

$(NOVA_PATH)/.venv/bin/activate :
	@python $(NOVA_PATH)/tools/install_venv.py

all : test package pylint
.PHONY : all

# Package the extensions.
package : deb tgz
.PHONY : package

# Build the python egg files.
build-nova : build-nova-gridcentric
build-nova : build-nova-api-gridcentric
build-nova : build-novaclient-gridcentric
build-nova : build-nova-compute-gridcentric
.PHONY : build-nova
build : build-nova
.PHONY : build

build-nova-gridcentric : test-nova
	@rm -rf nova/build/ dist/nova-gridcentric
	@cd nova && PACKAGE=nova-gridcentric VERSION=$(VERSION) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/nova-gridcentric/usr
PHONY: build-nova-gridcentric

build-nova-api-gridcentric : test-nova
	@rm -rf nova/build/ dist/nova-api-gridcentric
	@cd nova && PACKAGE=nova-api-gridcentric VERSION=$(VERSION) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/nova-api-gridcentric/usr
	@sed -i -e "s/'.*' ##TIMESTAMP##/'$(TIMESTAMP)' ##TIMESTAMP##/" \
	    `find dist/nova-api-gridcentric/ -name gridcentric_extension.py`
.PHONY: build-nova-api-gridcentric

build-novaclient-gridcentric : test-nova
	@rm -rf nova/build/ dist/novaclient-gridcentric
	@cd nova && PACKAGE=novaclient-gridcentric VERSION=$(VERSION) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/novaclient-gridcentric/usr
	@$(INSTALL_DIR) dist/novaclient-gridcentric/var/lib/nova/extensions
	@$(INSTALL_BIN) nova/gridcentric/nova/osapi/gridcentric_extension.py \
	    dist/novaclient-gridcentric/var/lib/nova/extensions

.PHONY: build-novaclient-gridcentric

build-nova-compute-gridcentric : test-nova
	@rm -rf nova/build/ dist/nova-compute-gridcentric
	@cd nova && PACKAGE=nova-compute-gridcentric VERSION=$(VERSION) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/nova-compute-gridcentric/usr
	@$(INSTALL_DIR) dist/nova-compute-gridcentric/etc/init
	@$(INSTALL_DATA) nova/etc/nova-gc.conf dist/nova-compute-gridcentric/etc/init
.PHONY: build-nova-compute-gridcentric

deb-nova : deb-nova-gridcentric
deb-nova : deb-nova-api-gridcentric
deb-nova : deb-novaclient-gridcentric
deb-nova : deb-nova-compute-gridcentric
.PHONY : deb-nova
deb : deb-nova
.PHONY : deb

deb-% : build-%
	@rm -rf debbuild && $(INSTALL_DIR) debbuild
	@rsync -ruav packagers/deb/$*/ debbuild
	@rsync -ruav dist/$*/ debbuild
	@sed -i "s/\(^Version:\).*/\1 $(VERSION).$(RELEASE)-$(OPENSTACK_RELEASE)py$(PYTHON_VERSION)/" debbuild/DEBIAN/control
	@dpkg -b debbuild/ .
	@LIBDIR=`ls -1d debbuild/usr/lib*/python*`; mv $$LIBDIR/site-packages $$LIBDIR/dist-packages
	@sed -i "s/\(^Version:\).*/\1 $(VERSION).$(RELEASE)-ubuntu$(OPENSTACK_RELEASE)py$(PYTHON_VERSION)/" debbuild/DEBIAN/control
	@dpkg -b debbuild/ .

tgz-nova : tgz-nova-gridcentric
tgz-nova : tgz-nova-api-gridcentric
tgz-nova : tgz-novaclient-gridcentric
tgz-nova : tgz-nova-compute-gridcentric
.PHONY : tgz-nova
tgz : tgz-nova
.PHONY : tgz
tgz-% : build-%
	tar -cvzf $*_$(VERSION).$(RELEASE)-$(OPENSTACK_RELEASE)py$(PYTHON_VERSION).tgz -C dist/$* .

# Runs pylint on the code base.
pylint-%.txt :
	cd $* && pylint --rcfile=pylintrc gridcentric 2>&1 > $@ || true
pylint : pylint-nova.txt
.PHONY: pylint

# Executes the units tests and generated an Junit XML report.
test-%.xml : test-%
test-% :
	cd $* && PYTHONPATH=$(NOVA_PATH):$(VMS_PATH)/src/python nosetests \
	    --with-xunit --xunit-file=$(CURDIR)/$@.xml gridcentric || true
test : test-nova
.PHONY : test

clean : 
	rm -f vms.db
	rm -rf build
	rm -rf dist
	rm -f test-*.xml
	rm -f pylint-*.txt
	rm -rf *.deb debbuild
	rm -rf *.tgz
	rm -rf nova/build
.PHONY : clean
