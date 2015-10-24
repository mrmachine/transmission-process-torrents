import setuptools

try:
    import pypandoc
    long_description = pypandoc.convert('README.md', 'rst')
except (ImportError, IOError):
    long_description = ''

setuptools.setup(
    name='transmission-process-torrents',
    version='0.1.dev0',
    description='Hard links downloaded torrents to a post processing '
                'directory and removes them once ratio and seed time '
                'requirements have been satisfied.',
    long_description=long_description,
    url='https://github.com/mrmachine/transmission-process-torrents',
    license='MIT',
    author='Tai Lee',
    author_email='real.human@mrmachine.net',
    packages=setuptools.find_packages(where='src'),
    package_dir={
        '': 'src',
    },
    install_requires=[
        'finder_colors',
        'hardlink',
        'pyyaml',
        'requests',
        'transmission-fluid',
    ],
    entry_points={
        'console_scripts': [
            'process-torrents = process_torrents.base:main',
        ],
    },
)
