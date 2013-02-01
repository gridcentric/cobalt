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
package : deb tgz pip rpm
.PHONY : package

# Build the python egg files.
build-nova : build-nova-gridcentric
build-nova : build-nova-api-gridcentric
build-nova : build-nova-compute-gridcentric
.PHONY : build-nova
build-novaclient : build-novaclient-gridcentric
.PHONY: build-novaclient
build-horizon : build-horizon-gridcentric
.PHONY : build-horizon
build : build-nova build-novaclient build-horizon
.PHONY : build

build-nova-gridcentric : test-nova
	@rm -rf nova/build/ dist/nova-gridcentric
	@cd nova && PACKAGE=nova-gridcentric VERSION=$(VERSION).$(RELEASE) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/nova-gridcentric/usr
PHONY: build-nova-gridcentric

build-nova-api-gridcentric : test-nova
	@rm -rf nova/build/ dist/nova-api-gridcentric
	@cd nova && PACKAGE=nova-api-gridcentric VERSION=$(VERSION).$(RELEASE) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/nova-api-gridcentric/usr
	@sed -i -e "s/'.*' ##TIMESTAMP##/'$(TIMESTAMP)' ##TIMESTAMP##/" \
	    `find dist/nova-api-gridcentric/ -name gridcentric_extension.py`
.PHONY: build-nova-api-gridcentric

build-novaclient-gridcentric :
	@rm -rf novaclient/build/ novaclient/*.egg-info dist/novaclient-gridcentric
	@mkdir -p $(CURDIR)/dist/novaclient-gridcentric/usr/lib/$(PYTHON)/site-packages
	@cd novaclient && VERSION=$(VERSION).$(RELEASE) __SETUP=distutils \
	    PYTHONPATH=$(CURDIR)/dist/novaclient-gridcentric/usr/lib/$(PYTHON)/site-packages \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/novaclient-gridcentric/usr
.PHONY: build-novaclient-gridcentric

build-nova-compute-gridcentric : test-nova
	@rm -rf nova/build/ dist/nova-compute-gridcentric
	@cd nova && PACKAGE=nova-compute-gridcentric VERSION=$(VERSION).$(RELEASE) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/nova-compute-gridcentric/usr
	@$(INSTALL_DIR) dist/nova-compute-gridcentric/etc/init
	@$(INSTALL_DATA) nova/etc/nova-gc.conf dist/nova-compute-gridcentric/etc/init
	@$(INSTALL_DIR) dist/nova-compute-gridcentric/etc/init.d
	@$(INSTALL_BIN) nova/etc/nova-gc dist/nova-compute-gridcentric/etc/init.d
.PHONY: build-nova-compute-gridcentric

build-horizon-gridcentric : test-horizon.xml
	@rm -rf horizon/build/ dist/horizon-gridcentric
	@cd horizon && VERSION=$(VERSION).$(RELEASE) \
	    $(PYTHON) setup.py install --prefix=$(CURDIR)/dist/horizon-gridcentric/usr
.PHONY: build-horizon-gridcentric

deb-nova : deb-nova-gridcentric
deb-nova : deb-nova-api-gridcentric
deb-nova : deb-nova-compute-gridcentric
.PHONY : deb-nova
deb-novaclient : deb-novaclient-gridcentric
.PHONY : deb-novaclient
deb-horizon : deb-horizon-gridcentric
.PHONY : deb-horizon
deb : deb-nova deb-novaclient deb-horizon 
.PHONY : deb

deb-% : build-%
	@rm -rf debbuild && $(INSTALL_DIR) debbuild
	@rsync -ruav packagers/deb/$*/ debbuild
	@rsync -ruav dist/$*/ debbuild
	@rm -rf debbuild/etc/init.d
	@sed -i "s/\(^Version:\).*/\1 $(VERSION).$(RELEASE)-$(OPENSTACK_RELEASE)py$(PYTHON_VERSION)/" debbuild/DEBIAN/control
	@dpkg -b debbuild/ .
	@LIBDIR=`ls -1d debbuild/usr/lib*/python*`; mv $$LIBDIR/site-packages $$LIBDIR/dist-packages
	@sed -i "s/\(^Version:\).*/\1 $(VERSION).$(RELEASE)-ubuntu$(OPENSTACK_RELEASE)py$(PYTHON_VERSION)/" debbuild/DEBIAN/control
	@dpkg -b debbuild/ .

tgz-nova : tgz-nova-gridcentric
tgz-nova : tgz-nova-api-gridcentric
tgz-nova : tgz-nova-compute-gridcentric
.PHONY : tgz-nova
tgz-novaclient : tgz-novaclient-gridcentric
.PHONY : tgz-novaclient
tgz-horizon : tgz-horizon-gridcentric
.PHONY : tgz-horizon
tgz : tgz-nova tgz-novaclient tgz-horizon
.PHONY : tgz

tgz-% : build-%
	tar -cvzf $*_$(VERSION).$(RELEASE)-$(OPENSTACK_RELEASE)py$(PYTHON_VERSION).tgz -C dist/$* .

pip : pip-novaclient-gridcentric
	@rm -rf novaclient/build/ novaclient/dist/ novaclient/*.egg-info
	@cd novaclient && VERSION=$(VERSION).$(RELEASE) \
	    $(PYTHON) setup.py sdist
	@cp novaclient/dist/*.tar.gz .
.PHONY: pip

pip-novaclient-gridcentric :
.PHONY: pip-novaclient-gridcentric

rpm-nova : rpm-nova-gridcentric
rpm-nova : rpm-nova-api-gridcentric
rpm-nova : rpm-nova-compute-gridcentric
.PHONY : rpm-nova

rpm-novaclient : rpm-novaclient-gridcentric
.PHONY : rpm-novaclient

rpm : rpm-nova rpm-novaclient
.PHONY : rpm

rpm-%: build-%
	@rm -rf dist/$*/etc/init
	@rpmbuild -bb --buildroot $(PWD)/rpmbuild/BUILDROOT \
	  --define="%_topdir $(PWD)/rpmbuild" --define="%version $(VERSION).$(RELEASE)" \
	  --define="%release $(NOVA_RELEASE)py$(PYTHON_VERSION)" packagers/rpm/$*.spec
	@cp rpmbuild/RPMS/noarch/*.rpm .
.PHONY : rpm

# Runs pylint on the code base.
pylint-%.txt :
	cd $* && pylint --rcfile=pylintrc gridcentric 2>&1 > $@ || true
pylint : pylint-nova.txt pylint-novaclient.txt pylint-horizon.txt
.PHONY: pylint

# Executes the units tests and generated an Junit XML report.
test-%.xml : test-%
test-% :
	cd $* && PYTHONPATH=$(PYTHONPATH):$(NOVA_PATH):$(VMS_PATH) nosetests \
	    --with-xunit --xunit-file=$(CURDIR)/$@.xml gridcentric || true
test : test-nova test-horizon
.PHONY : test

clean : 
	rm -f vms.db
	rm -rf build
	rm -rf dist
	rm -f test-*.xml
	rm -f pylint-*.txt
	rm -rf *.deb debbuild
	rm -rf *.tgz *.tar.gz
	rm -rf *.rpm rpmbuild
	rm -rf nova/build novaclient/build horizon/build
	rm -rf nova/dist novaclient/dist horizon/dist
	rm -rf novaclient/MANIFEST novaclient/requires.txt novaclient/*.egg-info
.PHONY : clean
