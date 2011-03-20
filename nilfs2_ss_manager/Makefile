INSTALL = install

all:
	@echo "'make install' to install scripts"

install:
	python setup.py install
	$(INSTALL) -d $(DEST)/etc/
	$(INSTALL) -d $(DEST)/etc/default
	$(INSTALL) default/nilfs $(DEST)/etc/default
	$(INSTALL) -d $(DEST)/etc/init.d
	$(INSTALL) init.d/nilfs $(DEST)/etc/init.d
