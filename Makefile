.PHONY: bootstrap install test compile verify smoke release-check alpha-check bench bench-quick

bootstrap:
	python3 -m venv .venv
	.venv/bin/python -m pip install -U pip setuptools wheel
	.venv/bin/python -m pip install -e .

install:
	python3 -m pip install -e .

test:
	python3 -m unittest discover -s tests -q

compile:
	python3 -m compileall src examples/two-agent-demo tests

verify: test compile

smoke:
	PYTHONPATH=src python3 -m loom --version

release-check:
	python3 -W error::ResourceWarning -m unittest tests.test_alpha_contract tests.test_entrypoint tests.test_quickstart tests.test_two_agent_demo tests.test_daemon.DaemonTest.test_real_daemon_smoke_start_claim_status_and_stop -q
	PYTHONPATH=src python3 -m loom --version
	PYTHONPATH=src python3 -m loom --help >/dev/null

alpha-check:
	$(MAKE) release-check
	python3 -W error::ResourceWarning -m unittest discover -s tests -q
	python3 -m compileall src examples/two-agent-demo tests

bench:
	python3 tools/run_benchmarks.py --label bench --rounds 5 --python-files 500 --script-files 500

bench-quick:
	python3 tools/run_benchmarks.py --label quick --rounds 2 --python-files 100 --script-files 100
