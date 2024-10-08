# Use the full Anaconda base image
FROM continuumio/anaconda3:latest

WORKDIR /code

# Create a new Conda environment with Python 3.11.9
RUN conda create --name stingray_env python=3.11.9 -y

# Activate the environment and upgrade pip
RUN conda run -n stingray_env pip install --no-cache-dir --upgrade pip

# Install all dependencies using pip within the Conda environment
RUN conda run -n stingray_env pip install --no-cache-dir astropy \
    scipy \
    matplotlib \
    numpy \
    tqdm \
    numba \
    pint-pulsar \
    emcee \
    corner \
    statsmodels \
    stingray \
    panel \
    watchfiles \
    holoviews \
    hvplot \
    param \
    pandas \
    h5py \
    datashader

# Set environment variables
ENV NUMBA_CACHE_DIR=/tmp/numba_cache

# Copy the application code
COPY . .

# Create the necessary directories with appropriate permissions
RUN mkdir -p /code/files/loaded-data && chmod -R 777 /code/files
RUN mkdir -p /tmp/numba_cache && chmod -R 777 /tmp/numba_cache


# Set the shell to activate the Conda environment by default
SHELL ["conda", "run", "-n", "stingray_env", "/bin/bash", "-c"]

# Command to run the Panel app within the Conda environment
CMD ["conda", "run", "--no-capture-output", "-n", "stingray_env", "panel", "serve", "explorer.py", "--autoreload", "--static-dirs", "assets=./assets", "--address", "0.0.0.0", "--port", "7860", "--allow-websocket-origin", "*"]
