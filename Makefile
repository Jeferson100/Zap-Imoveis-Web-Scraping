uv_install:
	uv sync --frozen --all-extras --no-dev

uv_dev_install:
	uv sync --all-extras

uv_install_scraping:
	uv sync --frozen --no-dev --extra scraping --extra geo

uv_install_ml:
	uv sync --frozen --no-dev --extra geo --extra ml --extra ml-dl

uv_install_agents:
	uv sync --frozen --no-dev --extra agents --extra vision

install:
	pip install --upgrade pip && \
		pip install -r requirements.txt