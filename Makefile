#!/usr/bin/make -f

build-all : gc-nova-extension
.PHONY : build-all

$(NOVA_PATH)/.venv/bin/activate :
	@python $(NOVA_PATH)/tools/install_venv.py

build-full : $(NOVA_PATH)/.venv/bin/activate
	@source $(NOVA_PATH)/.venv/bin/activate; $(MAKE) build-all
	@$(MAKE) collect
.PHONY : build-clean

gc-nova-extension :
	@echo Building the gridcentric nova extension
	@cd nova && $(MAKE)
.PHONY : gc-nova-extension

clean :
	@rm -rf build
	@cd nova && $(MAKE) clean
.PHONY : clean

# This basically rolls up all the artifacts to a top-level directory
collect : create-collect-dir
	@echo Collecting
	@cd nova && $(MAKE) collect COLLECT_DIR=$(PWD)/build
.PHONY : collect

create-collect-dir : build build/test-reports build/rpm build/deb

build build/test-reports build/rpm build/deb :
	@mkdir $@
