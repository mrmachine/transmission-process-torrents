import setuptools

VERSION = '0.1-dev'

setuptools.setup(
    name='transmission-process-torrents',
    version=VERSION,
    packages=setuptools.find_packages(),
    install_requires=[
        'finder_colors',
        'hardlink',
        'pyyaml',
        'requests',
        'transmission-fluid',
    ],
    entry_points={
        'console_scripts': [
            'process-torrents = process_torrents:main',
        ],
    },
)
