
build-all : gc-nova-extension
.PHONY : build-all

gc-nova-extension :
	@echo Building the gridcentric nova extension
	@cd openstack/nova; $(MAKE) 
.PHONY : gc-nova-extension

clean :
	@cd openstack/nova; $(MAKE) clean
.PHONY : clean

# This basically rolls up all the artifacts to a top-level directory
collect : create-collect-dir
	@echo Collecting
	@cd openstack/nova; $(MAKE) collect COLLECT_DIR=$(PWD)/build
.PHONY : collect

create-collect-dir : build build/test-reports

build build/test-reports :       
	@mkdir $@

