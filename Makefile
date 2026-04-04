check:
	prek run --all

hassfest:
	podman run --rm -v "$(PWD)/custom_components:/github/workspace" ghcr.io/home-assistant/hassfest

update:
	prek autoupdate
	uv sync --upgrade
