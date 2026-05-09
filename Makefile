UV ?= uv

.PHONY: help setup smoke-test latest-url sync-latest sync-latest-dry-run sync-list sync-page sync-page-dry-run run

help:
	@printf "Targets:\n"
	@printf "  make setup                 Install project dependencies with uv\n"
	@printf "  make smoke-test            Fetch the latest issue and print a summary\n"
	@printf "  make latest-url            Print the latest Concrete Avalanche list URL\n"
	@printf "  make sync-latest           Match the latest issue and sync it to Spotify\n"
	@printf "  make sync-latest-dry-run   Match the latest issue without writing anything\n"
	@printf "  make sync-list LIST_URL=...  Match a specific list URL and sync it\n"
	@printf "  make sync-page PAGE_URL=...  Extract a web page and save matched albums\n"
	@printf "  make sync-page-dry-run PAGE_URL=...  Preview a web page album sync\n"
	@printf "  make run                   Alias for make sync-latest\n"

setup:
	sfw $(UV) sync

smoke-test:
	op run --env-file=.env -- $(UV) run spotify-smoke-test

latest-url:
	$(UV) run spotify-automation latest-url

sync-latest:
	op run --env-file=.env -- $(UV) run spotify-automation sync-latest

sync-latest-dry-run:
	op run --env-file=.env -- $(UV) run spotify-automation sync-latest --dry-run

sync-list:
	@test -n "$(LIST_URL)" || (echo "LIST_URL is required" && exit 1)
	op run --env-file=.env -- $(UV) run spotify-automation sync-list --list-url "$(LIST_URL)"

sync-page:
	@test -n "$(PAGE_URL)" || (echo "PAGE_URL is required" && exit 1)
	op run --env-file=.env -- $(UV) run spotify-automation sync-page --url "$(PAGE_URL)"

sync-page-dry-run:
	@test -n "$(PAGE_URL)" || (echo "PAGE_URL is required" && exit 1)
	op run --env-file=.env -- $(UV) run spotify-automation sync-page --url "$(PAGE_URL)" --dry-run

run: sync-latest
