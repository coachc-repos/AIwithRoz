.PHONY: run smoke save

run:
	docker compose up --build

smoke:
	./smoke-test.sh

save:
	docker save scriptcraft-hackathon:latest | gzip > scriptcraft-hackathon.tar.gz
	@echo "wrote scriptcraft-hackathon.tar.gz"
