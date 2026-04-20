uv_install:
	uv pip install --upgrade pip && \
		uv pip install -r pyproject.toml

uv_dev_install:
	uv pip install -e ".[dev]"

install:
	pip install --upgrade pip && \
		pip install -r requirements.txt