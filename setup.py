try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='happycowler',
    version='0.2.4',
    author='Peter Wittek',
    author_email='peterwittek@users.noreply.github.com',
    packages=['happycowler'],
    scripts=['scripts/happycowl'],
    url='https://github.com/peterwittek/happycowler/',
    keywords='vegan vegetarian happycow.net crawler kml gpx',
    license='LICENSE',
    description='Crawl the HappyCow database to GPX or KML files for offline use.',
    long_description=open('README.rst').read(),
    classifiers=[
         'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
         'Operating System :: OS Independent',
         'Intended Audience :: End Users/Desktop',
         'Development Status :: 4 - Beta',
         'Programming Language :: Python'
    ],
    entry_points={
        'console_scripts': [
            'happycowler-mcp=happycowler.mcp_server:main',
        ],
    },
    install_requires=[
        "beautifulsoup4 >= 4",
        "incapsula-cracker-py3",
        "mcp >= 1.0",
    ],
    test_suite="tests"
)
