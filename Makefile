.PHONY: build
build:
	docker build . -t 660440363484.dkr.ecr.us-west-2.amazonaws.com/opencap/api

.PHONY: push
push:
	aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 660440363484.dkr.ecr.us-west-2.amazonaws.com
	docker push 660440363484.dkr.ecr.us-west-2.amazonaws.com/opencap/api

.PHONY: run
run:
	docker kill mcserver | true
	docker rm mcserver | true
	docker run --name mcserver -v $(shell pwd)/mcserver:/code/mcserver -v $(shell pwd)/data:/code/data -v $(shell pwd)/.env:/code/.env -p 80:80 -d 660440363484.dkr.ecr.us-west-2.amazonaws.com/opencap/api

.PHONY: debug
debug:
	docker kill mcserver | true
	docker rm mcserver | true
	docker run --name mcserver -e DEBUG=True -v $(shell pwd)/.env:/code/.env -p 80:80 -d 660440363484.dkr.ecr.us-west-2.amazonaws.com/opencap/api

.PHONY: runit
runit:
	docker kill mcserver | true
	docker rm mcserver | true
	docker run --name mcserver -v $(shell pwd)/.env:/code/.env -p 80:80 -it 660440363484.dkr.ecr.us-west-2.amazonaws.com/opencap/api

.PHONY: linkcode
linkcode:
	docker kill mcserver | true
	docker rm mcserver | true
	docker run --name mcserver -v $(shell pwd)/.env:/code/.env -p 80:80 -it 660440363484.dkr.ecr.us-west-2.amazonaws.com/opencap/api /bin/bash


