PROJECT=jupyterhub-binderhub
REPO=registry.rc.nectar.org.au/nectar

DESCRIBE=$(shell git describe --tags)
IMAGE_TAG := $(if $(TAG),$(TAG),$(DESCRIBE))
IMAGE=$(REPO)/$(PROJECT):$(IMAGE_TAG)
BUILDER=docker
BUILDER_ARGS=--no-cache


build:
	$(BUILDER) build $(BUILDER_ARGS) -t $(IMAGE) .

push:
	$(BUILDER) push $(IMAGE)

.PHONY: build push
