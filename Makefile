#!/usr/bin/make -f

build-all : nova-all
.PHONY : build-all

$(NOVA_PATH)/.venv/bin/activate :
	@python $(NOVA_PATH)/tools/install_venv.py

build-full : $(NOVA_PATH)/.venv/bin/activate
	$(NOVA_PATH)/tools/with_venv.sh $(MAKE) build-all
.PHONY : build-clean

nova-% :
	@cd nova && $(MAKE) $*
	@$(MAKE) collect

clean :
	@cd nova && $(MAKE) clean
ifeq ($(CLEAN_PACKAGES),y)
	@rm -rf build
endif
.PHONY : clean

# This basically rolls up all the artifacts to a top-level directory
collect : create-collect-dir
	@echo Collecting
	@cd nova && $(MAKE) collect COLLECT_DIR=$(PWD)/build
.PHONY : collect

create-collect-dir : build build/test-reports build/rpm build/deb build/tgz

build build/test-reports build/rpm build/deb build/tgz :
	@mkdir $@
